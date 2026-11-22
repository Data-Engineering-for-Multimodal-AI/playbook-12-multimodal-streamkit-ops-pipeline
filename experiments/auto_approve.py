"""Try this 3: how confident must a recommendation be to run without a person? (make try-auto-approve)

The check stage runs a recommended action by itself only when its confidence is at least
0.85 (guardrails.confidence_high in config/pipeline_config.yaml); between 0.6 and that, a
person decides. This runs the six stages with the bar at 0.75, 0.80, 0.85, 0.88 and 0.90, and
counts the actions that run, those that go to a person, and how many of the actions that run
target the labelled root cause.

Runs on the bundled sample; CASE=20240115 make try-auto-approve runs a downloaded case.
Rule-based analysis only; the act stage is simulated; nothing is written.
"""

from _stages import case_from_env, describe, run

case = case_from_env()
print(f"Auto-approve confidence on {describe(case)}\n")
print(f"{'confidence':>10} {'run':>5} {'to a person':>12} {'rejected':>9} {'run on root cause':>18} "
      f"{'run on other pods':>18}  stopped by a limit")
for bar in (0.75, 0.80, 0.85, 0.88, 0.90):
    r = run(case, lambda c: c["guardrails"].update(confidence_high=bar))
    root = r["evaluation"].get("root_cause_matched_pod")
    on_root = sum(a["pod"] == root for a in r["approved"])
    limits = sum("limit" in str(a.get("reason", "")).lower() for a in r["escalated"])
    print(f"{bar:>10.2f} {len(r['approved']):>5} {len(r['escalated']):>12} {len(r['rejected']):>9} "
          f"{on_root:>18} {len(r['approved']) - on_root:>18}  {limits}")
