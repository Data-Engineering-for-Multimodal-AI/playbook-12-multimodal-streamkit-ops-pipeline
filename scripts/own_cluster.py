"""Check a folder of your own cluster's metrics, then run the six stages on it.

    make check-data DIR=my_cluster    # check every file, write nothing
    make load DIR=my_cluster          # check, convert to the pipeline's format, run the pipeline

The folder holds CSV exports (from Prometheus, your APM, or a script):

    my_cluster/
      metrics.csv        timestamp, pod, metric, value     one row per sample; metric is one of
                         cpu_usage, memory_usage, rate_received_packets, rate_transmitted_packets,
                         rate_storage_iops, received_bandwidth, transmit_bandwidth (any subset)
      kpi.csv            timestamp, then error_rate (0 to 1) or latency_ms: what users see
      logs.csv           timestamp, pod, golden_signal, frequency    (optional) log counts per pod
      fault_label.json   {"root_cause_pod": "...", "failure_time": "2026-03-02T07:15:00Z"}  (optional)

Timestamps are unix seconds or ISO 8601 with a time zone (2026-03-02T07:15:00Z). The checks are
the things that break the pipeline or make its answer wrong: missing files or columns, files
that aren't UTF-8, timestamps that don't parse or have no time zone, metric names the pipeline
doesn't read (they would be ignored), values that aren't numbers, duplicate samples, an
error rate outside 0 to 1 or a latency of 0 or less, too short a recording for a baseline and
an incident (at least 1 hour, 12 five-minute windows), a KPI that doesn't overlap the metrics,
and a labelled root-cause pod that has no metrics. Every problem is reported with the file
and the reason; if there is any, nothing is written.

`make load` converts the folder like download_data.py converts a LEMMA-RCA case (30-second
means, a pod-by-time array per metric) into data/lemma-rca/own-<folder name>/, then runs
`python run_pipeline.py --case own-<folder name>`. The reports go to output/lemma-rca-own-<name>/.
`make clean` deletes both.
"""

import argparse
import csv
import json
import math
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

METRICS = ["cpu_usage", "memory_usage", "rate_received_packets", "rate_transmitted_packets",
           "rate_storage_iops", "received_bandwidth", "transmit_bandwidth"]
RESOLUTION = 30          # seconds, as download_data.py
MIN_SPAN = 3600          # 12 windows of 5 minutes
LABEL = "book_info"      # the key the pipeline's loader looks up (config label)


def parse_time(raw):
    """Unix seconds, or ISO 8601 with a time zone. Returns (seconds, problem)."""
    raw = (raw or "").strip()
    if not raw:
        return None, "empty timestamp"
    try:
        x = float(raw)
        if math.isfinite(x) and 9e8 < x < 5e9:
            return int(x), None
        return None, f"timestamp {raw!r} is not unix seconds (expected about 1.7e9)"
    except ValueError:
        pass
    import pandas as pd
    try:
        t = pd.Timestamp(raw)
    except ValueError:
        return None, f"timestamp {raw!r} doesn't parse"
    if t.tzinfo is None:
        return None, f"timestamp {raw!r} has no time zone (add Z for UTC)"
    return int(t.timestamp()), None


def number(raw):
    try:
        x = float(raw)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def read_csv(folder, name, required, problems, optional=False):
    path = folder / name
    if not path.exists():
        if not optional:
            problems.append(f"{name}: missing (needs columns {', '.join(required)})")
        return None
    raw = path.read_bytes()
    if raw.startswith(b"version https://git-lfs"):
        problems.append(f"{name}: Git LFS pointer, not the file (run git lfs pull)")
        return None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        problems.append(f"{name}: not UTF-8 text (byte {e.start})")
        return None
    reader = csv.DictReader(text.splitlines())
    missing = [c for c in required if c not in (reader.fieldnames or [])]
    if missing:
        problems.append(f"{name}: missing column(s) {', '.join(missing)}")
        return None
    rows = list(reader)
    if not rows:
        problems.append(f"{name}: no rows")
        return None
    return rows


