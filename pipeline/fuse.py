"""
Stage 2: Fuse

Aligns metrics and logs by pod name and time window into unified feature space.
Creates fused DataFrame where each row represents (pod, time_window) with all
available metric and log features.

Windows are cut on the time axis (seconds), so modalities sampled at different rates or over
different spans line up. Each sample belongs to exactly one window.
"""

import logging
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_AGGREGATIONS = ['mean', 'std', 'min', 'max', 'p50', 'p95', 'p99']
ID_COLUMNS = ['pod', 'window_start', 'window_end', 'window_id']


def get_common_pods(data_dict: Dict[str, Any]) -> set:
    """
    Find pod names that appear in all modalities.

    Args:
        data_dict: Data dictionary from ingest stage

    Returns:
        Set of common pod names
    """
    pod_sets = [set(df.columns) for df in data_dict['metrics'].values()]
    for key in ('logs_golden', 'logs_frequency'):
        if not data_dict[key].empty:
            pod_sets.append(set(data_dict[key].columns))
    return set.intersection(*pod_sets) if pod_sets else set()


def get_all_pods(data_dict: Dict[str, Any]) -> set:
    """Pods with at least one metric (features a pod doesn't have stay empty)"""
    return set().union(*(df.columns for df in data_dict['metrics'].values()))


def create_time_windows(
    start: int,
    end: int,
    window_size: int = 300,
    stride: Optional[int] = None,
) -> list[tuple[int, int]]:
    """
    Create time windows [start, end) for aggregation.

    Args:
        start: First timestamp (seconds)
        end: Last timestamp (seconds, inclusive)
        window_size: Size of each window (in seconds)
        stride: Stride between windows (default: window_size)

    Returns:
        List of (window_start, window_end) tuples; window_end is exclusive
    """
    if stride is None:
        stride = window_size

    windows = []
    t = start
    while t + window_size <= end + 1:
        windows.append((t, t + window_size))
        t += stride

    # Add final partial window if it exists and is at least half window size
    if t <= end and end + 1 - t >= window_size // 2:
        windows.append((t, end + 1))

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
        aggregations = DEFAULT_AGGREGATIONS
    data_clean = np.asarray(data, dtype=float)
    data_clean = data_clean[np.isfinite(data_clean)]
    if len(data_clean) == 0:
        return {agg: np.nan for agg in aggregations}
    functions = {'mean': np.mean, 'std': np.std, 'min': np.min, 'max': np.max,
                 'p50': lambda x: np.percentile(x, 50), 'p95': lambda x: np.percentile(x, 95),
                 'p99': lambda x: np.percentile(x, 99)}
    return {agg: float(functions[agg](data_clean)) for agg in aggregations}


def aggregate_frame(df: pd.DataFrame, windows: list[tuple[int, int]], prefix: str,
                    aggregations: list[str]) -> pd.DataFrame:
    """Aggregate a (time × pods) frame per window: rows (window_start, pod), columns prefix_agg"""
    starts = np.array([w[0] for w in windows])
    ends = np.array([w[1] for w in windows])
    times = df.index.to_numpy()
    position = np.searchsorted(starts, times, side='right') - 1
    inside = (position >= 0) & (times < ends[np.clip(position, 0, None)])
    df = df[inside].replace([np.inf, -np.inf], np.nan)
    group = pd.Index(starts[position[inside]], name='window_start')
    grouped = df.groupby(group)

    parts = {}
    for agg in aggregations:
        if agg in ('mean', 'std', 'min', 'max'):
            values = getattr(grouped, agg)(ddof=0) if agg == 'std' else getattr(grouped, agg)()
        else:
            values = grouped.quantile(int(agg[1:]) / 100)
        parts[f"{prefix}_{agg}"] = values.stack(future_stack=True)
    out = pd.DataFrame(parts)
    out.index.names = ['window_start', 'pod']
    return out


def window_kpi(kpi: pd.DataFrame, windows: list[tuple[int, int]]) -> pd.DataFrame:
    """KPI per window (mean of each KPI column), indexed by window_start"""
    if kpi is None or kpi.empty:
        return pd.DataFrame()
    starts = np.array([w[0] for w in windows])
    ends = np.array([w[1] for w in windows])
    times = kpi.index.to_numpy()
    position = np.searchsorted(starts, times, side='right') - 1
    inside = (position >= 0) & (times < ends[np.clip(position, 0, None)])
    numeric = kpi[inside].select_dtypes('number')
    return numeric.groupby(pd.Index(starts[position[inside]], name='window_start')).mean()


