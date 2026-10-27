"""Smoke tests on the bundled synthetic sample (a few seconds, no downloads)."""
import contextlib
import datetime
import io
import pickle
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import download_data  # noqa: E402
from pipeline import plan as plan_module  # noqa: E402
from pipeline.act import execute_actions  # noqa: E402
from pipeline.check import check_actions  # noqa: E402
from pipeline.fuse import create_time_windows, fuse_modalities  # noqa: E402
from pipeline.ingest import load_data  # noqa: E402
from pipeline.observe import generate_report  # noqa: E402
from pipeline.plan import plan_analysis  # noqa: E402
from pipeline.safe_npy import load_npy  # noqa: E402

CONFIG = str(REPO / "config" / "pipeline_config.yaml")
ROOT_CAUSE = "scenario10-malware-deployment-57db4df9f4-p8h7h"


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


@pytest.fixture(scope="module")
def sample():
    data = quiet(load_data, CONFIG)
    return data, quiet(fuse_modalities, data)


def test_safe_loader_refuses_code(tmp_path):
    # A pickle that names something other than plain data or numpy arrays is refused
    np.save(tmp_path / "evil.npy", np.array({'when': datetime.datetime(2024, 1, 1)}, dtype=object), allow_pickle=True)
    with pytest.raises(pickle.UnpicklingError):
        load_npy(tmp_path / "evil.npy")
    np.save(tmp_path / "ok.npy", np.array({'Pod_Name': ['a'], 'Sequence': np.zeros((2, 1))}, dtype=object))
    assert load_npy(tmp_path / "ok.npy")['Pod_Name'] == ['a']


def test_windows_do_not_overlap():
    windows = create_time_windows(0, 4999, 300)
    assert len(windows) == 17 and windows[0] == (0, 300) and windows[-1] == (4800, 5000)
    assert all(a[1] == b[0] for a, b in zip(windows, windows[1:]))


def test_fuse_shape(sample):
    _, fused = sample
    assert fused.shape == (136, 67)
    assert fused['pod'].nunique() == 8 and fused['window_start'].nunique() == 17


def test_baseline_is_split_by_time_not_by_pod_name(sample):
    data, fused = sample
    result = quiet(plan_analysis, fused, data['config'])
    assert result['incident']['detected'] and result['incident']['start'] == 3600
    assert result['pod_ranking'].index[0] == ROOT_CAUSE
    assert result['summary']['affected_pods'] == 8

    # Renaming the pods (so they sort differently) must not change which pod is flagged
    renamed = fused.copy()
    renamed['pod'] = renamed['pod'].map(lambda p: ('a-' if p == ROOT_CAUSE else 'z-') + p)
    renamed.attrs = fused.attrs
    again = quiet(plan_analysis, renamed, data['config'])
    assert again['pod_ranking'].index[0] == 'a-' + ROOT_CAUSE
    assert again['summary']['total_anomalies'] == result['summary']['total_anomalies']


def test_guardrail_policies_and_restart_limit(sample):
    data, _ = sample
    config = data['config']
    analyses = [{'pod': f'pod-{i}', 'confidence': 0.9,
                 'recommendations': [{'action': 'restart', 'confidence': 0.9},
                                     {'action': 'scale_down', 'confidence': 0.95}]} for i in range(7)]
    approved, escalated, rejected = quiet(check_actions, {'analyses': analyses}, config)
    # scale_down always needs a human (policy); at most 5 restarts per minute
    assert [a['action'] for a in approved] == ['restart'] * 5
    assert sum('always needs human approval' in e['reason'] for e in escalated) == 7
    assert sum('Rollback rate limit' in e['reason'] for e in escalated) == 2


def test_act_is_reproducible_and_consistent():
    approved = [{'pod': 'p', 'action': 'scale_up', 'confidence': 0.9}] * 3
    a = quiet(execute_actions, approved)['executed_actions']
    b = quiet(execute_actions, approved)['executed_actions']
    assert [x['duration_seconds'] for x in a] == [x['duration_seconds'] for x in b]
    for x in a:
        assert x['after_replicas'] > x['before_replicas']
        assert (x['timestamp_end'] - x['timestamp_start']).total_seconds() == x['duration_seconds']


def test_llm_failure_falls_back_to_rules(sample, monkeypatch):
    data, fused = sample
    monkeypatch.setattr(plan_module, 'HAS_LLM', True)
    monkeypatch.setenv('LLM_API_KEY', 'test')
    monkeypatch.setattr(plan_module, 'generate_llm_analysis', lambda *a, **k: None)
    result = quiet(plan_analysis, fused, data['config'])
    assert result['summary']['analyses_generated'] == 8


def test_undownloaded_case_says_how_to_get_it():
    with pytest.raises(FileNotFoundError, match="download_data.py --case 20231207"):
        quiet(load_data, CONFIG, "20231207")


def test_lemma_conversion(tmp_path):
    # Metric: the last column is the case KPI, not a pod; 1-second samples become 30-second means
    raw = io.BytesIO()
    np.save(raw, np.array({'book_info': {'Pod_Name': ['a', 'b'], 'KPI_Feature': ['Latency'],
                                         'Sequence': np.column_stack([np.arange(60.), np.ones(60), np.full(60, 9.)]),
                                         'time': list(range(1000, 1060))}}, dtype=object))
    entry = download_data.convert_metric(raw.getvalue())['book_info']
    assert entry['Sequence'].shape == (3, 2) and list(entry['time']) == [990, 1020, 1050]

    # Fault label from the README slides
    slide = ('<a:t>Failure time ( time to start affecting SLI) 2024-01-14 07:26:39Z</a:t>'
             '<a:t>Root cause pod (malware infection pod): scenario10-malware-deployment-57db4df9f4-p8h7h </a:t>'
             '<a:t>Root cause: malware infection pod attempts to connect to other pods.</a:t>')
    pptx = io.BytesIO()
    with zipfile.ZipFile(pptx, 'w') as z:
        z.writestr('ppt/slides/slide1.xml', slide)
    label = download_data.fault_labels_from_slides(pptx.getvalue(), '20240115')
    assert label['root_cause_pod'] == ROOT_CAUSE and label['failure_timestamp'] == 1705217199


def test_pipeline_end_to_end(sample, tmp_path):
    data, fused = sample
    result = quiet(plan_analysis, fused, data['config'])
    approved, escalated, rejected = quiet(check_actions, result, data['config'])
    log = quiet(execute_actions, approved, escalated, rejected)
    report = quiet(generate_report, log, result, data['config'], output_dir=str(tmp_path))['report']
    assert (tmp_path / "observability_report.json").exists()
    assert report['evaluation']['root_cause_rank'] == 1
    assert report['evaluation']['root_cause_in_actions']
    assert report['top_pods'][0]['pod'] == ROOT_CAUSE
