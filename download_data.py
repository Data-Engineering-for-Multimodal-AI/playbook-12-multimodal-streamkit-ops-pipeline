#!/usr/bin/env python3
"""
Download LEMMA-RCA dataset from HuggingFace.

Downloads one case of the Cloud Computing Preprocessed dataset and converts it into the format
the pipeline reads, in data/lemma-rca/{case}/:

    pod_level_data_{metric}.npy      7 pod metrics, 30-second means, with a time axis
    pod_level_log_golden_signal.npy  log signals (when the case has logs)
    pod_level_log_frequency.npy
    kpi.csv                          the service KPI: requests, error rate, latency per 30 s
    fault_labels.json                root-cause pod and failure time, from the case's README slides
    SOURCE.json                      where it came from (revision, SHA-256)

What is downloaded: the case's metrics zip (100-400 MB). From the log zip (up to 2.3 GB) only the two
small log-signal files are read, with range requests. The dataset's .npy files are pickles; they are
read with a loader that accepts numbers, text and numpy arrays only (pipeline/safe_npy.py).

Usage:
    python download_data.py                  # Download case 20240115 (default)
    python download_data.py --case 20240207  # Download a specific case
    python download_data.py --list
"""

import argparse
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from huggingface_hub import HfApi, HfFileSystem, hf_hub_download

from pipeline.safe_npy import load_npy, save_npy

REPO_ID = "Lemma-RCA-NEC/Cloud_Computing_Preprocessed"
REVISION = "03f82a2c4b16afe09e9315def9f5d6990427000a"   # pinned; the dataset is CC BY-NC 4.0
# What each case's README slides say, where the slides can't be parsed reliably:
# the time zone of the failure time, the SLI that shows users being hurt, and the root cause.
CASES = {
    "20231207": {"tz": "Asia/Tokyo", "sli": "latency_ms",
                 "root_cause_pod": "productpage-v1 (one of its two replicas; the slides don't say which)",
                 "root_cause_match": r"^productpage-v1-",
                 "root_cause": "a latent bug raises the CPU load of one productpage-v1 replica"},
    "20231221": {"tz": "Asia/Tokyo", "sli": "latency_ms",
                 "sli_note": "is_error is 1 for every request in this case's KPI file, so latency is used",
                 "root_cause_pod": "ratings-aggregated (robot-shop's ratings pod, which moved to productpage-v1's node)",
                 "root_cause_match": r"^ratings-aggregated$",
                 "root_cause": "robot-shop's ratings pod moved to productpage-v1's node and took its CPU (noisy neighbour)"},
    "20240115": {"tz": "UTC", "sli": "error_rate"},
    "20240124": {"tz": "UTC", "sli": "latency_ms",
                 "root_cause_pod": "i-078923fb30cac1ede (EC2 instance ip-10-1-100-109)",
                 "root_cause_match": r"^i-078923fb30cac1ede$",
                 "root_cause": "an infinite loop in one API occupies one of the instance's four CPUs"},
    "20240207": {"tz": "UTC", "sli": "error_rate"},
    "20240215": {"tz": "UTC", "sli": "cost_per_hour",
                 "root_cause_pod": "details-v1", "root_cause_match": r"^details-v1-",
                 "root_cause": "a cryptojacking coin miner runs in the details-v1 pod"},
}
VALID_CASES = list(CASES)
RESOLUTION = 30   # seconds; the log signals are already at 30 s
LABEL = "book_info"
ROOT = Path(__file__).resolve().parent


