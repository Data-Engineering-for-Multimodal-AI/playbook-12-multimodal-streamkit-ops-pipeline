"""
Scoring a run against the case's fault label.

LEMMA-RCA labels each case with its root cause (usually a pod) and the time the failure started
affecting users. This checks where the root-cause pod landed in the pipeline's pod ranking, whether
any recommended action targeted it, and how the KPI incident lines up with the labelled failure time.
"""

import re
from typing import Any, Dict, List

import pandas as pd


def evaluate_run(plan_result: Dict[str, Any], execution_log: Dict[str, Any]) -> Dict[str, Any]:
    labels = plan_result.get('fault_labels') or {}
    if not labels.get('root_cause_pod') and not labels.get('failure_timestamp') and not labels.get('root_cause'):
        return {'available': False, 'reason': 'no fault label for this case'}

    result: Dict[str, Any] = {'available': True, 'root_cause': labels.get('root_cause')}
    incident = plan_result.get('incident', {})
    ranking = plan_result['pod_ranking']
    pods = list(ranking.index)

    # Timing: does the KPI incident start when the label says the failure started?
    failure = labels.get('failure_timestamp')
    if failure is not None and incident.get('detected'):
        result['labelled_failure_utc'] = labels.get('failure_time_utc')
        result['kpi_incident_start_utc'] = pd.Timestamp(incident['start'], unit='s', tz='UTC').isoformat()
        result['kpi_incident_offset_minutes'] = round((incident['start'] - failure) / 60, 1)
    elif labels.get('note'):
        result['time_note'] = labels['note']

    # Ranking: where is the root-cause pod?
    root = labels.get('root_cause_pod')
    if not root:
        result['pod_note'] = 'the root cause is not a pod, so there is no pod ranking to score'
        return result

    # Some labels name a deployment or one of several replicas: the best-ranked matching pod counts
    pattern = re.compile(labels.get('root_cause_match') or '^' + re.escape(root) + '$')
    rank = next((i + 1 for i, pod in enumerate(pods) if pattern.search(pod)), None)
    matched = pods[rank - 1] if rank else None
    actions: List[Dict[str, Any]] = (execution_log.get('executed_actions', []) +
                                     execution_log.get('escalated_actions', []))
    result.update({
        'root_cause_pod': root,
        'root_cause_matched_pod': matched,
        'root_cause_rank': rank,
        'pods_ranked': len(pods),
        'hit_at_1': rank == 1,
        'hit_at_3': rank is not None and rank <= 3,
        'hit_at_5': rank is not None and rank <= 5,
        'ranked_above_root_cause': pods[:min((rank or len(pods)) - 1, 5)],
        'root_cause_anomalies': int(ranking.loc[matched, 'anomalies']) if rank else 0,
        'root_cause_in_actions': any(a.get('pod') == matched for a in actions) if rank else False,
        'actions_on_other_pods': sum(a.get('pod') != matched for a in actions),
    })
    if rank and failure is not None:
        result['root_cause_first_anomaly_offset_minutes'] = round(
            (int(ranking.loc[matched, 'first_anomaly']) - failure) / 60, 1)
    return result
