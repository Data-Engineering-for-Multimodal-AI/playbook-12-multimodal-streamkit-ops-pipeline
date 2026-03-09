"""
Stage 2: Fuse

Aligns metrics and logs by pod name and time window into unified feature space.
Creates fused DataFrame where each row represents (pod, time_window) with all
available metric and log features.
"""

import logging
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def get_common_pods(data_dict: Dict[str, Any]) -> set:
    """
    Find pod names that appear in all modalities.

    Args:
        data_dict: Data dictionary from ingest stage

    Returns:
        Set of common pod names
    """
    pod_sets = []

    # Collect pods from metrics
    for metric_name, metric_df in data_dict['metrics'].items():
        pod_sets.append(set(metric_df.columns))

    # Collect pods from logs
    if not data_dict['logs_golden'].empty:
        pod_sets.append(set(data_dict['logs_golden'].columns))

    if not data_dict['logs_frequency'].empty:
        pod_sets.append(set(data_dict['logs_frequency'].columns))

    # Find intersection
    if not pod_sets:
        return set()

    common_pods = pod_sets[0]
    for pod_set in pod_sets[1:]:
        common_pods = common_pods.intersection(pod_set)

    return common_pods


def create_time_windows(
    num_timestamps: int,
    window_size: int = 300,
    stride: Optional[int] = None,
) -> list[tuple[int, int]]:
    """
    Create time windows for aggregation.

    Args:
        num_timestamps: Total number of timestamps
        window_size: Size of each window (in timestamps)
        stride: Stride between windows (default: window_size)

    Returns:
        List of (start_idx, end_idx) tuples
    """
    if stride is None:
        stride = window_size

    windows = []
    start = 0

    while start + window_size <= num_timestamps:
        end = start + window_size
        windows.append((start, end))
        start += stride

    # Add final partial window if it exists and is at least half window size
    if start < num_timestamps and num_timestamps - start >= window_size // 2:
        windows.append((start, num_timestamps))

    return windows


def aggregate_window(
    data: np.ndarray,
    aggregations: list[str] = None,
) -> Dict[str, float]:
    """
    Compute aggregation statistics for a time window.

    Args:
        data: 1D array of values
        aggregations: List of aggregation functions to compute

    Returns:
        Dictionary of aggregation results
    """
    if aggregations is None:
        aggregations = ['mean', 'std', 'min', 'max', 'p50', 'p95', 'p99']

    # Remove NaN/inf values
    data_clean = data[np.isfinite(data)]

    if len(data_clean) == 0:
        return {agg: np.nan for agg in aggregations}

    results = {}

    for agg in aggregations:
        if agg == 'mean':
            results[agg] = np.mean(data_clean)
        elif agg == 'std':
            results[agg] = np.std(data_clean)
        elif agg == 'min':
            results[agg] = np.min(data_clean)
        elif agg == 'max':
            results[agg] = np.max(data_clean)
        elif agg == 'p50':
            results[agg] = np.percentile(data_clean, 50)
        elif agg == 'p95':
            results[agg] = np.percentile(data_clean, 95)
        elif agg == 'p99':
            results[agg] = np.percentile(data_clean, 99)

    return results


def fuse_modalities(
    data_dict: Dict[str, Any],
    window_size: int = 300,
    aggregations: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Stage 2: Fuse

    Align all modalities (metrics, logs) by pod and time window.

    Args:
        data_dict: Data dictionary from ingest stage
        window_size: Size of time window (in timestamps)
        aggregations: List of aggregation functions (default: mean, std, min, max, p50, p95, p99)

    Returns:
        Fused DataFrame with columns: pod, window_start, window_end, {modality}_{feature}_{agg}
    """
    print("\n" + "="*70)
    print("STAGE 2: FUSE")
    print("="*70)

    if aggregations is None:
        aggregations = ['mean', 'std', 'min', 'max', 'p50', 'p95', 'p99']

    # Get common pods
    common_pods = get_common_pods(data_dict)
    print(f"\nCommon pods across all modalities: {len(common_pods)}")
    if len(common_pods) == 0:
        print("  Warning: No common pods found. Creating union of all pods.")
        common_pods = set()
        for metric_df in data_dict['metrics'].values():
            common_pods.update(metric_df.columns)

    # Get number of timestamps
    first_metric = next(iter(data_dict['metrics'].values()))
    num_timestamps = first_metric.shape[0]
    print(f"Total timestamps: {num_timestamps}")

    # Create time windows
    windows = create_time_windows(num_timestamps, window_size)
    print(f"Time windows created: {len(windows)} windows of size {window_size}")

    # Build fused data
    fused_rows = []

    for pod_name in sorted(common_pods):
        print(f"\nProcessing pod: {pod_name}")

        for window_idx, (start_idx, end_idx) in enumerate(windows):
            row = {
                'pod': pod_name,
                'window_start': start_idx,
                'window_end': end_idx,
                'window_id': f"{pod_name}_{window_idx}",
            }

            # Add metric features
            for metric_name, metric_df in data_dict['metrics'].items():
                if pod_name in metric_df.columns:
                    window_data = metric_df.loc[start_idx:end_idx, pod_name].values

                    agg_results = aggregate_window(window_data, aggregations)
                    for agg_name, agg_value in agg_results.items():
                        col_name = f"metric_{metric_name}_{agg_name}"
                        row[col_name] = agg_value

            # Add log features
            if not data_dict['logs_golden'].empty and pod_name in data_dict['logs_golden'].columns:
                window_data = data_dict['logs_golden'].loc[start_idx:end_idx, pod_name].values

                agg_results = aggregate_window(window_data, aggregations)
                for agg_name, agg_value in agg_results.items():
                    col_name = f"log_golden_{agg_name}"
                    row[col_name] = agg_value

            if not data_dict['logs_frequency'].empty and pod_name in data_dict['logs_frequency'].columns:
                window_data = data_dict['logs_frequency'].loc[start_idx:end_idx, pod_name].values

                agg_results = aggregate_window(window_data, aggregations)
                for agg_name, agg_value in agg_results.items():
                    col_name = f"log_frequency_{agg_name}"
                    row[col_name] = agg_value

            fused_rows.append(row)

        if len(common_pods) <= 5:
            print(f"  ✓ {pod_name}: {len(windows)} windows")

    # Create DataFrame
    fused_df = pd.DataFrame(fused_rows)

    print(f"\n{'─'*70}")
    print("FUSION SUMMARY")
    print(f"{'─'*70}")
    print(f"Pods fused:         {len(common_pods)}")
    print(f"Windows per pod:    {len(windows)}")
    print(f"Total rows:         {len(fused_df)}")
    print(f"Total columns:      {fused_df.shape[1]}")
    print(f"Feature groups:")
    print(f"  - Metrics: {len([c for c in fused_df.columns if c.startswith('metric_')])}")
    print(f"  - Golden logs: {len([c for c in fused_df.columns if c.startswith('log_golden_')])}")
    print(f"  - Frequency logs: {len([c for c in fused_df.columns if c.startswith('log_frequency_')])}")

    return fused_df


if __name__ == "__main__":
    import logging
    from ingest import load_data

    logging.basicConfig(level=logging.INFO)

    data_dict = load_data("config/pipeline_config.yaml")
    fused_df = fuse_modalities(data_dict)

    print("\n\nFirst few rows of fused data:")
    print(fused_df.head())