def check(folder):
    """Returns (parsed data, [problems]). Parsed data is what convert() writes."""
    folder = Path(folder)
    if not folder.is_dir():
        return None, [f"{folder}: not a folder"]
    problems = []
    MAX = 5   # report at most this many problems of one kind per file, then a count

    def report(kind_counts, key, message):
        kind_counts[key] = kind_counts.get(key, 0) + 1
        if kind_counts[key] <= MAX:
            problems.append(message)

    # metrics.csv
    samples, seen, counts = {}, set(), {}
    rows = read_csv(folder, "metrics.csv", ["timestamp", "pod", "metric", "value"], problems)
    for line, row in enumerate(rows or [], start=2):
        where = f"metrics.csv line {line}"
        t, err = parse_time(row["timestamp"])
        if err:
            report(counts, "time", f"{where}: {err}")
            continue
        pod, metric = (row["pod"] or "").strip(), (row["metric"] or "").strip()
        if not pod:
            report(counts, "pod", f"{where}: empty pod")
            continue
        if metric not in METRICS:
            report(counts, "metric", f"{where}: metric {metric!r} is not one the pipeline reads "
                                     f"({', '.join(METRICS)})")
            continue
        value = number(row["value"])
        if value is None:
            report(counts, "value", f"{where}: value {row['value']!r} is not a number")
            continue
        if (t, pod, metric) in seen:
            report(counts, "dup", f"{where}: second sample for {pod} {metric} at the same timestamp")
            continue
        seen.add((t, pod, metric))
        samples.setdefault(metric, []).append((t, pod, value))
    for key, n in counts.items():
        if n > MAX:
            problems.append(f"metrics.csv: {n - MAX} more problem(s) like the ones above")

    times = [t for s in samples.values() for t, _, _ in s]
    if times and max(times) - min(times) < MIN_SPAN:
        problems.append(f"metrics.csv: covers {(max(times) - min(times)) / 60:.0f} minutes; the pipeline needs "
                        f"at least {MIN_SPAN // 60} (a baseline and an incident of 5-minute windows)")
    pods = {p for s in samples.values() for _, p, _ in s}

    # kpi.csv
    kpi, counts = [], {}
    rows = read_csv(folder, "kpi.csv", ["timestamp"], problems)
    sli = None
    if rows is not None:
        columns = rows[0].keys()
        sli = "error_rate" if "error_rate" in columns else "latency_ms" if "latency_ms" in columns else None
        if sli is None:
            problems.append("kpi.csv: needs an error_rate column (0 to 1) or a latency_ms column")
    for line, row in enumerate(rows or [], start=2) if sli else []:
        where = f"kpi.csv line {line}"
        t, err = parse_time(row["timestamp"])
        value = number(row[sli])
        if err:
            report(counts, "time", f"{where}: {err}")
        elif value is None:
            report(counts, "value", f"{where}: {sli} {row[sli]!r} is not a number")
        elif sli == "error_rate" and not 0 <= value <= 1:
            report(counts, "range", f"{where}: error_rate {row[sli]} is outside 0 to 1 (a share, not a percent)")
        elif sli == "latency_ms" and value <= 0:
            report(counts, "range", f"{where}: latency_ms {row[sli]} is 0 or less")
        else:
            kpi.append((t, value))
    for key, n in counts.items():
        if n > MAX:
            problems.append(f"kpi.csv: {n - MAX} more problem(s) like the ones above")
    if kpi and times and (max(t for t, _ in kpi) < min(times) or min(t for t, _ in kpi) > max(times)):
        problems.append("kpi.csv: its timestamps don't overlap metrics.csv (check the time zone)")

    # logs.csv (optional)
    logs, counts = [], {}
    rows = read_csv(folder, "logs.csv", ["timestamp", "pod", "golden_signal", "frequency"], problems, optional=True)
    for line, row in enumerate(rows or [], start=2):
        where = f"logs.csv line {line}"
        t, err = parse_time(row["timestamp"])
        g, f = number(row["golden_signal"]), number(row["frequency"])
        if err:
            report(counts, "time", f"{where}: {err}")
        elif g is None or f is None:
            report(counts, "value", f"{where}: golden_signal and frequency must be numbers")
        else:
            logs.append((t, (row["pod"] or "").strip(), g, f))
    for key, n in counts.items():
        if n > MAX:
            problems.append(f"logs.csv: {n - MAX} more problem(s) like the ones above")

    # fault_label.json (optional)
    label = {}
    path = folder / "fault_label.json"
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("not a JSON object")
        except (ValueError, UnicodeDecodeError) as e:
            problems.append(f"fault_label.json: can't read it ({e.__class__.__name__})")
            raw = {}
        pod = raw.get("root_cause_pod")
        if pod and pods and pod not in pods:
            problems.append(f"fault_label.json: root_cause_pod {pod!r} has no rows in metrics.csv")
        if raw.get("failure_time"):
            t, err = parse_time(str(raw["failure_time"]))
            if err:
                problems.append(f"fault_label.json: failure_time: {err}")
            else:
                label["failure_timestamp"] = t
        if pod:
            label["root_cause_pod"] = pod

    data = {"metrics": samples, "kpi": kpi, "sli": sli, "logs": logs, "label": label, "pods": sorted(pods)}
    return data, problems


