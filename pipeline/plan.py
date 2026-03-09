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


def compute_baselines(
    fused_df: pd.DataFrame,
    baseline_window_percent: float = 70,
) -> Dict[str, Dict[str, float]]:
    """
    Compute baseline statistics from first N% of data.

    Args:
        fused_df: Fused DataFrame
        baseline_window_percent: Percentage of data to use for baseline (0-100)

    Returns:
        Dictionary of baseline stats per feature
    """
    cutoff_idx = int(len(fused_df) * baseline_window_percent / 100)
    baseline_data = fused_df.iloc[:cutoff_idx]

    baselines = {}

    for col in fused_df.columns:
        if col in ['pod', 'window_start', 'window_end', 'window_id']:
            continue

        data = baseline_data[col].dropna()
        if len(data) == 0:
            continue

        baselines[col] = {
            'mean': float(np.mean(data)),
            'std': float(np.std(data)),
            'min': float(np.min(data)),
            'max': float(np.max(data)),
            'p50': float(np.percentile(data, 50)),
            'p95': float(np.percentile(data, 95)),
            'p99': float(np.percentile(data, 99)),
        }

    return baselines


def detect_anomalies(
    fused_df: pd.DataFrame,
    baselines: Dict[str, Dict[str, float]],
    std_multiplier: float = 2.0,
    baseline_window_percent: float = 70,
) -> List[Dict[str, Any]]:
    """
    Detect anomalies in the analysis window (remaining N% of data).

    Args:
        fused_df: Fused DataFrame
        baselines: Baseline statistics
        std_multiplier: Number of std devs to flag as anomaly
        baseline_window_percent: Percentage used for baseline

    Returns:
        List of anomaly records
    """
    cutoff_idx = int(len(fused_df) * baseline_window_percent / 100)
    analysis_data = fused_df.iloc[cutoff_idx:]

    anomalies = []

    for idx, row in analysis_data.iterrows():
        pod = row['pod']
        window_id = row.get('window_id', f"{pod}_{idx}")

        for col in fused_df.columns:
            if col in ['pod', 'window_start', 'window_end', 'window_id']:
                continue

            if col not in baselines:
                continue

            value = row[col]
            if pd.isna(value):
                continue

            baseline = baselines[col]
            mean = baseline['mean']
            std = baseline['std']
            threshold = mean + (std_multiplier * std)

            if value > threshold:
                anomalies.append({
                    'window_id': window_id,
                    'pod': pod,
                    'feature': col,
                    'value': float(value),
                    'baseline_mean': mean,
                    'baseline_std': std,
                    'threshold': threshold,
                    'deviation': float((value - mean) / std) if std > 0 else 0,
                    'idx': idx,
                })

    return anomalies


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
        anomaly_summary = []
        for anomaly in pod_anomalies:
            anomaly_summary.append(
                f"- {anomaly['feature']}: {anomaly['value']:.2f} "
                f"(baseline: {anomaly['baseline_mean']:.2f}, "
                f"deviation: {anomaly['deviation']:.2f}σ)"
            )

        prompt = f"""
You are an IT operations expert analyzing a root cause analysis scenario using the LEMMA-RCA dataset.

Pod: {pod_name}
Anomalies detected: {len(pod_anomalies)}

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
) -> Dict[str, Any]:
    """
    Stage 3: Plan

    Detect anomalies and generate analysis with recommendations.

    Args:
        fused_df: Fused DataFrame from stage 2
        config: Pipeline configuration

    Returns:
        Dictionary with:
        - anomalies: all detected anomalies
        - analyses: per-pod analysis with recommendations
        - baselines: baseline statistics
        - summary: aggregated statistics
    """
    print("\n" + "="*70)
    print("STAGE 3: PLAN")
    print("="*70)

    thresholds = config.get('thresholds', {})
    std_multiplier = thresholds.get('std_multiplier', 2.0)
    baseline_window_percent = thresholds.get('baseline_window_percent', 70)

    # Compute baselines
    print(f"\nComputing baselines from first {baseline_window_percent}% of data...")
    baselines = compute_baselines(fused_df, baseline_window_percent)
    print(f"  ✓ Baseline stats computed for {len(baselines)} features")

    # Detect anomalies
    print(f"\nDetecting anomalies in remaining {100 - baseline_window_percent}% of data...")
    anomalies = detect_anomalies(
        fused_df,
        baselines,
        std_multiplier=std_multiplier,
        baseline_window_percent=baseline_window_percent,
    )
    print(f"  ✓ {len(anomalies)} anomalies detected")

    # Group by pod
    anomaly_groups = group_anomalies_by_pod(anomalies)
    print(f"\n  Affected pods: {len(anomaly_groups)}")

    # Generate analyses
    print(f"\nGenerating analyses and recommendations...")
    analyses = []
    use_llm = HAS_LLM and os.getenv('LLM_API_KEY')

    for pod_name in sorted(anomaly_groups.keys()):
        pod_anomalies = anomaly_groups[pod_name]

        # Try LLM analysis first if available
        analysis = None
        if use_llm:
            print(f"  → {pod_name}: Using LLM for analysis...", end='', flush=True)
            analysis = generate_llm_analysis(pod_name, pod_anomalies, anomaly_groups)
            if analysis:
                print(" ✓")
        else:
            print(f"  → {pod_name}: Using rule-based analysis...", end='', flush=True)
            analysis = generate_rule_based_analysis(pod_name, pod_anomalies)
            if analysis:
                print(" ✓")

        if analysis:
            analyses.append(analysis)

    # Summary statistics
    summary = {
        'total_anomalies': len(anomalies),
        'affected_pods': len(anomaly_groups),
        'analyses_generated': len(analyses),
        'avg_anomalies_per_pod': len(anomalies) / max(1, len(anomaly_groups)),
        'baseline_window_percent': baseline_window_percent,
        'analysis_window_percent': 100 - baseline_window_percent,
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
        'anomaly_groups': anomaly_groups,
        'baselines': baselines,
        'summary': summary,
        'config': config,
    }


if __name__ == "__main__":
    import logging
    from ingest import load_data
    from fuse import fuse_modalities

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