def _bin(times, values: np.ndarray) -> pd.DataFrame:
    """Mean per 30-second bin; index = bin start (unix seconds)"""
    t = np.asarray(times, dtype=np.int64)
    df = pd.DataFrame(values.astype(np.float32))
    return df.groupby((t // RESOLUTION) * RESOLUTION).mean()


def convert_metric(raw: bytes) -> dict:
    data = load_npy(raw)
    entry = data[LABEL] if LABEL in data else next(iter(data.values()))
    pods = list(entry['Pod_Name'])
    sequence = np.asarray(entry['Sequence'])
    # The last column is the case's KPI (latency or error rate), not a pod
    sequence = sequence[:, :len(pods)]
    binned = _bin(entry['time'], sequence)
    return {LABEL: {'Pod_Name': pods, 'Sequence': binned.to_numpy(np.float32),
                    'time': binned.index.to_numpy(np.int64), 'KPI_Feature': 'kpi'}}


def convert_log(raw: bytes) -> dict:
    data = load_npy(raw)
    entry = data if 'Sequence' in data else next(iter(data.values()))
    sequence = np.asarray(entry['Sequence'], dtype=np.float32)
    if sequence.ndim == 3:            # (pods, time, 1) -> (time, pods)
        sequence = sequence[:, :, 0].T
    return {LABEL: {'Node_Name': list(entry['Node_Name']), 'Sequence': sequence,
                    'time': np.asarray(entry['time'], dtype=np.int64), 'KPI_Feature': str(entry.get('KPI_Feature'))}}


KPI_COLUMNS = {'is_error': 'error_rate', 'Latency': 'latency_ms', 'Total cost per hour(USD)': 'cost_per_hour'}


def convert_kpi(z: zipfile.ZipFile, names: list, sli: str = 'error_rate') -> Optional[pd.DataFrame]:
    """Per-request JMeter results (or the cost series) -> one row per 30 s.
    Cases store them in one kpi*.csv or in two (error rate, latency).

    kpi is a health score, higher is better:
      error-rate SLI:        1 - error rate (the share of requests served)
      latency or cost SLI:   usual value / value (1.0 normal, 0.5 = twice the usual), where usual is
                             the median over the whole recording
    """
    parts = []
    for name in names:
        with z.open(name) as f:
            header = pd.read_csv(f, nrows=0).columns
        columns = ['timeStamp'] + [c for c in KPI_COLUMNS if c in header]
        with z.open(name) as f:
            df = pd.read_csv(f, usecols=columns)
        bins = (df['timeStamp'].astype(np.int64) // RESOLUTION) * RESOLUTION
        grouped = df.groupby(bins)
        part = pd.DataFrame(index=grouped.size().index)
        if 'is_error' in columns:
            part['requests'] = grouped.size()
        for column, out_name in KPI_COLUMNS.items():
            if column in columns:
                part[out_name] = grouped[column].mean()
        parts.append(part)
    if not parts:
        return None
    out = pd.concat(parts, axis=1).sort_index()
    if sli not in out:
        return None
    out.index.name = 'timestamp'
    if sli == 'error_rate':
        out.insert(0, 'kpi', 1 - out['error_rate'])
    else:
        usual = out[sli].median()
        out.insert(0, 'kpi', (usual / out[sli]).clip(upper=1.0))
    return out.reset_index()


def fault_labels_from_slides(pptx_bytes: bytes, case: str, tz: str = 'UTC') -> dict:
    """Root-cause pod and failure time from the case's README slides (no other label file exists).
    tz: the time zone of the failure time (two cases give Japan time without saying so)"""
    text = []
    with zipfile.ZipFile(io.BytesIO(pptx_bytes)) as pptx:
        slides = sorted((n for n in pptx.namelist() if re.match(r'ppt/slides/slide\d+\.xml$', n)),
                        key=lambda n: int(re.search(r'(\d+)', n.rsplit('/', 1)[1]).group(1)))
        for name in slides:
            text += re.findall(r'<a:t>([^<]*)</a:t>', pptx.read(name).decode('utf-8'))
    text = re.sub(r'\s+', ' ', ' '.join(text))
    pod = re.search(r'Root cause\s*pod[^:]{0,40}:\s*([a-z0-9][a-z0-9.-]+[a-z0-9])', text, re.I)
    failure = re.search(r'Failure time.{0,80}?(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)Z?', text)
    cause = re.search(r'Root cause\s*:\s*([^.]{5,200})\.', text)
    label = {'case': case, 'source': 'README slides in the case metrics zip',
             'root_cause_pod': pod.group(1) if pod else None,
             'root_cause': cause.group(1).strip() if cause else None,
             'failure_time_utc': None}
    if failure:
        stamp = pd.Timestamp(failure.group(1).replace(' ', 'T'), tz=tz).tz_convert('UTC')
        label['failure_time_utc'] = stamp.strftime('%Y-%m-%dT%H:%M:%SZ')
        label['failure_timestamp'] = int(stamp.timestamp())
    return label


def case_labels(pptx_bytes: Optional[bytes], case: str) -> dict:
    """The slide label, completed from CASES; kpi_rule says how the pipeline reads the KPI"""
    known = CASES[case]
    label = fault_labels_from_slides(pptx_bytes, case, known['tz']) if pptx_bytes else {'case': case}
    for key in ('root_cause_pod', 'root_cause', 'root_cause_match', 'sli_note'):
        if key in known:
            label[key] = known[key]
    if label.get('root_cause_pod') and 'root_cause_match' not in label:
        label['root_cause_match'] = '^' + re.escape(label['root_cause_pod']) + '$'
    label['sli'] = known['sli']
    label['kpi_rule'] = 'error_rate' if known['sli'] == 'error_rate' else 'relative'
    return label


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def download_and_extract(
    case: str,
    repo_id: str = REPO_ID,
    output_dir: Optional[str] = None,
) -> bool:
    """
    Download one LEMMA-RCA case and convert it for the pipeline.

    Returns:
        True if successful, False otherwise
    """
    if case not in VALID_CASES:
        print(f"Error: Invalid case '{case}'")
        print(f"Valid cases: {', '.join(VALID_CASES)}")
        return False

    out = Path(output_dir) if output_dir else ROOT / "data" / "lemma-rca" / case
    out.mkdir(parents=True, exist_ok=True)

    print(f"Downloading LEMMA-RCA dataset for case {case}...")
    print(f"Repository: {repo_id} (revision {REVISION[:8]})")
    print(f"Output directory: {out}")

    info = {p.path: p for p in HfApi().get_paths_info(
        repo_id, [f"Metrics Data/{case}.zip", f"Log Data/{case}.zip"], repo_type="dataset", revision=REVISION)}
    metrics_name = f"Metrics Data/{case}.zip"
    if metrics_name not in info:
        print(f"Error: {metrics_name} not found in the dataset")
        return False

    print(f"\nDownloading {metrics_name} ({info[metrics_name].size / 1e6:.0f} MB)...")
    metrics_zip = hf_hub_download(repo_id, metrics_name, repo_type="dataset", revision=REVISION)
    if sha256(metrics_zip) != info[metrics_name].lfs.sha256:
        print("Error: SHA-256 mismatch: the download is not the pinned file")
        return False
    print("  SHA-256 verified")

    with zipfile.ZipFile(metrics_zip) as z:
        names = z.namelist()
        print("\nConverting metrics (30-second means)...")
        # Pod metrics differ between cases. Some cases store them once per KPI folder (latency/,
        # error_rate/); the pod columns are the same, so the first folder is used.
        found = {}
        for n in sorted(names):
            m = re.search(r'/pod_level_data_([a-z0-9_]+)\.npy$', n)
            if m:
                found.setdefault(m.group(1), n)
        for metric, member in found.items():
            data = convert_metric(z.read(member))
            save_npy(out / f"pod_level_data_{metric}.npy", data)
            seq = data[LABEL]['Sequence']
            print(f"  ✓ {metric}: {seq.shape[0]} time steps × {seq.shape[1]} pods")

        sli = CASES[case]['sli']
        kpi = convert_kpi(z, [n for n in names if re.search(r'/kpi[^/]*\.csv$', n, re.I)], sli)
        if kpi is not None:
            kpi.to_csv(out / "kpi.csv", index=False)
            print(f"\n  ✓ KPI: {len(kpi)} time steps; the SLI is {sli}")
        else:
            print(f"\n  ✗ KPI: no {sli} in this case")

        slides = [n for n in names if n.endswith('.pptx')]
        labels = case_labels(z.read(slides[0]) if slides else None, case)
    with open(out / "fault_labels.json", 'w') as f:
        json.dump(labels, f, indent=2)
    print(f"  ✓ Fault label: root cause {labels.get('root_cause_pod')}, failure at {labels.get('failure_time_utc')}")

    log_name = f"Log Data/{case}.zip"
    if log_name in info:
        print(f"\nReading the log signals from {log_name} ({info[log_name].size / 1e9:.2f} GB; range requests, not a full download)...")
        fs = HfFileSystem()
        with fs.open(f"datasets/{repo_id}@{REVISION}/{log_name}", "rb") as f, zipfile.ZipFile(f) as z:
            for kind in ["golden_signal", "frequency"]:
                member = next((n for n in z.namelist() if n.endswith(f"pod_level_log_{kind}.npy")), None)
                if member is None:
                    print(f"  ✗ {kind}: not in this case")
                    continue
                data = convert_log(z.read(member))
                save_npy(out / f"pod_level_log_{kind}.npy", data)
                seq = data[LABEL]['Sequence']
                print(f"  ✓ {kind}: {seq.shape[0]} time steps × {seq.shape[1]} pods")
    else:
        print(f"\nNo log zip for case {case}: the pipeline will use metrics and KPI only")

    with open(out / "SOURCE.json", 'w') as f:
        json.dump({'repository': f"https://huggingface.co/datasets/{repo_id}", 'revision': REVISION,
                   'license': 'CC BY-NC 4.0', 'metrics_zip': metrics_name,
                   'metrics_zip_sha256': info[metrics_name].lfs.sha256,
                   'log_zip': log_name if log_name in info else None,
                   'metrics': sorted(found),
                   'resolution_seconds': RESOLUTION}, f, indent=2)

    size = sum(p.stat().st_size for p in out.iterdir()) / 1e6
    print(f"\nDataset successfully downloaded and converted to {out} ({size:.0f} MB)")
    print(f"Next: python run_pipeline.py --case {case}")
    return True


def main():
    """Command-line interface for downloading LEMMA-RCA dataset."""
    parser = argparse.ArgumentParser(
        description="Download LEMMA-RCA dataset from HuggingFace"
    )
    parser.add_argument(
        "--case",
        type=str,
        default="20240115",
        help=f"Case ID to download (default: 20240115). "
             f"Valid: {', '.join(VALID_CASES)}",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: data/lemma-rca/{case}/)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available cases",
    )

    args = parser.parse_args()

    if args.list:
        print("Valid cases:", ", ".join(VALID_CASES))
        return 0

    success = download_and_extract(
        case=args.case,
        output_dir=args.output_dir,
    )

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
