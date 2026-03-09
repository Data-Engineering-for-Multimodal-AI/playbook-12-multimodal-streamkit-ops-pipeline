"""
Stage 6: Observe

Aggregates all pipeline outputs into observability reports and dashboards.
Generates JSON reports and human-readable summaries.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def compute_confidence_distribution(
    execution_log: Dict[str, Any],
) -> Dict[str, int]:
    """
    Compute distribution of confidence scores.

    Args:
        execution_log: Execution log from act stage

    Returns:
        Distribution dictionary: {confidence_bucket: count}
    """
    distribution = {
        'very_low': 0,  # < 0.4
        'low': 0,       # 0.4-0.6
        'medium': 0,    # 0.6-0.75
        'high': 0,      # 0.75-0.85
        'very_high': 0, # >= 0.85
    }

    for action in execution_log.get('executed_actions', []):
        confidence = action.get('confidence', 0)

        if confidence < 0.4:
            distribution['very_low'] += 1
        elif confidence < 0.6:
            distribution['low'] += 1
        elif confidence < 0.75:
            distribution['medium'] += 1
        elif confidence < 0.85:
            distribution['high'] += 1
        else:
            distribution['very_high'] += 1

    return distribution


def extract_root_causes(
    plan_result: Dict[str, Any],
) -> Dict[str, int]:
    """
    Extract and count root cause classifications.

    Args:
        plan_result: Plan result dictionary

    Returns:
        Root cause counts
    """
    root_causes = {}

    for analysis in plan_result.get('analyses', []):
        root_cause = analysis.get('root_cause', 'Unknown')

        if root_cause not in root_causes:
            root_causes[root_cause] = 0
        root_causes[root_cause] += 1

    return root_causes


def generate_json_report(
    plan_result: Dict[str, Any],
    execution_log: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Generate comprehensive JSON report.

    Args:
        plan_result: Plan stage result
        execution_log: Execution log from act stage
        config: Pipeline configuration

    Returns:
        Report dictionary
    """
    confidence_dist = compute_confidence_distribution(execution_log)
    root_causes = extract_root_causes(plan_result)

    # Action breakdown
    action_summary = {}
    for action in execution_log.get('executed_actions', []):
        action_type = action.get('action', 'unknown')
        if action_type not in action_summary:
            action_summary[action_type] = {'count': 0, 'avg_confidence': 0, 'total_confidence': 0}
        action_summary[action_type]['count'] += 1
        action_summary[action_type]['total_confidence'] += action.get('confidence', 0)

    # Compute averages
    for action_type in action_summary:
        count = action_summary[action_type]['count']
        total = action_summary[action_type]['total_confidence']
        action_summary[action_type]['avg_confidence'] = total / count if count > 0 else 0

    # Build report
    report = {
        'timestamp': datetime.utcnow().isoformat(),
        'pipeline_config': {
            'case': config.get('case', 'unknown'),
            'service': config.get('label', 'unknown'),
            'data_path': config.get('data_path', 'unknown'),
        },
        'processing_summary': {
            'total_anomalies_detected': plan_result['summary'].get('total_anomalies', 0),
            'affected_pods': plan_result['summary'].get('affected_pods', 0),
            'analyses_generated': plan_result['summary'].get('analyses_generated', 0),
        },
        'actions_summary': {
            'total_executed': execution_log['summary']['total_executed'],
            'total_escalated': execution_log['summary']['total_escalated'],
            'total_rejected': execution_log['summary']['total_rejected'],
            'affected_pods': execution_log['summary']['affected_pods'],
            'by_type': action_summary,
        },
        'confidence_distribution': confidence_dist,
        'root_causes': root_causes,
        'top_anomalies': [],
    }

    # Extract top anomalies
    anomalies_by_frequency = {}
    for anomaly in plan_result.get('anomalies', []):
        feature = anomaly.get('feature', 'unknown')
        if feature not in anomalies_by_frequency:
            anomalies_by_frequency[feature] = 0
        anomalies_by_frequency[feature] += 1

    # Sort and take top 10
    for feature, count in sorted(
        anomalies_by_frequency.items(),
        key=lambda x: x[1],
        reverse=True
    )[:10]:
        report['top_anomalies'].append({
            'feature': feature,
            'occurrences': count,
        })

    return report


