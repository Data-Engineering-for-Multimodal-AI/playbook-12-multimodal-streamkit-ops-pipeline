"""
Stage 3: Plan

Detects anomalies by comparing metrics against baselines.
Optionally uses an LLM (any OpenAI-compatible API) for intelligent analysis.
Recommends remediation actions with confidence scores.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Try to import OpenAI-compatible client (optional)
try:
    from openai import OpenAI
    HAS_LLM = True
except ImportError:
    HAS_LLM = False


FEATURE_SKIP = ['pod', 'window_start', 'window_end', 'window_id']


def find_incident(kpi_windows: pd.DataFrame, config: Dict[str, Any], data_source: str) -> Dict[str, Any]:
    """When users were hurt, from the KPI alone (no labels).

    A window breaches when its KPI is below the threshold for this data source (LEMMA-RCA: error rate
    above 1%, the alert rule in the dataset's README). Breaches separated by short gaps are merged;
    runs of at least min_consecutive_windows are incidents. The incident with the largest impact
    (summed shortfall below the threshold) is the one analysed; the others are reported.
    """
    rules = config.get('incident', {})
    threshold = rules.get(data_source, {}).get('kpi_threshold')
    run_length = int(rules.get('min_consecutive_windows', 3))
    max_gap = int(rules.get('merge_gap_windows', 2))
    if threshold is None or kpi_windows is None or kpi_windows.empty or 'kpi' not in kpi_windows:
        return {'detected': False, 'reason': 'no KPI or no threshold for this data source'}
    kpi = kpi_windows['kpi']
    starts = kpi.index.to_numpy()
    breached = np.flatnonzero((kpi < threshold).to_numpy())

    runs = []
    for i in breached:
        if runs and i - runs[-1][1] <= max_gap + 1:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    incidents = []
    for first, last in runs:
        if last - first + 1 >= run_length:
            window = kpi.iloc[first:last + 1]
            incidents.append({'start': int(starts[first]), 'end': int(starts[last]), 'windows': int(last - first + 1),
                              'kpi_mean': float(window.mean()),
                              'impact': float((threshold - window).clip(lower=0).sum())})
    if not incidents:
        return {'detected': False, 'kpi_threshold': threshold, 'reason': 'KPI never stayed below the threshold'}

    main = max(incidents, key=lambda i: i['impact'])
    breach_starts = set(int(t) for t in starts[breached])
    normal_before = kpi[(kpi.index < main['start']) & ~kpi.index.isin(breach_starts)]
    return {'detected': True, **main, 'kpi_threshold': threshold, 'min_consecutive_windows': run_length,
            'kpi_before': float(normal_before.mean()) if len(normal_before) else None,
            'kpi_after': main['kpi_mean'], 'breached_windows': sorted(breach_starts),
            'incidents': incidents}


def split_windows(
    fused_df: pd.DataFrame,
    incident: Dict[str, Any],
    baseline_window_percent: float = 70,
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """Baseline = normal windows (KPI fine) before the incident; analysis = the incident's windows.
    Without an incident: the first N% of the time span, and the rest. Split by time, for every pod alike."""
    t = fused_df['window_start']
    if incident.get('detected'):
        breached = t.isin(incident['breached_windows'])
        baseline = fused_df[(t < incident['start']) & ~breached]
        analysis = fused_df[(t >= incident['start']) & (t <= incident['end'])]
        return baseline, analysis, 'normal windows before the incident'
    cut = t.min() + (t.max() - t.min()) * baseline_window_percent / 100
    return fused_df[t < cut], fused_df[t >= cut], f'first {baseline_window_percent}% of the time span'


def compute_baselines(
    baseline_data: pd.DataFrame,
) -> Dict[str, pd.DataFrame]:
    """
    Baseline statistics per pod and feature (each pod is compared with its own normal).

    Args:
        baseline_data: Fused rows of the baseline period

    Returns:
        {'mean': DataFrame (pods × features), 'std': DataFrame (pods × features)}
    """
    features = [c for c in baseline_data.columns if c not in FEATURE_SKIP]
    grouped = baseline_data.groupby('pod')[features]
    return {'mean': grouped.mean(), 'std': grouped.std(ddof=0)}


def detect_anomalies(
    analysis_data: pd.DataFrame,
    baselines: Dict[str, pd.DataFrame],
    std_multiplier: float = 2.0,
) -> pd.DataFrame:
    """
    Detect anomalies in the analysis period: a value above its pod's baseline mean plus
    std_multiplier standard deviations.

    Returns:
        One row per anomalous (window, pod, feature), with value, baseline and deviation in σ
    """
    features = list(baselines['mean'].columns)
    index = analysis_data.set_index(['window_id', 'window_start', 'pod'])[features]
    pods = index.index.get_level_values('pod')
    mean = baselines['mean'].reindex(pods).to_numpy()
    std = baselines['std'].reindex(pods).to_numpy()
    values = index.to_numpy(dtype=float)
    threshold = mean + std_multiplier * std
    with np.errstate(invalid='ignore', divide='ignore'):
        anomalous = np.isfinite(values) & np.isfinite(mean) & (values > threshold)
        # A feature that never varied in the baseline (std 0): any rise is anomalous; its deviation is
        # measured against a tiny floor so it sorts above ordinary ones
        deviation = (values - mean) / np.maximum(std, 1e-9)
    rows, cols = np.nonzero(anomalous)
    keys = index.index[rows]
    return pd.DataFrame({
        'window_id': keys.get_level_values('window_id'),
        'window_start': keys.get_level_values('window_start'),
        'pod': keys.get_level_values('pod'),
        'feature': np.array(features)[cols],
        'value': values[rows, cols],
        'baseline_mean': mean[rows, cols],
        'baseline_std': std[rows, cols],
        'threshold': threshold[rows, cols],
        'deviation': deviation[rows, cols],
    })


def rank_pods(anomalies: pd.DataFrame) -> pd.DataFrame:
    """Pods by number of anomalies, then by their largest deviation"""
    if anomalies.empty:
        return pd.DataFrame(columns=['anomalies', 'max_deviation', 'first_anomaly'])
    ranking = anomalies.groupby('pod').agg(anomalies=('feature', 'size'), max_deviation=('deviation', 'max'),
                                           first_anomaly=('window_start', 'min'))
    return ranking.sort_values(['anomalies', 'max_deviation'], ascending=False)


def group_anomalies_by_pod(
    anomalies: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group anomalies by pod for coherent analysis.

    Args:
        anomalies: List of anomaly records

    Returns:
        Dictionary mapping pod names to their anomalies
    """
    grouped = {}

    for anomaly in anomalies:
        pod = anomaly['pod']
        if pod not in grouped:
            grouped[pod] = []
        grouped[pod].append(anomaly)

    return grouped


def compute_anomaly_confidence(
    anomalies: List[Dict[str, Any]],
) -> float:
    """
    Compute confidence score for a set of anomalies.

    Based on deviation magnitude and consistency across features.

    Args:
        anomalies: List of anomalies for a pod

    Returns:
        Confidence score (0.0 to 1.0)
    """
    if not anomalies:
        return 0.0

    # Average absolute deviation
    deviations = [abs(a['deviation']) for a in anomalies]
    avg_deviation = np.mean(deviations)

    # Normalize to 0-1 range: 2 std devs = 0.5 confidence, 4+ = 0.95+ confidence
    confidence = min(0.95, avg_deviation / 4.0)

    # Boost confidence for multiple simultaneous anomalies
    if len(anomalies) >= 2:
        confidence = min(0.95, confidence * 1.1)

    return float(confidence)


def generate_rule_based_analysis(
    pod_name: str,
    pod_anomalies: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Generate analysis using rule-based heuristics.

    Args:
        pod_name: Pod name
        pod_anomalies: List of anomalies for the pod

    Returns:
        Analysis dictionary with recommendations
    """
    if not pod_anomalies:
        return None

    # Count anomalies by type
    cpu_anomalies = [a for a in pod_anomalies if 'cpu_usage' in a['feature']]
    mem_anomalies = [a for a in pod_anomalies if 'memory_usage' in a['feature']]
    net_anomalies = [a for a in pod_anomalies if 'bandwidth' in a['feature'] or 'packets' in a['feature']]
    io_anomalies = [a for a in pod_anomalies if 'iops' in a['feature']]

    analysis = {
        'pod': pod_name,
        'anomaly_count': len(pod_anomalies),
        'anomalies': pod_anomalies,
        'anomaly_types': {
            'cpu': len(cpu_anomalies),
            'memory': len(mem_anomalies),
            'network': len(net_anomalies),
            'io': len(io_anomalies),
        },
    }

    # Generate recommendations based on anomaly patterns
    recommendations = []

    if len(cpu_anomalies) >= 3:
        recommendations.append({
            'action': 'scale_up',
            'reason': 'High CPU usage across multiple time windows',
            'confidence': 0.80,
            'severity': 'high',
        })
    elif len(cpu_anomalies) >= 1:
        recommendations.append({
            'action': 'restart_with_debug',
            'reason': 'CPU spike detected',
            'confidence': 0.65,
            'severity': 'medium',
        })

    if len(mem_anomalies) >= 3:
        recommendations.append({
            'action': 'restart',
            'reason': 'Possible memory leak (sustained high usage)',
            'confidence': 0.75,
            'severity': 'high',
        })
    elif len(mem_anomalies) >= 1:
        recommendations.append({
            'action': 'collect_logs',
            'reason': 'Memory usage anomaly - collect diagnostics',
            'confidence': 0.60,
            'severity': 'low',
        })

    if len(net_anomalies) >= 2:
        recommendations.append({
            'action': 'trigger_profiling',
            'reason': 'Network bandwidth anomaly',
            'confidence': 0.70,
            'severity': 'medium',
        })

    if len(io_anomalies) >= 2:
        recommendations.append({
            'action': 'trigger_profiling',
            'reason': 'Storage I/O anomaly',
            'confidence': 0.65,
            'severity': 'medium',
        })

    if not recommendations:
        # Default action for any anomaly
        recommendations.append({
            'action': 'collect_logs',
            'reason': 'Anomaly detected - collecting diagnostic data',
            'confidence': 0.50,
            'severity': 'low',
        })

    # Scale recommendation confidence by overall pod anomaly confidence.
    # A pod with massive deviations across many features should produce
    # higher-confidence recommendations than one with minor blips.
    pod_confidence = compute_anomaly_confidence(pod_anomalies)
    for rec in recommendations:
        # Blend: 40% base heuristic + 60% pod-level confidence
        rec['confidence'] = round(
            min(0.95, 0.4 * rec['confidence'] + 0.6 * pod_confidence), 2
        )

    analysis['recommendations'] = recommendations
    analysis['confidence'] = pod_confidence

    return analysis


def generate_llm_analysis(
    pod_name: str,
    pod_anomalies: List[Dict[str, Any]],
    anomaly_groups: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """
    Generate analysis using an LLM (OpenAI-compatible API) for intelligent reasoning.

    Args:
        pod_name: Pod name
        pod_anomalies: List of anomalies for the pod
        anomaly_groups: All anomalies grouped by pod

    Returns:
        Analysis dictionary with recommendations
    """
    if not HAS_LLM or not os.getenv('LLM_API_KEY'):
        return None

    try:
        client = OpenAI(
            api_key=os.getenv('LLM_API_KEY'),
            base_url=os.getenv('LLM_BASE_URL', 'https://api.openai.com/v1'),
        )

        # Build context for the LLM
        # The strongest deviations only: a pod can have thousands of anomalous cells
        strongest = sorted(pod_anomalies, key=lambda a: a['deviation'], reverse=True)[:50]
        anomaly_summary = []
        for anomaly in strongest:
            anomaly_summary.append(
                f"- {anomaly['feature']}: {anomaly['value']:.2f} "
                f"(baseline: {anomaly['baseline_mean']:.2f}, "
                f"deviation: {anomaly['deviation']:.2f}σ)"
            )

        prompt = f"""
You are an IT operations expert analyzing a root cause analysis scenario using the LEMMA-RCA dataset.

Pod: {pod_name}
Anomalies detected: {len(pod_anomalies)} (the {len(strongest)} strongest below)

Details:
{chr(10).join(anomaly_summary)}

Based on these metrics, what is the likely root cause and what remediation action should be taken?

Respond in JSON format:
{{
    "root_cause": "brief root cause description",
    "severity": "low|medium|high",
    "recommended_action": "action name (scale_up, scale_down, restart, etc.)",
    "confidence": 0.0-1.0,
    "reasoning": "explanation of analysis"
}}
"""

        model = os.getenv('LLM_MODEL', 'gpt-4o')
        response = client.chat.completions.create(
            model=model,
            max_tokens=500,
            temperature=0.2,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        response_text = response.choices[0].message.content

        # Try to parse JSON from response
        try:
            if '{' in response_text:
                json_start = response_text.index('{')
                json_end = response_text.rindex('}') + 1
                json_str = response_text[json_start:json_end]
                llm_result = json.loads(json_str)
            else:
                llm_result = json.loads(response_text)
        except (json.JSONDecodeError, ValueError):
            # If parsing fails, return None to fall back to rule-based
            return None

        analysis = {
            'pod': pod_name,
            'anomaly_count': len(pod_anomalies),
            'anomalies': pod_anomalies,
            'root_cause': llm_result.get('root_cause', 'Unknown'),
            'confidence': float(llm_result.get('confidence', 0.5)),
            'recommendations': [
                {
                    'action': llm_result.get('recommended_action', 'collect_logs'),
                    'reason': llm_result.get('reasoning', ''),
                    'confidence': float(llm_result.get('confidence', 0.5)),
                    'severity': llm_result.get('severity', 'medium'),
                }
            ],
        }

        return analysis

    except Exception as e:
        logger.warning(f"LLM analysis failed: {e}. Falling back to rule-based.")
        return None


def plan_analysis(
    fused_df: pd.DataFrame,
    config: Dict[str, Any],
    kpi_windows: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """
    Stage 3: Plan

    Find when the incident started (KPI), detect anomalies against each pod's own baseline,
    rank the pods and generate analyses with recommendations for the top ones.

    Args:
        fused_df: Fused DataFrame from stage 2 (its attrs carry the KPI per window)
        config: Pipeline configuration
        kpi_windows: KPI per window (default: fused_df.attrs['kpi_windows'])

    Returns:
        Dictionary with:
        - anomalies: DataFrame of anomalous (window, pod, feature) cells
        - analyses: per-pod analysis with recommendations (top pods)
        - pod_ranking: pods by anomaly count
        - incident: when the KPI showed users being hurt
        - baselines: baseline statistics
        - summary: aggregated statistics
    """
    print("\n" + "="*70)
    print("STAGE 3: PLAN")
    print("="*70)

    thresholds = config.get('thresholds', {})
    std_multiplier = thresholds.get('std_multiplier', 2.0)
    baseline_window_percent = thresholds.get('baseline_window_percent', 70)
    max_pods = int(config.get('planning', {}).get('max_pods_to_analyze', 10))
    if kpi_windows is None:
        kpi_windows = fused_df.attrs.get('kpi_windows')
    data_source = fused_df.attrs.get('data_source', config.get('data_source', 'sample'))

    # When did users start being hurt?
    print("\nLooking for the incident in the KPI...")
    incident = find_incident(kpi_windows, config, data_source)
    if incident['detected']:
        print(f"  ✓ {len(incident['incidents'])} period(s) with the KPI below {incident['kpi_threshold']}; analysing the largest:")
        print(f"    {format_time(incident['start'], data_source)} to {format_time(incident['end'], data_source)} "
              f"({incident['windows']} windows; KPI {incident['kpi_before']:.3f} before, {incident['kpi_after']:.3f} during)")
    else:
        print(f"  ⚠ No incident found ({incident['reason']}); using the first {baseline_window_percent}% of time as baseline")

    baseline_data, analysis_data, how = split_windows(fused_df, incident, baseline_window_percent)
    windows = fused_df['window_start'].nunique()
    print(f"\nComputing baselines per pod from {baseline_data['window_start'].nunique()} of {windows} windows ({how})...")
    baselines = compute_baselines(baseline_data)
    print(f"  ✓ Baseline stats computed for {baselines['mean'].shape[1]} features × {baselines['mean'].shape[0]} pods")

    print(f"\nDetecting anomalies in {analysis_data['window_start'].nunique()} windows...")
    anomalies = detect_anomalies(analysis_data, baselines, std_multiplier=std_multiplier)
    ranking = rank_pods(anomalies)
    print(f"  ✓ {len(anomalies)} anomalies detected")
    print(f"\n  Affected pods: {len(ranking)}")
    for pod, row in ranking.head(5).iterrows():
        print(f"    {int(row['anomalies']):6d}  {pod}")

    # Generate analyses for the top pods
    top = list(ranking.index[:max_pods])
    print(f"\nGenerating analyses and recommendations (top {len(top)} pods)...")
    analyses = []
    use_llm = HAS_LLM and os.getenv('LLM_API_KEY')
    anomaly_groups = {pod: anomalies[anomalies['pod'] == pod].to_dict('records') for pod in top}

    for pod_name in top:
        pod_anomalies = anomaly_groups[pod_name]

        # Try LLM analysis first if available; fall back to the rules if it fails
        analysis = None
        if use_llm:
            print(f"  → {pod_name}: Using LLM for analysis...", end='', flush=True)
            analysis = generate_llm_analysis(pod_name, pod_anomalies, anomaly_groups)
            print(" ✓" if analysis else " ✗ failed, using rule-based analysis...", end='\n' if analysis else '')
        else:
            print(f"  → {pod_name}: Using rule-based analysis...", end='', flush=True)
        if analysis is None:
            analysis = generate_rule_based_analysis(pod_name, pod_anomalies)
            if analysis:
                print(" ✓")

        if analysis:
            analysis['rank'] = len(analyses) + 1
            analysis['anomalies'] = sorted(pod_anomalies, key=lambda a: a['deviation'], reverse=True)[:20]
            analyses.append(analysis)

    # Summary statistics
    summary = {
        'total_anomalies': len(anomalies),
        'affected_pods': len(ranking),
        'analyses_generated': len(analyses),
        'avg_anomalies_per_pod': len(anomalies) / max(1, len(ranking)),
        'baseline_windows': int(baseline_data['window_start'].nunique()),
        'analysis_windows': int(analysis_data['window_start'].nunique()),
        'baseline': how,
        'llm_enabled': bool(use_llm),
    }

    print(f"\n{'─'*70}")
    print("PLANNING SUMMARY")
    print(f"{'─'*70}")
    print(f"Anomalies detected:     {summary['total_anomalies']}")
    print(f"Affected pods:          {summary['affected_pods']}")
    print(f"Analyses generated:     {summary['analyses_generated']}")
    print(f"Avg anomalies/pod:      {summary['avg_anomalies_per_pod']:.1f}")
    print(f"LLM analysis:           {'✓ Enabled' if use_llm else '✗ Disabled'}")

    return {
        'anomalies': anomalies,
        'analyses': analyses,
        'pod_ranking': ranking,
        'incident': incident,
        'baselines': baselines,
        'summary': summary,
        'fault_labels': fused_df.attrs.get('fault_labels', {}),
        'data_source': data_source,
        'config': config,
    }


def format_time(t: int, data_source: str) -> str:
    """Unix time for LEMMA-RCA cases; step number for the clock-less sample"""
    if data_source == 'lemma-rca':
        return pd.Timestamp(int(t), unit='s', tz='UTC').strftime('%Y-%m-%d %H:%M UTC')
    return f"step {int(t)}"


if __name__ == "__main__":
    from pipeline.ingest import load_data
    from pipeline.fuse import fuse_modalities

    logging.basicConfig(level=logging.INFO)

    data_dict = load_data("config/pipeline_config.yaml")
    fused_df = fuse_modalities(data_dict)
    plan_result = plan_analysis(fused_df, data_dict['config'])

    print("\n\nSample analyses:")
    for analysis in plan_result['analyses'][:3]:
        print(f"\nPod: {analysis['pod']}")
        print(f"  Anomalies: {analysis['anomaly_count']}")
        print(f"  Confidence: {analysis['confidence']:.2f}")
        for rec in analysis['recommendations']:
            print(f"  - {rec['action']}: {rec['reason']}")