def fuse_modalities(
    data_dict: Dict[str, Any],
    window_size: Optional[int] = None,
    aggregations: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Stage 2: Fuse

    Align all modalities (metrics, logs) by pod and time window.

    Args:
        data_dict: Data dictionary from ingest stage
        window_size: Size of time window in seconds (default: config feature_engineering.window_size)
        aggregations: List of aggregation functions (default: config feature_engineering.aggregation)

    Returns:
        Fused DataFrame with columns: pod, window_start, window_end, window_id, {modality}_{feature}_{agg}.
        fused_df.attrs carries the KPI per window, the fault labels and the window size.
    """
    print("\n" + "="*70)
    print("STAGE 2: FUSE")
    print("="*70)

    features = data_dict.get('config', {}).get('feature_engineering', {})
    window_size = int(window_size or features.get('window_size', 300))
    aggregations = aggregations or features.get('aggregation') or DEFAULT_AGGREGATIONS

    common_pods = get_common_pods(data_dict)
    pods = get_all_pods(data_dict)
    print(f"\nCommon pods across all modalities: {len(common_pods)}")
    print(f"Pods with metrics: {len(pods)}")

    # One time grid for every modality
    frames = list(data_dict['metrics'].values()) + [data_dict[k] for k in ('logs_golden', 'logs_frequency')
                                                    if not data_dict[k].empty]
    start = int(min(df.index.min() for df in frames))
    end = int(max(df.index.max() for df in data_dict['metrics'].values()))
    windows = create_time_windows(start, end, window_size)
    print(f"Time span: {end - start + 1} seconds")
    print(f"Time windows created: {len(windows)} windows of {window_size} s")

    parts = [aggregate_frame(df, windows, f"metric_{name}", aggregations)
             for name, df in data_dict['metrics'].items()]
    for key, prefix in (('logs_golden', 'log_golden'), ('logs_frequency', 'log_frequency')):
        if not data_dict[key].empty:
            logs = data_dict[key][[p for p in data_dict[key].columns if p in pods]]
            parts.append(aggregate_frame(logs, windows, prefix, aggregations))

    # Every (window, pod) row, with the features that pod has
    grid = pd.MultiIndex.from_product([[w[0] for w in windows], sorted(pods)], names=['window_start', 'pod'])
    fused_df = pd.concat(parts, axis=1).reindex(grid).reset_index()
    window_end = dict(windows)
    fused_df.insert(2, 'window_end', fused_df['window_start'].map(window_end))
    window_number = {w[0]: i for i, w in enumerate(windows)}
    fused_df.insert(3, 'window_id', fused_df['pod'] + '_' + fused_df['window_start'].map(window_number).astype(str))
    fused_df = fused_df[['pod', 'window_start', 'window_end', 'window_id'] +
                        [c for c in fused_df.columns if c not in ID_COLUMNS]]

    fused_df.attrs.update({
        'window_size': window_size,
        'kpi_windows': window_kpi(data_dict.get('kpi'), windows),
        'fault_labels': data_dict.get('fault_labels', {}),
        'data_source': data_dict.get('config', {}).get('data_source', 'sample'),
    })

    feature_columns = [c for c in fused_df.columns if c not in ID_COLUMNS]
    print(f"\n{'─'*70}")
    print("FUSION SUMMARY")
    print(f"{'─'*70}")
    print(f"Pods fused:         {len(pods)}")
    print(f"Windows per pod:    {len(windows)}")
    print(f"Total rows:         {len(fused_df)}")
    print(f"Total columns:      {fused_df.shape[1]}")
    print(f"Empty feature cells: {fused_df[feature_columns].isna().to_numpy().mean():.1%} (metrics a pod doesn't report)")
    print(f"Feature groups:")
    print(f"  - Metrics: {len([c for c in fused_df.columns if c.startswith('metric_')])}")
    print(f"  - Golden logs: {len([c for c in fused_df.columns if c.startswith('log_golden_')])}")
    print(f"  - Frequency logs: {len([c for c in fused_df.columns if c.startswith('log_frequency_')])}")

    return fused_df


if __name__ == "__main__":
    from pipeline.ingest import load_data

    logging.basicConfig(level=logging.INFO)

    data_dict = load_data("config/pipeline_config.yaml")
    fused_df = fuse_modalities(data_dict)

    print("\n\nFirst few rows of fused data:")
    print(fused_df.head())
