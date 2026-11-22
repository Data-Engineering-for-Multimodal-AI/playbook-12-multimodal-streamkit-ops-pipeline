"""Why does a pod rank where it does? (make explain POD=... [CASE=...])

    make explain POD=gateway-stu901
    make explain POD=scenario10-malware-deployment-57db4df9f4-p8h7h CASE=20240115

Runs the six stages quietly (rule-based, nothing written), then prints the pod's place in the
ranking, its strongest deviations from its own baseline, and what the guardrails did with the
actions recommended for it. A pod name can be the start of a name (scenario10-malware).
"""

import argparse
import contextlib
import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.pop("LLM_API_KEY", None)   # rule-based: this never calls an LLM

from pipeline.check import check_actions  # noqa: E402
from pipeline.fuse import fuse_modalities  # noqa: E402
from pipeline.ingest import load_data  # noqa: E402
from pipeline.plan import format_time, plan_analysis  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pod", required=True)
    parser.add_argument("--case", default=None, help="a downloaded LEMMA-RCA case (default: the bundled sample)")
    parser.add_argument("--top", type=int, default=8)
    args = parser.parse_args()

    with contextlib.redirect_stdout(io.StringIO()):
        data = load_data(str(ROOT / "config" / "pipeline_config.yaml"), args.case)
        fused = fuse_modalities(data)
        plan = plan_analysis(fused, data["config"])
        approved, escalated, rejected = check_actions(plan, data["config"])
    ranking = plan["pod_ranking"]
    matches = [p for p in ranking.index if p == args.pod] or [p for p in ranking.index if p.startswith(args.pod)]
    if not matches:
        sys.exit(f"No pod named {args.pod!r} has anomalies. The top 5: {', '.join(ranking.index[:5])}")
    pod = matches[0]
    rank = list(ranking.index).index(pod) + 1
    row = ranking.loc[pod]
    source = plan["data_source"]
    print(f"{pod}: rank {rank} of {len(ranking)}, {int(row['anomalies'])} anomalies, "
          f"first at {format_time(int(row['first_anomaly']), source)}")
    if rank > 1:
        print(f"Ranked above it: {', '.join(f'{p} ({int(n)})' for p, n in ranking['anomalies'].iloc[:min(rank - 1, 3)].items())}")

    anomalies = plan["anomalies"]
    top = anomalies[anomalies["pod"] == pod].sort_values("deviation", ascending=False).head(args.top)
    print(f"\nStrongest deviations from its baseline (in standard deviations):")
    print(f"  {'window':<22} {'feature':<38} {'value':>10} {'baseline':>10} {'std devs':>9}")
    for a in top.itertuples():
        print(f"  {format_time(int(a.window_start), source):<22} {a.feature:<38} {a.value:>10.3g} "
              f"{a.baseline_mean:>10.3g} {a.deviation:>9.1f}")

    decisions = [("runs", x) for x in approved] + [("to a person", x) for x in escalated] + \
                [("rejected", x) for x in rejected]
    mine = [(d, x) for d, x in decisions if x.get("pod") == pod]
    print(f"\nRecommended actions: {len(mine) or 'none (only the top pods get recommendations)'}")
    for d, x in mine:
        why = f" ({x['reason']})" if d != "runs" and x.get("reason") else ""
        print(f"  {x['action']:<18} confidence {x['confidence']:.2f}  {d}{why}")


if __name__ == "__main__":
    main()
