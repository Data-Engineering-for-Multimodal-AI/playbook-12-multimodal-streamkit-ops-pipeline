"""
Stage 5: Act

Simulates execution of approved remediation actions.
Logs execution with timestamps and before/after states.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


def simulate_action_execution(
    action: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Simulate execution of a single action.

    Args:
        action: Action dictionary with pod, action, confidence

    Returns:
        Execution log entry
    """
    pod = action['pod']
    action_type = action['action']
    confidence = action['confidence']

    now = datetime.utcnow()

    execution_log = {
        'pod': pod,
        'action': action_type,
        'confidence': confidence,
        'status': 'executed',
        'timestamp_start': now,
        'timestamp_end': now + timedelta(seconds=np.random.randint(5, 30)),
        'duration_seconds': np.random.randint(5, 30),
    }

    # Simulate action-specific behavior
    if action_type == 'scale_up':
        execution_log.update({
            'before_replicas': np.random.randint(2, 5),
            'after_replicas': np.random.randint(3, 6),
            'change': 'scale_up',
            'details': 'Added replicas to handle load',
        })

    elif action_type == 'scale_down':
        execution_log.update({
            'before_replicas': np.random.randint(4, 8),
            'after_replicas': np.random.randint(2, 5),
            'change': 'scale_down',
            'details': 'Removed excess replicas',
        })

    elif action_type == 'restart':
        execution_log.update({
            'before_state': 'running',
            'after_state': 'running',
            'change': 'restart',
            'details': f'Gracefully restarted pod {pod}',
        })

    elif action_type == 'restart_with_debug':
        execution_log.update({
            'before_state': 'running',
            'after_state': 'running_with_debug',
            'change': 'restart_with_debug',
            'details': f'Restarted {pod} with debug logging enabled',
            'debug_features': ['cpu_profiling', 'memory_tracking', 'verbose_logging'],
        })

    elif action_type == 'collect_logs':
        execution_log.update({
            'change': 'collect_logs',
            'details': f'Collected logs from {pod}',
            'log_lines': np.random.randint(100, 1000),
            'log_size_mb': np.random.uniform(1, 50),
        })

    elif action_type == 'trigger_profiling':
        execution_log.update({
            'change': 'trigger_profiling',
            'details': f'Started profiling on {pod}',
            'profiling_duration_seconds': 60,
            'profile_types': ['cpu', 'memory'],
        })

    elif action_type == 'cordon_node':
        execution_log.update({
            'before_state': 'ready',
            'after_state': 'cordoned',
            'change': 'cordon_node',
            'details': f'Cordoned node to prevent new pod scheduling',
        })

    elif action_type == 'force_rebalance':
        execution_log.update({
            'change': 'force_rebalance',
            'details': f'Initiated pod rebalancing',
            'pods_moved': np.random.randint(1, 5),
        })

    return execution_log


def execute_actions(
    approved_actions: List[Dict[str, Any]],
    escalated_actions: Optional[List[Dict[str, Any]]] = None,
    rejected_actions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Stage 5: Act

    Simulate execution of approved remediation actions.

    Args:
        approved_actions: List of approved actions from check stage
        escalated_actions: List of escalated actions (for logging)
        rejected_actions: List of rejected actions (for logging)

    Returns:
        Execution log dictionary with:
        - executed_actions: List of executed action logs
        - escalated_actions: Original escalated actions
        - rejected_actions: Original rejected actions
        - summary: Execution statistics
    """
    print("\n" + "="*70)
    print("STAGE 5: ACT")
    print("="*70)

    if escalated_actions is None:
        escalated_actions = []
    if rejected_actions is None:
        rejected_actions = []

    executed_actions = []

    print(f"\nExecuting {len(approved_actions)} approved actions...")

    for action in approved_actions:
        pod = action['pod']
        action_type = action['action']

        print(f"  → {pod}: {action_type}...", end='', flush=True)

        try:
            execution_log = simulate_action_execution(action)
            executed_actions.append(execution_log)
            print(f" ✓ ({execution_log['duration_seconds']}s)")

        except Exception as e:
            print(f" ✗ Error: {e}")
            # Log failed action
            executed_actions.append({
                'pod': pod,
                'action': action_type,
                'status': 'failed',
                'error': str(e),
                'timestamp': datetime.utcnow(),
            })

    # Execution summary
    summary = {
        'total_executed': len(executed_actions),
        'total_escalated': len(escalated_actions),
        'total_rejected': len(rejected_actions),
        'actions_by_type': {},
        'execution_timestamp': datetime.utcnow(),
    }

    # Count by action type
    for action_log in executed_actions:
        action_type = action_log.get('action', 'unknown')
        if action_type not in summary['actions_by_type']:
            summary['actions_by_type'][action_type] = 0
        summary['actions_by_type'][action_type] += 1

    # Count affected pods
    affected_pods = set()
    for action_log in executed_actions:
        affected_pods.add(action_log.get('pod', 'unknown'))

    summary['affected_pods'] = len(affected_pods)

    print(f"\n{'─'*70}")
    print("EXECUTION SUMMARY")
    print(f"{'─'*70}")
    print(f"Actions executed:       {summary['total_executed']}")
    print(f"Affected pods:          {summary['affected_pods']}")
    print(f"Actions by type:")
    for action_type, count in sorted(summary['actions_by_type'].items()):
        print(f"  - {action_type}: {count}")
    print(f"Actions escalated:      {summary['total_escalated']}")
    print(f"Actions rejected:       {summary['total_rejected']}")

    return {
        'executed_actions': executed_actions,
        'escalated_actions': escalated_actions,
        'rejected_actions': rejected_actions,
        'summary': summary,
    }


if __name__ == "__main__":
    import logging
    from ingest import load_data
    from fuse import fuse_modalities
    from plan import plan_analysis
    from check import check_actions

    logging.basicConfig(level=logging.INFO)

    data_dict = load_data("config/pipeline_config.yaml")
    fused_df = fuse_modalities(data_dict)
    plan_result = plan_analysis(fused_df, data_dict['config'])
    approved, escalated, rejected = check_actions(plan_result, data_dict['config'])
    execution_log = execute_actions(approved, escalated, rejected)

    print("\n\nExecuted actions:")
    for action in execution_log['executed_actions'][:5]:
        print(f"  {action['pod']}: {action['action']} - {action['status']}")
