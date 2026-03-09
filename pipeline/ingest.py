"""
Stage 1: Ingest

Loads metrics, logs, and KPI data from the LEMMA-RCA dataset.
Validates data integrity and returns structured DataFrames for downstream processing.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
import yaml

logger = logging.getLogger(__name__)


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
        Dictionary with keys: Pod_Name, Sequence, KPI_Feature
        None if file not found
    """
    npy_file = Path(data_path) / f"pod_level_data_{metric_name}.npy"

    if not npy_file.exists():
        logger.warning(f"Metric file not found: {npy_file}")
        return None

    try:
        data_dict = np.load(npy_file, allow_pickle=True).item()

        if label not in data_dict:
            logger.warning(f"Label '{label}' not found in {metric_name}.npy")
            return None

        return data_dict[label]

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
        Dictionary with keys: Node_Name, Sequence, KPI_Feature
        None if file not found
    """
    npy_file = Path(data_path) / filename

    if not npy_file.exists():
        logger.warning(f"Log file not found: {npy_file}")
        return None

    try:
        data_dict = np.load(npy_file, allow_pickle=True).item()

        if label not in data_dict:
            logger.warning(f"Label '{label}' not found in {filename}")
            return None

        return data_dict[label]

    except Exception as e:
        logger.error(f"Error loading {npy_file}: {e}")
        return None


def load_kpi_data(data_path: str) -> Optional[pd.DataFrame]:
    """
    Load KPI data from CSV file.

    Args:
        data_path: Path to data directory

    Returns:
        DataFrame with KPI data
        None if file not found
    """
    kpi_file = Path(data_path) / "kpi.csv"

    if not kpi_file.exists():
        logger.warning(f"KPI file not found: {kpi_file}")
        return None

    try:
        kpi_df = pd.read_csv(kpi_file)
        return kpi_df

    except Exception as e:
        logger.error(f"Error loading {kpi_file}: {e}")
        return None


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

    if 'KPI_Feature' not in metric_data:
        return False, f"{metric_name}: missing 'KPI_Feature' key"

    sequence = metric_data['Sequence']
    if not isinstance(sequence, np.ndarray):
        return False, f"{metric_name}: Sequence is not a numpy array"

    if sequence.ndim != 2:
        return False, f"{metric_name}: Sequence should be 2D (timestamps × pods)"

    # Check for NaN/inf
    if np.isnan(sequence).any():
        logger.warning(f"{metric_name}: contains NaN values")
    if np.isinf(sequence).any():
        logger.warning(f"{metric_name}: contains infinite values")

    return True, ""


def validate_consistency(metrics_data: Dict[str, Dict[str, Any]]) -> tuple[bool, str]:
    """
    Validate consistency across all metrics (pod names, sequence lengths).

    Args:
        metrics_data: Dictionary of all metric data

    Returns:
        (is_valid, error_message)
    """
    if not metrics_data:
        return False, "No metrics loaded"

    # Get reference from first metric
    first_metric = next(iter(metrics_data.values()))
    ref_pods = set(first_metric['Pod_Name'])
    ref_seq_len = first_metric['Sequence'].shape[0]

    for metric_name, metric_data in metrics_data.items():
        current_pods = set(metric_data['Pod_Name'])

        if current_pods != ref_pods:
            missing = ref_pods - current_pods
            extra = current_pods - ref_pods
            msg = f"{metric_name}: pod mismatch. "
            if missing:
                msg += f"Missing: {missing}. "
            if extra:
                msg += f"Extra: {extra}"
            return False, msg

        seq_len = metric_data['Sequence'].shape[0]
        if seq_len != ref_seq_len:
            return False, f"{metric_name}: sequence length mismatch ({seq_len} vs {ref_seq_len})"

    return True, ""


def load_data(config_path: str) -> Dict[str, Any]:
    """
    Stage 1: Ingest

    Load all data from LEMMA-RCA dataset and validate consistency.

    Args:
        config_path: Path to pipeline_config.yaml

    Returns:
        Dictionary containing:
        - metrics: Dict[metric_name, DataFrame]
        - logs_golden: DataFrame with golden signal logs
        - logs_frequency: DataFrame with frequency logs
        - kpi: DataFrame with KPI data
        - config: Configuration dictionary
        - validation_summary: Dict with validation results
    """
    print("\n" + "="*70)
    print("STAGE 1: INGEST")
    print("="*70)

    # Load configuration
    print("\nLoading configuration...")
    config = load_config(config_path)
    data_path = config['data_path']
    label = config['label']
    metrics_to_load = config.get('metrics', [])

    print(f"  Case: {config['case']}")
    print(f"  Service: {label}")
    print(f"  Data path: {data_path}")

    # Load metric data
    print(f"\nLoading metrics ({len(metrics_to_load)} files)...")
    metrics_data = {}
    loaded_metrics = 0

    for metric_name in metrics_to_load:
        metric_data = load_metric_data(data_path, metric_name, label)
        if metric_data is not None:
            is_valid, error = validate_metric_data(metric_data, metric_name)
            if is_valid:
                metrics_data[metric_name] = metric_data
                print(f"  ✓ {metric_name}: shape {metric_data['Sequence'].shape}")
                loaded_metrics += 1
            else:
                print(f"  ✗ {metric_name}: {error}")
        else:
            print(f"  ✗ {metric_name}: file not found")

    if not metrics_data:
        raise ValueError("No metrics loaded successfully")

    # Load log data
    print(f"\nLoading logs...")
    logs_golden = load_log_data(data_path, "pod_level_log_golden_signal.npy", label)
    logs_frequency = load_log_data(data_path, "pod_level_log_frequency.npy", label)

    if logs_golden is not None:
        is_valid, error = validate_metric_data(logs_golden, "golden_signal")
        if is_valid:
            print(f"  ✓ Golden signal: shape {logs_golden['Sequence'].shape}")
        else:
            print(f"  ✗ Golden signal: {error}")
    else:
        print(f"  ✗ Golden signal: file not found")

    if logs_frequency is not None:
        is_valid, error = validate_metric_data(logs_frequency, "frequency")
        if is_valid:
            print(f"  ✓ Frequency logs: shape {logs_frequency['Sequence'].shape}")
        else:
            print(f"  ✗ Frequency logs: {error}")
    else:
        print(f"  ✗ Frequency logs: file not found")

    # Load KPI data
    print(f"\nLoading KPI...")
    kpi_df = load_kpi_data(data_path)
    if kpi_df is not None:
        print(f"  ✓ KPI: {kpi_df.shape[0]} rows, {kpi_df.shape[1]} columns")
    else:
        print(f"  ✗ KPI: file not found")
        kpi_df = pd.DataFrame()

    # Validate consistency
    print(f"\nValidating consistency...")
    is_consistent, consistency_error = validate_consistency(metrics_data)
    if is_consistent:
        print(f"  ✓ All metrics have consistent pod names and sequence lengths")
    else:
        print(f"  ✗ Consistency check failed: {consistency_error}")

    # Convert to DataFrames
    print(f"\nConverting to DataFrames...")
    metrics_dfs = {}

    for metric_name, metric_data in metrics_data.items():
        # Create DataFrame with pod names as columns
        df = pd.DataFrame(
            metric_data['Sequence'],
            columns=metric_data['Pod_Name']
        )
        metrics_dfs[metric_name] = df
        print(f"  ✓ {metric_name}: {df.shape[0]} timestamps × {df.shape[1]} pods")

    # Convert log data to DataFrames
    if logs_golden is not None:
        logs_golden_df = pd.DataFrame(
            logs_golden['Sequence'],
            columns=logs_golden.get('Node_Name', logs_golden.get('Pod_Name', []))
        )
    else:
        logs_golden_df = pd.DataFrame()

    if logs_frequency is not None:
        logs_frequency_df = pd.DataFrame(
            logs_frequency['Sequence'],
            columns=logs_frequency.get('Node_Name', logs_frequency.get('Pod_Name', []))
        )
    else:
        logs_frequency_df = pd.DataFrame()

    # Validation summary
    validation_summary = {
        'metrics_loaded': len(metrics_dfs),
        'metrics_failed': len(metrics_to_load) - len(metrics_dfs),
        'total_pods': max(
            [df.shape[1] for df in metrics_dfs.values()] +
            [logs_golden_df.shape[1] if not logs_golden_df.empty else 0] +
            [logs_frequency_df.shape[1] if not logs_frequency_df.empty else 0]
        ),
        'total_timestamps': next(iter(metrics_dfs.values())).shape[0],
        'consistency_valid': is_consistent,
        'logs_golden_available': not logs_golden_df.empty,
        'logs_frequency_available': not logs_frequency_df.empty,
        'kpi_available': not kpi_df.empty,
    }

    print(f"\n{'─'*70}")
    print("INGESTION SUMMARY")
    print(f"{'─'*70}")
    print(f"Metrics loaded:     {validation_summary['metrics_loaded']}")
    print(f"Pods:               {validation_summary['total_pods']}")
    print(f"Timestamps:         {validation_summary['total_timestamps']}")
    print(f"Consistency:        {'✓ Valid' if validation_summary['consistency_valid'] else '✗ Invalid'}")
    print(f"Golden logs:        {'✓ Available' if validation_summary['logs_golden_available'] else '✗ Not found'}")
    print(f"Frequency logs:     {'✓ Available' if validation_summary['logs_frequency_available'] else '✗ Not found'}")
    print(f"KPI data:           {'✓ Available' if validation_summary['kpi_available'] else '✗ Not found'}")

    return {
        'metrics': metrics_dfs,
        'logs_golden': logs_golden_df,
        'logs_frequency': logs_frequency_df,
        'kpi': kpi_df,
        'config': config,
        'validation_summary': validation_summary,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    data_dict = load_data("config/pipeline_config.yaml")
    print("\nData loaded successfully!")
