"""Try this 2: how long should a fusion window be? (make try-window-size)

The fuse stage aligns metrics and logs by pod in 5-minute windows
(feature_engineering.window_size in config/pipeline_config.yaml), and the plan stage finds the
incident in the KPI per window: 3 windows in a row below the threshold. This runs the six
stages with 1, 2.5, 5, 10 and 20-minute windows and reports the windows, when the incident is
found relative to the labelled failure, and where the root cause lands.

Runs on the bundled sample; CASE=20240115 make try-window-size runs a downloaded case (only a
real case has a failure time to compare with). Rule-based analysis only; nothing is written.
"""

import time

from _stages import case_from_env, describe, run

case = case_from_env()
print(f"Window size on {describe(case)}\n")
print(f"{'window':>8} {'windows':>8} {'incident found':>15} {'incident start vs label':>24} "
      f"{'root cause rank':>16} {'run time':>9}")
for seconds in (60, 150, 300, 600, 1200):
    start = time.perf_counter()
    r = run(case, lambda c: c["feature_engineering"].update(window_size=seconds))
    took = time.perf_counter() - start
    incident, ev = r["plan"]["incident"], r["evaluation"]
    offset = ev.get("kpi_incident_offset_minutes")
    offset = f"{offset:+.1f} min" if offset is not None else ("no clock" if not case else "-")
    rank = f"{ev['root_cause_rank']} of {ev['pods_ranked']}" if ev.get("root_cause_rank") else "-"
    label = f"{seconds // 60} min" if seconds % 60 == 0 else f"{seconds / 60:.1f} min"
    print(f"{label:>8} {r['windows']:>8} {'yes' if incident.get('detected') else 'no':>15} {offset:>24} "
          f"{rank:>16} {took:>8.1f}s")