def generate_text_dashboard(
    report: Dict[str, Any],
) -> str:
    """
    Generate human-readable text dashboard.

    Args:
        report: Report dictionary

    Returns:
        Formatted text dashboard
    """
    dashboard = []

    dashboard.append("\n" + "="*70)
    dashboard.append("OBSERVABILITY DASHBOARD")
    dashboard.append("="*70)

    # Header
    config = report['pipeline_config']
    dashboard.append(f"\nPipeline Configuration:")
    dashboard.append(f"  Case ID:    {config.get('case', 'unknown')}")
    dashboard.append(f"  Service:    {config.get('service', 'unknown')}")
    dashboard.append(f"  Timestamp:  {report['timestamp']}")

    # Processing Summary
    proc = report['processing_summary']
    dashboard.append(f"\n{'─'*70}")
    dashboard.append(f"Processing Summary:")
    dashboard.append(f"  Anomalies detected:     {proc['total_anomalies_detected']}")
    dashboard.append(f"  Affected pods:          {proc['affected_pods']}")
    dashboard.append(f"  Analyses generated:     {proc['analyses_generated']}")

    # Actions Summary
    actions = report['actions_summary']
    dashboard.append(f"\n{'─'*70}")
    dashboard.append(f"Actions Taken:")
    dashboard.append(f"  ✓ Executed:             {actions['total_executed']}")
    dashboard.append(f"  ⚠ Escalated:            {actions['total_escalated']}")
    dashboard.append(f"  ✗ Rejected:             {actions['total_rejected']}")
    dashboard.append(f"  Pods affected:          {actions['affected_pods']}")

    # Actions by type
    if actions['by_type']:
        dashboard.append(f"\n  Actions by type:")
        for action_type in sorted(actions['by_type'].keys()):
            count = actions['by_type'][action_type]['count']
            avg_conf = actions['by_type'][action_type]['avg_confidence']
            dashboard.append(f"    - {action_type:25s}: {count:3d} actions (avg confidence: {avg_conf:.2f})")

    # Confidence Distribution
    conf = report['confidence_distribution']
    dashboard.append(f"\n{'─'*70}")
    dashboard.append(f"Confidence Distribution:")
    dashboard.append(f"  Very High (≥0.85):      {conf['very_high']:4d} actions")
    dashboard.append(f"  High (0.75-0.85):       {conf['high']:4d} actions")
    dashboard.append(f"  Medium (0.60-0.75):     {conf['medium']:4d} actions")
    dashboard.append(f"  Low (0.40-0.60):        {conf['low']:4d} actions")
    dashboard.append(f"  Very Low (<0.40):       {conf['very_low']:4d} actions")

    # Root Causes
    root_causes = report['root_causes']
    if root_causes:
        dashboard.append(f"\n{'─'*70}")
        dashboard.append(f"Root Causes Identified:")
        for cause in sorted(root_causes.keys(), key=lambda x: root_causes[x], reverse=True)[:10]:
            count = root_causes[cause]
            dashboard.append(f"  - {cause:40s}: {count:3d} occurrences")

    # Top Anomalies
    anomalies = report['top_anomalies']
    if anomalies:
        dashboard.append(f"\n{'─'*70}")
        dashboard.append(f"Top Anomalous Features:")
        for anomaly in anomalies[:10]:
            feature = anomaly['feature']
            count = anomaly['occurrences']
            dashboard.append(f"  - {feature:50s}: {count:4d} times")

    dashboard.append(f"\n{'='*70}\n")

    return "\n".join(dashboard)


def generate_report(
    execution_log: Dict[str, Any],
    plan_result: Dict[str, Any],
    config: Dict[str, Any],
    output_dir: str = "output/",
) -> Dict[str, Any]:
    """
    Stage 6: Observe

    Generate comprehensive observability reports.

    Args:
        execution_log: Execution log from act stage
        plan_result: Plan result from plan stage
        config: Pipeline configuration
        output_dir: Output directory for reports

    Returns:
        Report dictionary
    """
    print("\n" + "="*70)
    print("STAGE 6: OBSERVE")
    print("="*70)

    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate JSON report
    print(f"\nGenerating observability report...")
    report = generate_json_report(plan_result, execution_log, config)

    # Write JSON report
    report_file = output_path / "observability_report.json"
    try:
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        print(f"  ✓ JSON report: {report_file}")
    except Exception as e:
        print(f"  ✗ Error writing JSON report: {e}")

    # Generate text dashboard
    dashboard_text = generate_text_dashboard(report)

    # Write text dashboard
    dashboard_file = output_path / "observability_dashboard.txt"
    try:
        with open(dashboard_file, 'w') as f:
            f.write(dashboard_text)
        print(f"  ✓ Text dashboard: {dashboard_file}")
    except Exception as e:
        print(f"  ✗ Error writing text dashboard: {e}")

    # Print dashboard to console
    print("\n" + dashboard_text)

    # Summary statistics
    summary = {
        'total_anomalies': plan_result['summary'].get('total_anomalies', 0),
        'total_analyses': plan_result['summary'].get('analyses_generated', 0),
        'total_actions_executed': execution_log['summary']['total_executed'],
        'total_actions_escalated': execution_log['summary']['total_escalated'],
        'total_actions_rejected': execution_log['summary']['total_rejected'],
        'report_file': str(report_file),
        'dashboard_file': str(dashboard_file),
    }

    return {
        'report': report,
        'summary': summary,
        'files': {
            'json': str(report_file),
            'text': str(dashboard_file),
        },
    }


if __name__ == "__main__":
    import logging
    from ingest import load_data
    from fuse import fuse_modalities
    from plan import plan_analysis
    from check import check_actions
    from act import execute_actions

    logging.basicConfig(level=logging.INFO)

    data_dict = load_data("config/pipeline_config.yaml")
    fused_df = fuse_modalities(data_dict)
    plan_result = plan_analysis(fused_df, data_dict['config'])
    approved, escalated, rejected = check_actions(plan_result, data_dict['config'])
    execution_log = execute_actions(approved, escalated, rejected)
    observe_result = generate_report(execution_log, plan_result, data_dict['config'])

    print("\nReport files:")
    print(f"  JSON: {observe_result['files']['json']}")
    print(f"  Text: {observe_result['files']['text']}")
