"""
Stage 1: Ingest

Loads metrics, logs, KPI and fault labels from a case folder: the bundled synthetic sample
(data/20240115/) or a LEMMA-RCA case converted by download_data.py (data/lemma-rca/{case}/).
Validates data integrity and returns time-indexed DataFrames for downstream processing.

Every series is indexed by time in seconds. LEMMA-RCA cases carry unix timestamps; the synthetic
sample has none, so its steps are numbered 0, 1, 2, ... and treated as seconds.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
import yaml

from pipeline.safe_npy import load_npy

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent


def load_config(config_path: str) -> Dict[str, Any]:
    """
    Load pipeline configuration from YAML file.

    Args:
        config_path: Path to pipeline_config.yaml

    Returns:
        Configuration dictionary
    """
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    return config


def resolve_data_path(config: Dict[str, Any], case: Optional[str] = None) -> Dict[str, Any]:
    """Pick the folder: without a case, the bundled sample; with a case, the downloaded LEMMA-RCA case.

    Sets config['case'], config['data_path'] and config['data_source'] ('lemma-rca' or 'sample').
    """
    sample = dict(data_path=str(ROOT / config['data_path']), data_source='sample')
    if case is None:
        config.update(**sample)
        return config
    case = str(case)
    downloaded = ROOT / "data" / "lemma-rca" / case
    if (downloaded / "fault_labels.json").exists():
        config.update(case=case, data_path=str(downloaded), data_source='lemma-rca')
    elif case == str(config['case']):
        print(f"  Case {case} isn't downloaded (python download_data.py --case {case}); using the bundled sample")
        config.update(**sample)
    else:
        raise FileNotFoundError(f"No data for case {case}. Run: python download_data.py --case {case}")
    return config


def _entry(npy_file: Path, label: str) -> Optional[Dict[str, Any]]:
    data = load_npy(npy_file)
    if label in data:
        return data[label]
    if 'Sequence' in data:
        return data
    logger.warning(f"Label '{label}' not found in {npy_file.name}")
    return None


def load_metric_data(
    data_path: str,
    metric_name: str,
    label: str,
) -> Optional[Dict[str, Any]]:
    """
    Load a single metric's .npy file.

    Args:
        data_path: Path to data directory
        metric_name: Name of metric (e.g., 'cpu_usage')
        label: Label/service name (e.g., 'book_info')

    Returns:
        Dictionary with keys: Pod_Name, Sequence, KPI_Feature (and time for LEMMA-RCA cases)
        None if file not found
    """
    npy_file = Path(data_path) / f"pod_level_data_{metric_name}.npy"

    if not npy_file.exists():
        logger.warning(f"Metric file not found: {npy_file}")
        return None

    try:
        return _entry(npy_file, label)
    except Exception as e:
        logger.error(f"Error loading {npy_file}: {e}")
        return None


def load_log_data(
    data_path: str,
    filename: str,
    label: str,
) -> Optional[Dict[str, Any]]:
    """
    Load log data (.npy file).

    Args:
        data_path: Path to data directory
        filename: Filename (e.g., 'pod_level_log_golden_signal.npy')
        label: Label/service name

    Returns:
        Dictionary with keys: Node_Name, Sequence, KPI_Feature (and time)
        None if file not found
    """
    npy_file = Path(data_path) / filename

    if not npy_file.exists():
        logger.warning(f"Log file not found: {npy_file}")
        return None

    try:
        return _entry(npy_file, label)
    except Exception as e:
        logger.error(f"Error loading {npy_file}: {e}")
        return None


def load_kpi_data(data_path: str) -> Optional[pd.DataFrame]:
    """
    Load KPI data from CSV file.

    Args:
        data_path: Path to data directory

    Returns:
        DataFrame indexed by time with at least a 'kpi' column (higher is better)
        None if file not found
    """
    kpi_file = Path(data_path) / "kpi.csv"

    if not kpi_file.exists():
        logger.warning(f"KPI file not found: {kpi_file}")
        return None

    try:
        return pd.read_csv(kpi_file).set_index('timestamp')

    except Exception as e:
        logger.error(f"Error loading {kpi_file}: {e}")
        return None


def load_fault_labels(data_path: str) -> Dict[str, Any]:
    """Root-cause pod and failure time, in one shape for both data sources.

    The synthetic sample's label names a real-world time, but the sample has no clock, so only its
    root-cause pod can be scored.
    """
    label_file = Path(data_path) / "fault_labels.json"
    if not label_file.exists():
        return {}
    with open(label_file) as f:
        labels = json.load(f)
    if 'root_cause_pod' in labels:
        return labels
    injections = [i for day in labels.values() for i in day]
    if not injections:
        return {}
    first = injections[0]
    return {'root_cause_pod': first.get('inject_pod'), 'fault_type': first.get('inject_type'),
            'failure_timestamp': None,
            'note': 'the sample has no clock: its label time cannot be compared with the data'}


def validate_metric_data(
    metric_data: Dict[str, Any],
    metric_name: str,
) -> tuple[bool, str]:
    """
    Validate a metric data dictionary.

    Args:
        metric_data: Metric data dictionary
        metric_name: Name of metric for logging

    Returns:
        (is_valid, error_message)
    """
    if not isinstance(metric_data, dict):
        return False, f"{metric_name}: data is not a dictionary"

    # LEMMA-RCA logs use 'Node_Name' instead of 'Pod_Name'
    if 'Pod_Name' not in metric_data and 'Node_Name' not in metric_data:
        return False, f"{metric_name}: missing 'Pod_Name' or 'Node_Name' key"

    # Normalize: copy Node_Name to Pod_Name if needed
    if 'Pod_Name' not in metric_data and 'Node_Name' in metric_data:
        metric_data['Pod_Name'] = metric_data['Node_Name']

    if 'Sequence' not in metric_data:
        return False, f"{metric_name}: missing 'Sequence' key"

    sequence = metric_data['Sequence']
    if not isinstance(sequence, np.ndarray):
        return False, f"{metric_name}: Sequence is not a numpy array"

    if sequence.ndim != 2:
        return False, f"{metric_name}: Sequence should be 2D (timestamps × pods)"

    if sequence.shape[1] != len(metric_data['Pod_Name']):
        return False, f"{metric_name}: {sequence.shape[1]} columns for {len(metric_data['Pod_Name'])} pods"

    if 'time' in metric_data and len(metric_data['time']) != sequence.shape[0]:
        return False, f"{metric_name}: {len(metric_data['time'])} timestamps for {sequence.shape[0]} rows"

    # Check for NaN/inf
    if np.isnan(sequence).any():
        logger.warning(f"{metric_name}: contains NaN values")
    if np.isinf(sequence).any():
        logger.warning(f"{metric_name}: contains infinite values")

    return True, ""


def to_frame(entry: Dict[str, Any]) -> pd.DataFrame:
    """Time-indexed DataFrame (rows: seconds, columns: pods)"""
    sequence = np.asarray(entry['Sequence'], dtype=np.float64)
    time = np.asarray(entry['time'], dtype=np.int64) if 'time' in entry else np.arange(sequence.shape[0])
    return pd.DataFrame(sequence, index=pd.Index(time, name='time'), columns=list(entry['Pod_Name']))


def validate_consistency(metrics: Dict[str, pd.DataFrame]) -> tuple[bool, str]:
    """
    Validate consistency across all metrics (pod names, time span).

    Real clusters don't report every metric for every pod (LEMMA-RCA has storage IOPS for 6 of
    257 pods), so differences are reported, not treated as errors.

    Returns:
        (all_identical, description)
    """
    if not metrics:
        return False, "No metrics loaded"

    pod_sets = {name: set(df.columns) for name, df in metrics.items()}
    spans = {name: (int(df.index.min()), int(df.index.max())) for name, df in metrics.items()}
    all_pods = set().union(*pod_sets.values())
    partial = {name: len(p) for name, p in pod_sets.items() if p != all_pods}
    if not partial and len(set(spans.values())) == 1:
        return True, "All metrics have consistent pod names and time spans"
    notes = []
    if partial:
        notes.append(f"metrics covering fewer of the {len(all_pods)} pods: " +
                     ", ".join(f"{n} ({c})" for n, c in partial.items()))
    if len(set(spans.values())) > 1:
        notes.append("time spans differ between metrics (aligned by time in the fuse stage)")
    return False, "; ".join(notes)


def load_data(config_path: str, case: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage 1: Ingest

    Load all data for a case and validate it.

    Args:
        config_path: Path to pipeline_config.yaml
        case: Case ID (default: the config's case; a downloaded LEMMA-RCA case wins over the sample)

    Returns:
        Dictionary containing:
        - metrics: Dict[metric_name, DataFrame]   (index: time, columns: pods)
        - logs_golden: DataFrame with golden signal logs
        - logs_frequency: DataFrame with frequency logs
        - kpi: DataFrame with KPI data (index: time)
        - fault_labels: root-cause pod and failure time
        - config: Configuration dictionary
        - validation_summary: Dict with validation results
    """
    print("\n" + "="*70)
    print("STAGE 1: INGEST")
    print("="*70)

    # Load configuration
    print("\nLoading configuration...")
    config = resolve_data_path(load_config(config_path), case)
    data_path = config['data_path']
    label = config['label']
    metrics_to_load = config.get('metrics', [])

    print(f"  Case: {config['case']}")
    print(f"  Source: {'LEMMA-RCA (downloaded)' if config['data_source'] == 'lemma-rca' else 'synthetic sample (bundled)'}")
    print(f"  Service: {label}")
    print(f"  Data path: {Path(data_path).relative_to(ROOT) if Path(data_path).is_relative_to(ROOT) else data_path}")

    # Load metric data
    print(f"\nLoading metrics ({len(metrics_to_load)} files)...")
    metrics_dfs = {}

    for metric_name in metrics_to_load:
        metric_data = load_metric_data(data_path, metric_name, label)
        if metric_data is not None:
            is_valid, error = validate_metric_data(metric_data, metric_name)
            if is_valid:
                metrics_dfs[metric_name] = to_frame(metric_data)
                print(f"  ✓ {metric_name}: shape {metric_data['Sequence'].shape}")
            else:
                print(f"  ✗ {metric_name}: {error}")
        else:
            print(f"  ✗ {metric_name}: file not found")

    if not metrics_dfs:
        raise ValueError("No metrics loaded successfully")

    # Load log data
    print(f"\nLoading logs...")
    logs = {}
    for key, filename, title in [('golden', 'pod_level_log_golden_signal.npy', 'Golden signal'),
                                 ('frequency', 'pod_level_log_frequency.npy', 'Frequency logs')]:
        entry = load_log_data(data_path, filename, label)
        logs[key] = pd.DataFrame()
        if entry is None:
            print(f"  ✗ {title}: file not found")
            continue
        is_valid, error = validate_metric_data(entry, key)
        if is_valid:
            logs[key] = to_frame(entry)
            print(f"  ✓ {title}: shape {entry['Sequence'].shape}")
        else:
            print(f"  ✗ {title}: {error}")

    # Load KPI data
    print(f"\nLoading KPI...")
    kpi_df = load_kpi_data(data_path)
    if kpi_df is not None:
        print(f"  ✓ KPI: {kpi_df.shape[0]} rows, {kpi_df.shape[1] + 1} columns")
    else:
        print(f"  ✗ KPI: file not found")
        kpi_df = pd.DataFrame()

    fault_labels = load_fault_labels(data_path)
    if fault_labels.get('root_cause_pod'):
        print(f"  ✓ Fault label: root cause {fault_labels['root_cause_pod']}")

    # Validate consistency
    print(f"\nValidating consistency...")
    is_consistent, consistency_note = validate_consistency(metrics_dfs)
    print(f"  {'✓' if is_consistent else '⚠'} {consistency_note}")

    first = next(iter(metrics_dfs.values()))
    validation_summary = {
        'metrics_loaded': len(metrics_dfs),
        'metrics_failed': len(metrics_to_load) - len(metrics_dfs),
        'total_pods': len(set().union(*(df.columns for df in metrics_dfs.values()))),
        'total_timestamps': first.shape[0],
        'consistency_valid': is_consistent,
        'consistency_note': consistency_note,
        'logs_golden_available': not logs['golden'].empty,
        'logs_frequency_available': not logs['frequency'].empty,
        'kpi_available': not kpi_df.empty,
        'fault_label_available': bool(fault_labels.get('root_cause_pod')),
    }

    print(f"\n{'─'*70}")
    print("INGESTION SUMMARY")
    print(f"{'─'*70}")
    print(f"Metrics loaded:     {validation_summary['metrics_loaded']}")
    print(f"Pods:               {validation_summary['total_pods']}")
    print(f"Timestamps:         {validation_summary['total_timestamps']}")
    print(f"Consistency:        {'✓ Valid' if is_consistent else '⚠ See note above'}")
    print(f"Golden logs:        {'✓ Available' if validation_summary['logs_golden_available'] else '✗ Not found'}")
    print(f"Frequency logs:     {'✓ Available' if validation_summary['logs_frequency_available'] else '✗ Not found'}")
    print(f"KPI data:           {'✓ Available' if validation_summary['kpi_available'] else '✗ Not found'}")
    print(f"Fault label:        {'✓ Available' if validation_summary['fault_label_available'] else '✗ Not found'}")

    return {
        'metrics': metrics_dfs,
        'logs_golden': logs['golden'],
        'logs_frequency': logs['frequency'],
        'kpi': kpi_df,
        'fault_labels': fault_labels,
        'config': config,
        'validation_summary': validation_summary,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    data_dict = load_data(str(ROOT / "config" / "pipeline_config.yaml"))
    print("\nData loaded successfully!")
