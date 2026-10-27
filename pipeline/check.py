"""
Stage 4: Check (Guardrails)

Validates action recommendations against safety constraints.
Implements confidence gating, escalation rules, and rate limiting.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def validate_action_input(
    analysis: Dict[str, Any],
) -> Tuple[bool, str]:
    """
    Validate that analysis contains required fields.

    Args:
        analysis: Analysis dictionary from plan stage

    Returns:
        (is_valid, error_message)
    """
    required_fields = ['pod', 'recommendations', 'confidence']

    for field in required_fields:
        if field not in analysis:
            return False, f"Missing required field: {field}"

    if not isinstance(analysis['recommendations'], list):
        return False, "recommendations must be a list"

    for rec in analysis['recommendations']:
        if 'action' not in rec or 'confidence' not in rec:
            return False, "Each recommendation must have 'action' and 'confidence'"

    return True, ""


def filter_allowed_actions(
    recommendation: Dict[str, Any],
    allowed_actions: List[str],
) -> Tuple[bool, str]:
    """
    Check if recommended action is in the allowed list.

    Args:
        recommendation: Recommendation dictionary
        allowed_actions: List of allowed action types

    Returns:
        (is_allowed, reason)
    """
    action = recommendation.get('action', '')

    if action in allowed_actions:
        return True, ""
    else:
        return False, f"Action '{action}' not in allowed list"


def apply_confidence_gate(
    recommendation: Dict[str, Any],
    config: Dict[str, Any],
) -> Tuple[str, Optional[str]]:
    """
    Apply confidence-based action gating.

    Returns:
        (status, reason)
        status: 'approved', 'escalate', or 'reject'
    """
    confidence = recommendation.get('confidence', 0.0)
    guardrails = config.get('guardrails', {})

    confidence_high = guardrails.get('confidence_high', 0.85)
    confidence_medium = guardrails.get('confidence_medium', 0.6)

    if confidence >= confidence_high:
        return 'approved', None
    elif confidence >= confidence_medium:
        return 'escalate', f"Confidence {confidence:.2f} requires escalation"
    else:
        return 'reject', f"Confidence {confidence:.2f} below threshold {confidence_medium}"


def apply_action_policy(
    recommendation: Dict[str, Any],
    config: Dict[str, Any],
) -> Tuple[bool, str]:
    """
    Per-action policy from config action_policies: a minimum confidence, and actions that always
    need a human.

    Returns:
        (may_auto_approve, reason)
    """
    action = recommendation.get('action', '')
    policy = config.get('action_policies', {}).get(action)
    if not policy:
        return True, ""
    confidence = recommendation.get('confidence', 0.0)
    if confidence < policy.get('min_confidence', 0.0):
        return False, f"Confidence {confidence:.2f} below {action}'s minimum {policy['min_confidence']}"
    if policy.get('requires_escalation'):
        return False, f"Policy: {action} always needs human approval"
    return True, ""


def validate_scale_action(
    recommendation: Dict[str, Any],
    config: Dict[str, Any],
) -> Tuple[bool, str]:
    """
    Validate scale_up/scale_down actions against constraints.

    Args:
        recommendation: Recommendation dictionary
        config: Pipeline configuration

    Returns:
        (is_valid, reason)
    """
    action = recommendation.get('action', '')

    if action not in ['scale_up', 'scale_down']:
        return True, ""

    guardrails = config.get('guardrails', {})
    max_replica_scale = guardrails.get('max_replica_scale', 10)

    # Note: in a real system, we'd query current replica count
    # For simulation, we assume all pods start with reasonable counts
    if action == 'scale_up':
        # Assume scaling up by 1-3 replicas
        return True, ""
    else:
        return True, ""


def check_rate_limits(
    actions_taken: List[Dict[str, Any]],
    new_recommendation: Dict[str, Any],
    config: Dict[str, Any],
) -> Tuple[bool, str]:
    """
    Check rate limiting constraints.

    Args:
        actions_taken: List of previously taken actions
        new_recommendation: New recommendation to check
        config: Pipeline configuration

    Returns:
        (is_allowed, reason)
    """
    guardrails = config.get('guardrails', {})
    max_actions_per_minute = guardrails.get('max_actions_per_minute', 20)

    # Count actions in the last minute
    now = datetime.now(timezone.utc)
    recent_actions = [
        a for a in actions_taken
        if (now - a.get('timestamp', now)).total_seconds() < 60
    ]

    if len(recent_actions) >= max_actions_per_minute:
        return False, f"Rate limit: {max_actions_per_minute} actions/minute exceeded"

    return True, ""


def check_rollback_rate(
    actions_taken: List[Dict[str, Any]],
    new_action: str,
    config: Dict[str, Any],
) -> Tuple[bool, str]:
    """
    Check rollback rate limiting (e.g., max restarts per minute).

    Args:
        actions_taken: List of previously taken actions
        new_action: New action type to check
        config: Pipeline configuration

    Returns:
        (is_allowed, reason)
    """
    if 'restart' not in new_action:
        return True, ""

    guardrails = config.get('guardrails', {})
    max_rollback_rate = guardrails.get('max_rollback_rate', 5)

    now = datetime.now(timezone.utc)
    recent_restarts = [
        a for a in actions_taken
        if 'restart' in a.get('action', '') and
        (now - a.get('timestamp', now)).total_seconds() < 60
    ]

    if len(recent_restarts) >= max_rollback_rate:
        return False, f"Rollback rate limit: {max_rollback_rate} restarts/minute exceeded"

    return True, ""


def check_actions(
    plan_result: Dict[str, Any],
    config: Dict[str, Any],
    actions_taken: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Stage 4: Check (Guardrails)

    Validate action recommendations against safety constraints.

    Args:
        plan_result: Result dictionary from plan stage
        config: Pipeline configuration
        actions_taken: Previously taken actions (for rate limiting)

    Returns:
        (approved_actions, escalated_actions, rejected_actions)
    """
    print("\n" + "="*70)
    print("STAGE 4: CHECK (GUARDRAILS)")
    print("="*70)

    if actions_taken is None:
        actions_taken = []

    analyses = plan_result.get('analyses', [])
    allowed_actions = config.get('allowed_actions', [])
    guardrails = config.get('guardrails', {})

    approved_actions = []
    escalated_actions = []
    rejected_actions = []

    print(f"\nValidating {len(analyses)} analyses against guardrails...")

    for analysis in analyses:
        pod = analysis.get('pod', 'unknown')

        # Validate input
        is_valid, error = validate_action_input(analysis)
        if not is_valid:
            print(f"  ✗ {pod}: Input validation failed: {error}")
            continue

        print(f"  → {pod}")

        recommendations = analysis.get('recommendations', [])
        for rec_idx, rec in enumerate(recommendations):
            # Check if action is allowed
            is_allowed, filter_reason = filter_allowed_actions(rec, allowed_actions)
            if not is_allowed:
                rejected_actions.append({
                    'pod': pod,
                    'action': rec.get('action', ''),
                    'confidence': rec.get('confidence', 0),
                    'reason': filter_reason,
                    'timestamp': datetime.now(timezone.utc),
                })
                print(f"      Rec {rec_idx + 1}: ✗ {filter_reason}")
                continue

            # Apply confidence gating
            status, gate_reason = apply_confidence_gate(rec, config)

            if status == 'approved':
                # Additional validation for specific action types
                is_valid_scale, scale_reason = validate_scale_action(rec, config)
                if not is_valid_scale:
                    rejected_actions.append({
                        'pod': pod,
                        'action': rec.get('action', ''),
                        'confidence': rec.get('confidence', 0),
                        'reason': scale_reason,
                        'timestamp': datetime.now(timezone.utc),
                    })
                    print(f"      Rec {rec_idx + 1}: ✗ {scale_reason}")
                    continue

                # Per-action policy, then rate limits over what this run already approved
                may_approve, policy_reason = apply_action_policy(rec, config)
                if not may_approve:
                    escalated_actions.append({
                        'pod': pod,
                        'action': rec.get('action', ''),
                        'confidence': rec.get('confidence', 0),
                        'reason': policy_reason,
                        'timestamp': datetime.now(timezone.utc),
                    })
                    print(f"      Rec {rec_idx + 1}: ⚠ Escalated: {policy_reason}")
                    continue

                is_allowed_rate, rate_reason = check_rate_limits(
                    actions_taken + approved_actions, rec, config
                )
                if is_allowed_rate:
                    is_allowed_rate, rate_reason = check_rollback_rate(
                        actions_taken + approved_actions, rec.get('action', ''), config
                    )
                if not is_allowed_rate:
                    escalated_actions.append({
                        'pod': pod,
                        'action': rec.get('action', ''),
                        'confidence': rec.get('confidence', 0),
                        'reason': rate_reason,
                        'timestamp': datetime.now(timezone.utc),
                    })
                    print(f"      Rec {rec_idx + 1}: ⚠ Escalated: {rate_reason}")
                    continue

                approved_actions.append({
                    'pod': pod,
                    'action': rec.get('action', ''),
                    'confidence': rec.get('confidence', 0),
                    'severity': rec.get('severity', 'medium'),
                    'reason': rec.get('reason', ''),
                    'timestamp': datetime.now(timezone.utc),
                })
                print(f"      Rec {rec_idx + 1}: ✓ Approved ({rec.get('confidence', 0):.2f} confidence)")

            elif status == 'escalate':
                escalated_actions.append({
                    'pod': pod,
                    'action': rec.get('action', ''),
                    'confidence': rec.get('confidence', 0),
                    'reason': gate_reason or 'Confidence gating escalation',
                    'timestamp': datetime.now(timezone.utc),
                })
                print(f"      Rec {rec_idx + 1}: ⚠ Escalated: {gate_reason}")

            else:  # reject
                rejected_actions.append({
                    'pod': pod,
                    'action': rec.get('action', ''),
                    'confidence': rec.get('confidence', 0),
                    'reason': gate_reason or 'Confidence too low',
                    'timestamp': datetime.now(timezone.utc),
                })
                print(f"      Rec {rec_idx + 1}: ✗ Rejected: {gate_reason}")

    # Summary
    print(f"\n{'─'*70}")
    print("GUARDRAIL SUMMARY")
    print(f"{'─'*70}")
    print(f"Approved actions:       {len(approved_actions)}")
    print(f"Escalated actions:      {len(escalated_actions)}")
    print(f"Rejected actions:       {len(rejected_actions)}")

    if approved_actions:
        print(f"\nApproved:")
        for action in approved_actions:
            print(f"  - {action['pod']}: {action['action']} ({action['confidence']:.2f})")

    if escalated_actions:
        print(f"\nEscalated:")
        for action in escalated_actions[:5]:  # Show first 5
            print(f"  - {action['pod']}: {action['action']} ({action['reason']})")
        if len(escalated_actions) > 5:
            print(f"  ... and {len(escalated_actions) - 5} more")

    return approved_actions, escalated_actions, rejected_actions


if __name__ == "__main__":
    from pipeline.ingest import load_data
    from pipeline.fuse import fuse_modalities
    from pipeline.plan import plan_analysis

    logging.basicConfig(level=logging.INFO)

    data_dict = load_data("config/pipeline_config.yaml")
    fused_df = fuse_modalities(data_dict)
    plan_result = plan_analysis(fused_df, data_dict['config'])
    approved, escalated, rejected = check_actions(plan_result, data_dict['config'])

    print("\n\nApproved actions:")
    for action in approved[:5]:
        print(f"  {action['pod']}: {action['action']}")
