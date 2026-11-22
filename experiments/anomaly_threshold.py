"""Try this 1: how many standard deviations make an anomaly? (make try-anomaly-threshold)

The plan stage flags a feature of a pod in a window as anomalous when it is more than 2
standard deviations from that pod's own baseline (thresholds.std_multiplier in
config/pipeline_config.yaml), and ranks the pods by their anomaly count. This runs the six
stages with 1.5, 2, 3, 5 and 8 standard deviations and reports the anomalies, how many pods
have any, where the labelled root cause lands, and what the guardrails approve.

Runs on the bundled sample; CASE=20240115 make try-anomaly-threshold runs a downloaded case.
Rule-based analysis only; nothing is written.
"""

from _stages import case_from_env, describe, run

case = case_from_env()
print(f"Anomaly threshold on {describe(case)}\n")
print(f"{'std devs':>8} {'anomalies':>10} {'pods with any':>14} {'root cause rank':>16} {'its anomalies':>14} "
      f"{'next pod':>9} {'approved':>9} {'on root cause':>14}")
for k in (1.5, 2.0, 3.0, 5.0, 8.0):
    r = run(case, lambda c: c["thresholds"].update(std_multiplier=k))
    ranking, ev = r["plan"]["pod_ranking"], r["evaluation"]
    root = ev.get("root_cause_matched_pod")
    others = ranking.drop(index=root)["anomalies"] if root in ranking.index else ranking["anomalies"]
    rank = f"{ev['root_cause_rank']} of {ev['pods_ranked']}" if ev.get("root_cause_rank") else "-"
    on_root = sum(a["pod"] == root for a in r["approved"])
    print(f"{k:>8} {len(r['plan']['anomalies']):>10} {len(ranking):>14} {rank:>16} "
          f"{ev.get('root_cause_anomalies', 0):>14} {int(others.max()) if len(others) else 0:>9} "
          f"{len(r['approved']):>9} {on_root:>14}")
print("\nnext pod: the most anomalies of any other pod. approved: actions the guardrails let run.")