def convert(data, out):
    """Write the pipeline's format (as download_data.py does) into `out`."""
    import numpy as np
    import pandas as pd

    from pipeline.safe_npy import save_npy
    out.mkdir(parents=True, exist_ok=True)

    def grid(rows, columns):
        df = pd.DataFrame(rows, columns=["t", "pod", *columns])
        df["t"] = (df["t"] // RESOLUTION) * RESOLUTION
        return df.groupby(["t", "pod"])[columns].mean()

    for metric, rows in data["metrics"].items():
        wide = grid(rows, ["value"])["value"].unstack("pod").sort_index()
        save_npy(out / f"pod_level_data_{metric}.npy",
                 {LABEL: {"Pod_Name": list(wide.columns), "Sequence": wide.to_numpy(np.float32),
                          "time": wide.index.to_numpy(np.int64), "KPI_Feature": "kpi"}})
    if data["logs"]:
        logs = grid(data["logs"], ["golden_signal", "frequency"])
        for kind in ("golden_signal", "frequency"):
            wide = logs[kind].unstack("pod").sort_index()
            save_npy(out / f"pod_level_log_{kind}.npy",
                     {LABEL: {"Node_Name": list(wide.columns), "Sequence": wide.to_numpy(np.float32),
                              "time": wide.index.to_numpy(np.int64), "KPI_Feature": kind}})
    kpi = pd.DataFrame(data["kpi"], columns=["timestamp", data["sli"]])
    kpi["timestamp"] = (kpi["timestamp"] // RESOLUTION) * RESOLUTION
    kpi = kpi.groupby("timestamp").mean()
    if data["sli"] == "error_rate":     # the same KPI as download_data.convert_kpi: higher is better
        kpi.insert(0, "kpi", 1 - kpi["error_rate"])
    else:
        kpi.insert(0, "kpi", (kpi["latency_ms"].median() / kpi["latency_ms"]).clip(upper=1.0))
    kpi.reset_index().to_csv(out / "kpi.csv", index=False)
    label = {"case": out.name, "source": "your own data (scripts/own_cluster.py)",
             "sli": data["sli"], "kpi_rule": "error_rate" if data["sli"] == "error_rate" else "relative"}
    if data["label"].get("root_cause_pod"):
        label["root_cause_pod"] = data["label"]["root_cause_pod"]
    if "failure_timestamp" in data["label"]:
        t = data["label"]["failure_timestamp"]
        label["failure_timestamp"] = t
        label["failure_time_utc"] = pd.Timestamp(t, unit="s", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(out / "fault_labels.json", "w") as f:
        json.dump(label, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Check a folder of your own cluster data and run the pipeline on it.")
    parser.add_argument("--dir", required=True)
    parser.add_argument("--check-only", action="store_true", help="check the files, write nothing")
    args = parser.parse_args()
    folder = Path(args.dir).resolve()

    data, problems = check(folder)
    if problems:
        print(f"{len(problems)} problem(s) in {args.dir}; nothing was written:")
        for p in problems:
            print(f"  {p}")
        sys.exit(1)
    times = [t for s in data["metrics"].values() for t, _, _ in s]
    print(f"{args.dir}: {len(data['pods'])} pods, {len(data['metrics'])} metrics, "
          f"{(max(times) - min(times)) / 3600:.1f} hours, KPI from {data['sli']}"
          f"{', logs' if data['logs'] else ', no logs'}"
          f"{', a fault label' if data['label'] else ', no fault label'}. All checks passed.")
    if args.check_only:
        return

    case = f"own-{folder.name}"
    out = ROOT / "data" / "lemma-rca" / case
    convert(data, out)
    print(f"Converted to {out.relative_to(ROOT)}/. Running the pipeline: python run_pipeline.py --case {case}\n", flush=True)
    sys.exit(subprocess.run([sys.executable, str(ROOT / "run_pipeline.py"), "--case", case], cwd=ROOT).returncode)


if __name__ == "__main__":
    main()
