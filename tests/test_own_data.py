"""Checks for the "Use your own data" adapter (scripts/own_cluster.py). Builds folders in tmp_path."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from own_cluster import check, convert  # noqa: E402

START = 1772409600   # 2026-03-02T00:00:00Z
PODS = ["web-1", "pay-1", "db-0"]


def make_folder(path, hours=2, step=60, **changes):
    path.mkdir(parents=True, exist_ok=True)
    times = range(START, START + int(hours * 3600), step)
    files = {
        "metrics.csv": "timestamp,pod,metric,value\n" + "".join(
            f"{t},{p},cpu_usage,{0.3 + (0.5 if p == 'pay-1' and t > START + 3600 else 0)}\n"
            f"{t},{p},memory_usage,512\n" for t in times for p in PODS),
        "kpi.csv": "timestamp,error_rate\n" + "".join(
            f"{t},{0.05 if t > START + 3600 else 0.001}\n" for t in times),
        "logs.csv": "timestamp,pod,golden_signal,frequency\n" + "".join(f"{t},web-1,0,10\n" for t in times),
        "fault_label.json": json.dumps({"root_cause_pod": "pay-1", "failure_time": "2026-03-02T01:00:00Z"}),
    }
    files.update(changes)
    for name, content in files.items():
        if content is None:
            continue
        (path / name).write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return path


def test_good_folder_converts_to_the_pipelines_format(tmp_path):
    data, problems = check(make_folder(tmp_path / "in"))
    assert problems == []
    assert data["pods"] == sorted(PODS) and data["sli"] == "error_rate"
    out = tmp_path / "own-in"
    convert(data, out)
    from pipeline.safe_npy import load_npy
    cpu = load_npy(out / "pod_level_data_cpu_usage.npy")["book_info"]
    assert cpu["Sequence"].shape == (120, 3) and sorted(cpu["Pod_Name"]) == sorted(PODS)   # 2 h of 1-minute samples
    assert (cpu["time"] % 30 == 0).all()
    label = json.loads((out / "fault_labels.json").read_text())
    assert label["root_cause_pod"] == "pay-1" and label["kpi_rule"] == "error_rate"
    assert label["failure_time_utc"] == "2026-03-02T01:00:00Z"
    assert (out / "pod_level_log_golden_signal.npy").exists()


def test_latency_kpi_and_no_optional_files(tmp_path):
    kpi = "timestamp,latency_ms\n" + "".join(f"{t},{120}\n" for t in range(START, START + 7200, 60))
    data, problems = check(make_folder(tmp_path, **{"kpi.csv": kpi, "logs.csv": None,
                                                                   "fault_label.json": None}))
    assert problems == [] and data["sli"] == "latency_ms" and data["label"] == {}


@pytest.mark.parametrize("changes,expected", [
    ({"metrics.csv": None}, "metrics.csv: missing"),
    ({"kpi.csv": "timestamp,errors\n1772409600,1\n"}, "needs an error_rate column"),
    ({"metrics.csv": "timestamp,pod,value\n"}, "missing column(s) metric"),
    ({"metrics.csv": "timestamp,pod,metric,value\n1772409600,web-1,cpu_seconds_total,1\n"},
     "metric 'cpu_seconds_total' is not one the pipeline reads"),
    ({"metrics.csv": "timestamp,pod,metric,value\n2026-03-02 00:00:00,web-1,cpu_usage,1\n"}, "has no time zone"),
    ({"metrics.csv": "timestamp,pod,metric,value\n1772409600000,web-1,cpu_usage,1\n"}, "is not unix seconds"),
    ({"metrics.csv": "timestamp,pod,metric,value\n1772409600,web-1,cpu_usage,n/a\n"}, "value 'n/a' is not a number"),
    ({"metrics.csv": "timestamp,pod,metric,value\n1772409600,web-1,cpu_usage,1\n1772409600,web-1,cpu_usage,2\n"},
     "second sample for web-1 cpu_usage"),
    ({"kpi.csv": "timestamp,error_rate\n1772409600,5\n"}, "outside 0 to 1"),
    ({"kpi.csv": "timestamp,latency_ms\n1772409600,0\n"}, "latency_ms 0 is 0 or less"),
    ({"kpi.csv": "timestamp,error_rate\n1700000000,0.1\n"}, "don't overlap metrics.csv"),
    ({"logs.csv": "timestamp,pod,golden_signal,frequency\n1772409600,caf\xe9,1,2\n".encode("latin-1")}, "not UTF-8"),
    ({"fault_label.json": json.dumps({"root_cause_pod": "nope"})}, "root_cause_pod 'nope' has no rows"),
    ({"fault_label.json": "{not json"}, "fault_label.json: can't read it"),
    ({"metrics.csv": b"version https://git-lfs.github.com/spec/v1\n"}, "Git LFS pointer"),
])
def test_problems_are_reported(tmp_path, changes, expected):
    _, problems = check(make_folder(tmp_path, **changes))
    assert any(expected in p for p in problems), problems


def test_too_short(tmp_path):
    _, problems = check(make_folder(tmp_path, hours=0.5))
    assert any("needs at least 60" in p for p in problems), problems


def test_many_bad_rows_are_summarized(tmp_path):
    rows = "".join(f"x{i},web-1,cpu_usage,1\n" for i in range(20))
    _, problems = check(make_folder(tmp_path, **{"metrics.csv": "timestamp,pod,metric,value\n" + rows}))
    assert sum("doesn't parse" in p for p in problems) == 5
    assert "metrics.csv: 15 more problem(s) like the ones above" in problems


def test_check_only_writes_nothing_on_problems(tmp_path):
    folder = make_folder(tmp_path / "bad", **{"kpi.csv": None})
    run = subprocess.run([sys.executable, str(ROOT / "scripts" / "own_cluster.py"), "--dir", str(folder)],
                         capture_output=True, text=True, cwd=ROOT)
    assert run.returncode == 1 and "nothing was written" in run.stdout
    assert not (ROOT / "data" / "lemma-rca" / "own-bad").exists()
