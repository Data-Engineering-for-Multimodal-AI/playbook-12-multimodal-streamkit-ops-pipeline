# StreamKit Ops Playbook

**Chapter 12 playbook** from *Data Engineering for Multimodal AI* (O'Reilly, 2026), pages 496–500 (Early Release page numbers; they may differ in the final print).
Book: https://oreil.ly/data-engineering-multimodal

> Want the code exactly as printed? Use the `first-edition` tag. This branch is the 2026 maintenance update; see [Differences from the printed book](#differences-from-the-printed-book).

## What you'll build

A six-stage multimodal pipeline for IT-operations root cause analysis (RCA). It runs on the LEMMA-RCA cloud dataset: a Kubernetes cluster of about 260 pods, with injected failures.

1. **Ingest:** load the pod metrics (CPU, memory, network, storage), the log signals, the service KPI and the fault label.
2. **Fuse:** align metrics and logs by pod and 5-minute time window into one feature table.
3. **Plan:** find when users started being hurt (from the KPI), compare every pod with its own normal before that, rank the pods, and recommend actions. The rules are built in, or an LLM can be used (optional).
4. **Check:** apply the guardrails: allowed actions, confidence gates, per-action policies, a restart limit and a rate limit.
5. **Act:** simulate the approved actions; nothing touches a cluster.
6. **Observe:** write a JSON report and a text dashboard. They include how the run scores against the case's fault label: where the real root cause landed in the ranking, and how close the KPI incident is to the labelled failure time.

It runs on two kinds of data:

| | Bundled synthetic sample (default) | Real LEMMA-RCA cases (downloaded) |
|---|---|---|
| Where | `data/20240115/`, in the repository | `data/lemma-rca/<case>/`, made by `download_data.py` |
| Size | 8 pods, 5,000 steps, 3 MB | about 260 pods, 45 hours at 30-second resolution, 37 MB per case (a ~200 MB download) |
| What it shows | The pipeline end to end: the six stages take a tenth of a second (the first run after installing takes about 15 s while Python loads the libraries) | What RCA is like on a real cluster: a few seconds per case |

## Quick start

You need Python 3.12 or newer and about 150 MB of disk space for the environment. Add about 250 MB per LEMMA-RCA case (the download cache plus the converted files).

```bash
# Clone the repository
git clone https://github.com/Data-Engineering-for-Multimodal-AI/playbook-12-multimodal-streamkit-ops-pipeline.git
cd playbook-12-multimodal-streamkit-ops-pipeline

# Create and activate a virtual environment, then install dependencies
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

With [uv](https://docs.astral.sh/uv/): `uv sync`, then prefix commands with `uv run`. The Makefile has shortcuts: `make run`, `make run-lemma`, `make run-20240207`, `make smoke`.

### 1. Run it on the bundled sample

```bash
python run_pipeline.py
```

### 2. Download a real LEMMA-RCA case and run it

```bash
python download_data.py                    # case 20240115 (default)
python run_pipeline.py --case 20240115
```

What the downloader does:

- **Metrics.** It downloads the case's metrics zip (193 MB for 20240115) at a pinned dataset revision and checks its SHA-256.
- **Logs.** From the case's log zip (2.3 GB) it reads only the two log-signal files, with range requests, so the whole zip isn't downloaded.
- **Conversion.** It converts everything into the pipeline's format at 30-second resolution, in `data/lemma-rca/20240115/` (37 MB, about 10 seconds).
- **Fault label.** The case's README slides are the only place the label is given, so the downloader reads the root-cause pod and the failure time from them into `fault_labels.json`. Where the slides can't be read reliably (the time zone, the SLI, root causes named as a deployment or an EC2 instance), `CASES` in `download_data.py` records what they say.
- **Safe loading.** The dataset's `.npy` files are Python pickles, which can run code when loaded. They are read with a loader that accepts numbers, text and NumPy arrays only (`pipeline/safe_npy.py`).

Without `--case`, the pipeline runs on the bundled sample. With `--case`, it runs on that downloaded case, and the reports go to `output/lemma-rca-<case>/`. (The book runs `python run_pipeline.py` right after the download; that runs the sample, and says how to run the downloaded case.)

### 3. The other five cases

All six Cloud Computing cases run the same way (`python download_data.py --list`):

```bash
python download_data.py --case 20240215
python run_pipeline.py --case 20240215
```

The cases differ more than the book suggests: each has its own pod metrics, and the signal that shows users being hurt (the SLI) is the error rate in two cases, latency in three, and the cluster's hourly cost in one. The pipeline turns the SLI into a KPI where higher is better: the share of requests served for an error rate, and the usual value divided by the current one for latency and cost (the usual value is the median over the recording). An incident is an error rate above 1% (the alert rule in the case slides) or a latency or cost above 1.5 times the usual value.

Results on 2026-10-27 (macOS 26.5.1, Python 3.13.16), rule-based analysis:

| Case | Fault (from the slides) | SLI | Pods | KPI incident start vs the labelled failure | Root cause in the pod ranking |
|---|---|---|---|---|---|
| 20231207 | A latent bug raises the CPU load of one `productpage-v1` replica | Latency | 196 | 136.9 min later (latency rose slowly) | 5th (`productpage-v1-94d68db49-j7t55`); actions recommended on it |
| 20231221 | Robot-shop's `ratings` pod moves to `productpage-v1`'s node and takes its CPU | Latency | 159 | 2.1 min earlier | 21st (`ratings-aggregated`) |
| 20240115 | A malware pod infects about 30 others, which flood the web server | Error rate | 257 | 1.6 min earlier | 80th (see below) |
| 20240124 | An infinite loop occupies one of four CPUs on an EC2 instance | Latency | 15 instances | None found: 5-minute latency never reached 1.5 times the usual value | 12th of 15 (the baseline is the first 70% of the recording, which includes the failure) |
| 20240207 | A `git push` deploys wrong resource limits (not a pod) | Error rate | 264 | 3.7 min earlier | Not scored |
| 20240215 | A coin miner runs in the `details-v1` pod | Hourly cost | 59 | 1.5 min earlier | 16th (`details-v1-79548dfc8f-b45tm`) |

The KPI finds the incident within four minutes of the label in four cases. Finding the root cause by anomaly counts mostly doesn't work: the pods that suffer (victims, bots, autoscaled replicas) deviate more than the cause. Case 20231221's root cause is taken to be the dataset's `ratings-aggregated` series: robot-shop's ratings pod changed name when it moved, and this is the only ratings series outside book-info's `ratings-v1` and `ratings-v2`. Case 20231221's `is_error` column is 1 for every request, so its latency is used. Case 20240207 has no logs; 20240124 has no log-frequency file.

### 4. LLM analysis (optional)

For analysis with any OpenAI-compatible LLM, set your API key and base URL:

```bash
export LLM_API_KEY="your-api-key"
export LLM_BASE_URL="https://api.your-provider.com/v1"  # optional, defaults to OpenAI
export LLM_MODEL="gpt-4o"  # optional, defaults to gpt-4o
python run_pipeline.py
```

The LLM gets each top pod's 50 strongest deviations and returns a root cause, an action and a confidence. If a call fails, that pod falls back to the rule-based analysis. This path was not run for this update; all output below is rule-based. The book's `export ANTHROPIC_API_KEY=...` (page 499) is not read by the code; use the three variables above with the provider's OpenAI-compatible endpoint. They are listed in `.env.example`.

### Individual stages

```python
from pipeline.ingest import load_data
from pipeline.fuse import fuse_modalities
from pipeline.plan import plan_analysis
from pipeline.check import check_actions
from pipeline.act import execute_actions
from pipeline.observe import generate_report

data_dict = load_data('config/pipeline_config.yaml')          # or load_data(..., case='20240115')
fused_df = fuse_modalities(data_dict)
plan_result = plan_analysis(fused_df, data_dict['config'])
approved, escalated, rejected = check_actions(plan_result, data_dict['config'])
execution_log = execute_actions(approved, escalated, rejected)
report = generate_report(execution_log, plan_result, data_dict['config'])
```

Each stage also runs on its own from the repository folder, for example `python -m pipeline.plan`.

## Tested on

| Date | OS | Python | What |
|---|---|---|---|
| 2026-10-26 | macOS 26.5.1 (Apple M3) | 3.12.15 and 3.13.16 | `make smoke` (10 tests); the sample; LEMMA-RCA cases 20240115 and 20240207 (output below) |
| 2026-10-27 | macOS 26.5.1 (Apple M3) | 3.13.16 | All six LEMMA-RCA cases (table above); `make smoke` |
| 2026-10-26 | Ubuntu (GitHub Actions) | 3.12, 3.13 | `make smoke`, then after `pip install -r requirements.txt`: the sample, and both cases downloaded and run |

Versions are pinned in `uv.lock` and `requirements.txt` (NumPy 2.5, pandas 3.1, huggingface_hub 2.3, openai 3.39).

## Differences from the printed book

The printed commands still work: `pip install -r requirements.txt`, `python download_data.py --case 20240115`, `python run_pipeline.py`, and the stage functions in the snippet above. The left column is the first edition: the code at the `first-edition` tag, which the book describes.

| Area | First edition | Now |
|---|---|---|
| Folder | The book's `cd streamkit-ops-playbook` (page 499) | `cd playbook-12-multimodal-streamkit-ops-pipeline` |
| `python run_pipeline.py` after the download (page 499) | Ran the synthetic sample | Still runs the sample, and prints the `--case` command for the downloaded case |
| LLM | The book's `ANTHROPIC_API_KEY` (page 499) was never read; the code read `LLM_API_KEY` | Unchanged: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` |
| Other cases (page 499) | Could not run | All six run (table above) |
| Sample data | Presented as LEMMA-RCA output | Labelled as what it is: synthetic data with made-up pod names (see [Data and licenses](#data-and-licenses)). Kept unchanged as the default |
| Real data | `download_data.py` unzipped into a layout the pipeline doesn't read, so every run used the synthetic files | Real cases are converted into the pipeline's format and run with `--case` |
| Baseline | "The first 70% of the data" was the first 70% of rows, which are sorted by pod name. So the baseline was the first 6 pods alphabetically, and the 3 "affected pods" were simply the last 3 alphabetically | Split by time, the same for every pod. The baseline is each pod's normal (KPI fine) windows before the incident; the analysis covers the incident |
| `--case` | Changed the label in the report but not the data that was loaded | Loads that case |
| Windows | Neighbouring windows shared a sample; the configured window size and aggregations were ignored | Windows on the time axis, from the config; each sample in exactly one window |
| Pods | Only pods present in every metric were kept. On real data that drops the root-cause pod: storage IOPS covers 6 of 257 pods | All pods, with the features each one has |
| Guardrails | `action_policies` and the restart limit in the config were never applied, and the rate limit only counted earlier runs | Per-action minimum confidence, actions that always need a human (for example `scale_down`), at most 5 restarts and 20 actions per minute |
| LLM failure | A failed call dropped the pod from the analysis | Falls back to the rule-based analysis |
| Act | Unseeded; the printed duration differed from the logged end time, and a `scale_up` could end with fewer replicas | Seeded and consistent |
| Fault label and KPI | Loaded but never used | The KPI finds the incident; the report scores the run against the label |
| Safety | `np.load(allow_pickle=True)` on downloaded files | A loader that refuses anything but data |
| Install | Unpinned; scikit-learn and requests were never imported; Python 3.9 | Pinned and locked, Python 3.12+; unused packages removed |

The pipeline is still the book's: the same six stages, z-score anomalies (2 σ), rule-based recommendations with the same confidence blend, and the same thresholds. Also new: `pipeline/safe_npy.py`, `pipeline/evaluate.py` and an `incident` section in the config.

## Data and licenses

| Data | Source | License |
|---|---|---|
| `data/20240115/` (bundled) | Synthetic, committed with the first edition (how it was generated is not recorded). It is not LEMMA-RCA data: the values are seeded random numbers, 7 of the 8 pod names are made up, and the 8th pod (the "malware" pod) borrows its name and fault label from LEMMA-RCA case 20240115. Its `fault_labels.json` gives the real case's failure time, which the sample has no clock for, and its `inject_time` text doesn't match its own `inject_timestamp` (2024-01-14 07:26:39 UTC). The files are kept as committed | MIT, like the code |
| LEMMA-RCA cases (downloaded) | [Lemma-RCA-NEC/Cloud_Computing_Preprocessed](https://huggingface.co/datasets/Lemma-RCA-NEC/Cloud_Computing_Preprocessed), revision `03f82a2c`. L. Zheng, Z. Chen, D. Wang, C. Deng, R. Matsuoka, H. Chen, "LEMMA-RCA: A Large Multi-modal Multi-domain Dataset for Root Cause Analysis", [arXiv:2406.05375](https://arxiv.org/abs/2406.05375) | CC BY-NC 4.0 (non-commercial), per the dataset card at that revision; the book (page 497) says CC BY-ND 4.0. Not redistributed here; `download_data.py` fetches it |

## Expected output

### The bundled sample

From `python run_pipeline.py` on 2026-10-26, macOS 26.5.1, Python 3.13.16. The timestamps are replaced by `<your-run-timestamp>`. This is the output of this version; it may differ from the output printed in the book, and that's okay.

#### Stage 1: Ingest

```
======================================================================
STAGE 1: INGEST
======================================================================

Loading configuration...
  Case: 20240115
  Source: synthetic sample (bundled)
  Service: book_info
  Data path: data/20240115

Loading metrics (7 files)...
  ✓ cpu_usage: shape (5000, 8)
  ✓ memory_usage: shape (5000, 8)
  ✓ rate_received_packets: shape (5000, 8)
  ✓ rate_transmitted_packets: shape (5000, 8)
  ✓ rate_storage_iops: shape (5000, 8)
  ✓ received_bandwidth: shape (5000, 8)
  ✓ transmit_bandwidth: shape (5000, 8)

Loading logs...
  ✓ Golden signal: shape (5000, 8)
  ✓ Frequency logs: shape (5000, 8)

Loading KPI...
  ✓ KPI: 5000 rows, 2 columns
  ✓ Fault label: root cause scenario10-malware-deployment-57db4df9f4-p8h7h

Validating consistency...
  ✓ All metrics have consistent pod names and time spans

──────────────────────────────────────────────────────────────────────
INGESTION SUMMARY
──────────────────────────────────────────────────────────────────────
Metrics loaded:     7
Pods:               8
Timestamps:         5000
Consistency:        ✓ Valid
Golden logs:        ✓ Available
Frequency logs:     ✓ Available
KPI data:           ✓ Available
Fault label:        ✓ Available
```

#### Stage 2: Fuse

5,000 steps in 300-step windows make 16 full windows and a final partial one of 200 steps. A partial window is kept when it's at least half a window long.

```
======================================================================
STAGE 2: FUSE
======================================================================

Common pods across all modalities: 8
Pods with metrics: 8
Time span: 5000 seconds
Time windows created: 17 windows of 300 s

──────────────────────────────────────────────────────────────────────
FUSION SUMMARY
──────────────────────────────────────────────────────────────────────
Pods fused:         8
Windows per pod:    17
Total rows:         136
Total columns:      67
Empty feature cells: 0.0% (metrics a pod doesn't report)
Feature groups:
  - Metrics: 49
  - Golden logs: 7
  - Frequency logs: 7
```

#### Stage 3: Plan

The KPI (a health score in the sample) falls from 0.95 to 0.60 at step 3600. Each pod's baseline is its 12 windows before that point. The malware pod stands out with 315 anomalies; every other pod has a few (18 to 26 for the top 4 shown, which are false positives).

```
======================================================================
STAGE 3: PLAN
======================================================================

Looking for the incident in the KPI...
  ✓ 1 period(s) with the KPI below 0.8; analysing the largest:
    step 3600 to step 4800 (5 windows; KPI 0.950 before, 0.598 during)

Computing baselines per pod from 12 of 17 windows (normal windows before the incident)...
  ✓ Baseline stats computed for 63 features × 8 pods

Detecting anomalies in 5 windows...
  ✓ 446 anomalies detected

  Affected pods: 8
       315  scenario10-malware-deployment-57db4df9f4-p8h7h
        26  db-service-ghi789
        22  frontend-v1-abc123
        19  gateway-stu901
        18  worker-pqr678

Generating analyses and recommendations (top 8 pods)...
  → scenario10-malware-deployment-57db4df9f4-p8h7h: Using rule-based analysis... ✓
  → db-service-ghi789: Using rule-based analysis... ✓
  → frontend-v1-abc123: Using rule-based analysis... ✓
  → gateway-stu901: Using rule-based analysis... ✓
  → worker-pqr678: Using rule-based analysis... ✓
  → cache-layer-jkl012: Using rule-based analysis... ✓
  → queue-service-mno345: Using rule-based analysis... ✓
  → api-server-def456: Using rule-based analysis... ✓

──────────────────────────────────────────────────────────────────────
PLANNING SUMMARY
──────────────────────────────────────────────────────────────────────
Anomalies detected:     446
Affected pods:          8
Analyses generated:     8
Avg anomalies/pod:      55.8
LLM analysis:           ✗ Disabled
```

#### Stage 4: Check (guardrails)

```
======================================================================
STAGE 4: CHECK (GUARDRAILS)
======================================================================

Validating 8 analyses against guardrails...
  → scenario10-malware-deployment-57db4df9f4-p8h7h
      Rec 1: ✓ Approved (0.89 confidence)
      Rec 2: ✓ Approved (0.87 confidence)
      Rec 3: ✓ Approved (0.85 confidence)
      Rec 4: ⚠ Escalated: Confidence 0.83 requires escalation
  → db-service-ghi789
      Rec 1: ⚠ Escalated: Confidence 0.77 requires escalation
      Rec 2: ⚠ Escalated: Confidence 0.75 requires escalation
      Rec 3: ⚠ Escalated: Confidence 0.73 requires escalation
      Rec 4: ⚠ Escalated: Confidence 0.71 requires escalation
  → frontend-v1-abc123
      Rec 1: ⚠ Escalated: Confidence 0.71 requires escalation
      Rec 2: ⚠ Escalated: Confidence 0.69 requires escalation
      Rec 3: ⚠ Escalated: Confidence 0.73 requires escalation
  → gateway-stu901
      Rec 1: ⚠ Escalated: Confidence 0.83 requires escalation
      Rec 2: ⚠ Escalated: Confidence 0.81 requires escalation
      Rec 3: ✓ Approved (0.85 confidence)
      Rec 4: ⚠ Escalated: Confidence 0.83 requires escalation
  → worker-pqr678
      Rec 1: ⚠ Escalated: Confidence 0.77 requires escalation
      Rec 2: ⚠ Escalated: Confidence 0.73 requires escalation
      Rec 3: ⚠ Escalated: Confidence 0.71 requires escalation
  → cache-layer-jkl012
      Rec 1: ⚠ Escalated: Confidence 0.72 requires escalation
      Rec 2: ⚠ Escalated: Confidence 0.70 requires escalation
      Rec 3: ⚠ Escalated: Confidence 0.68 requires escalation
  → queue-service-mno345
      Rec 1: ⚠ Escalated: Confidence 0.71 requires escalation
      Rec 2: ⚠ Escalated: Confidence 0.75 requires escalation
      Rec 3: ⚠ Escalated: Confidence 0.73 requires escalation
      Rec 4: ⚠ Escalated: Confidence 0.71 requires escalation
  → api-server-def456
      Rec 1: ⚠ Escalated: Confidence 0.73 requires escalation
      Rec 2: ⚠ Escalated: Confidence 0.71 requires escalation
      Rec 3: ⚠ Escalated: Confidence 0.69 requires escalation

──────────────────────────────────────────────────────────────────────
GUARDRAIL SUMMARY
──────────────────────────────────────────────────────────────────────
Approved actions:       4
Escalated actions:      24
Rejected actions:       0

Approved:
  - scenario10-malware-deployment-57db4df9f4-p8h7h: scale_up (0.89)
  - scenario10-malware-deployment-57db4df9f4-p8h7h: restart (0.87)
  - scenario10-malware-deployment-57db4df9f4-p8h7h: trigger_profiling (0.85)
  - gateway-stu901: trigger_profiling (0.85)

Escalated:
  - scenario10-malware-deployment-57db4df9f4-p8h7h: trigger_profiling (Confidence 0.83 requires escalation)
  - db-service-ghi789: scale_up (Confidence 0.77 requires escalation)
  - db-service-ghi789: restart (Confidence 0.75 requires escalation)
  - db-service-ghi789: trigger_profiling (Confidence 0.73 requires escalation)
  - db-service-ghi789: trigger_profiling (Confidence 0.71 requires escalation)
  ... and 19 more
```

#### Stage 5: Act (simulated)

```
======================================================================
STAGE 5: ACT
======================================================================

Executing 4 approved actions (simulated)...
  → scenario10-malware-deployment-57db4df9f4-p8h7h: scale_up... ✓ (26s)
  → scenario10-malware-deployment-57db4df9f4-p8h7h: restart... ✓ (11s)
  → scenario10-malware-deployment-57db4df9f4-p8h7h: trigger_profiling... ✓ (12s)
  → gateway-stu901: trigger_profiling...2026-10-26 17:05:39,940 - __main__ - INFO - Pipeline execution completed successfully
 ✓ (6s)

──────────────────────────────────────────────────────────────────────
EXECUTION SUMMARY
──────────────────────────────────────────────────────────────────────
Actions executed:       4
Affected pods:          2
Actions by type:
  - restart: 1
  - scale_up: 1
  - trigger_profiling: 2
Actions escalated:      24
Actions rejected:       0
```

#### Stage 6: Observe

```
======================================================================
STAGE 6: OBSERVE
======================================================================

Generating observability report...
  ✓ JSON report: output/observability_report.json
  ✓ Text dashboard: output/observability_dashboard.txt


======================================================================
OBSERVABILITY DASHBOARD
======================================================================

Pipeline Configuration:
  Case ID:    20240115
  Service:    book_info
  Timestamp:  <your-run-timestamp>

──────────────────────────────────────────────────────────────────────
Processing Summary:
  Anomalies detected:     446
  Affected pods:          8
  Analyses generated:     8

──────────────────────────────────────────────────────────────────────
Actions Taken:
  ✓ Executed:             4
  ⚠ Escalated:            24
  ✗ Rejected:             0
  Pods affected:          2

  Actions by type:
    - restart                  :   1 actions (avg confidence: 0.87)
    - scale_up                 :   1 actions (avg confidence: 0.89)
    - trigger_profiling        :   2 actions (avg confidence: 0.85)

──────────────────────────────────────────────────────────────────────
Confidence Distribution:
  Very High (≥0.85):         4 actions
  High (0.75-0.85):          0 actions
  Medium (0.60-0.75):        0 actions
  Low (0.40-0.60):           0 actions
  Very Low (<0.40):          0 actions

──────────────────────────────────────────────────────────────────────
Root Causes Identified:
  - Unknown                                 :   8 occurrences

──────────────────────────────────────────────────────────────────────
Top Anomalous Features:
  - metric_rate_storage_iops_max                      :   12 times
  - metric_rate_received_packets_p50                  :   11 times
  - log_frequency_min                                 :   11 times
  - metric_memory_usage_mean                          :    9 times
  - metric_rate_storage_iops_std                      :    9 times
  - metric_rate_storage_iops_p99                      :    9 times
  - metric_memory_usage_std                           :    9 times
  - log_golden_mean                                   :    9 times
  - metric_memory_usage_p50                           :    9 times
  - metric_rate_transmitted_packets_p50               :    9 times

──────────────────────────────────────────────────────────────────────
Most Anomalous Pods:
  - scenario10-malware-deployment-57db4df9f4-p8h7h    :    315 anomalies
  - db-service-ghi789                                 :     26 anomalies
  - frontend-v1-abc123                                :     22 anomalies
  - gateway-stu901                                    :     19 anomalies
  - worker-pqr678                                     :     18 anomalies

──────────────────────────────────────────────────────────────────────
Incident (from the KPI):
  step 3600 to step 4800 (5 windows, KPI 0.598; 1 period(s) below 0.8)

──────────────────────────────────────────────────────────────────────
Evaluation Against the Fault Label:
  Root cause pod:         scenario10-malware-deployment-57db4df9f4-p8h7h
  Its rank:               1 of 8 pods (top 1: yes, top 3: yes)
  Actions on it:          yes (24 actions on other pods)
  Time:                   not scored (the sample has no clock: its label time cannot be compared with the data)

======================================================================
```

### A real case: LEMMA-RCA 20240115 (malware → bot pods → DDoS)

The case: a malware-infected pod logs into about 30 other pods. They become bots and flood the `productpage` web server, and its error rate rises. From `python run_pipeline.py --case 20240115`, same machine and date:

```
Looking for the incident in the KPI...
  ✓ 3 period(s) with the KPI below 0.99; analysing the largest:
    2024-01-14 07:25 UTC to 2024-01-15 01:35 UTC (219 windows; KPI 1.000 before, 0.388 during)

Computing baselines per pod from 289 of 544 windows (normal windows before the incident)...
  ✓ Baseline stats computed for 63 features × 257 pods

Detecting anomalies in 219 windows...
  ✓ 660831 anomalies detected

  Affected pods: 257
      9650  productpage-v1-94d68db49-jjkdt
      9191  scenario10-bot-deployment-69bbf69f44-bhfd5
      9186  scenario10-bot-deployment-69bbf69f44-c2fz7
      9156  scenario10-bot-deployment-69bbf69f44-ccqk2
      9150  scenario10-bot-deployment-69bbf69f44-dk25p

Generating analyses and recommendations (top 10 pods)...
  → productpage-v1-94d68db49-jjkdt: Using rule-based analysis... ✓
  → scenario10-bot-deployment-69bbf69f44-bhfd5: Using rule-based analysis... ✓
  → scenario10-bot-deployment-69bbf69f44-c2fz7: Using rule-based analysis... ✓
  → scenario10-bot-deployment-69bbf69f44-ccqk2: Using rule-based analysis... ✓
  → scenario10-bot-deployment-69bbf69f44-dk25p: Using rule-based analysis... ✓
  → scenario10-bot-deployment-69bbf69f44-dsd4c: Using rule-based analysis... ✓
  → scenario10-bot-deployment-69bbf69f44-f62hr: Using rule-based analysis... ✓
  → scenario10-bot-deployment-69bbf69f44-f9wvp: Using rule-based analysis... ✓
  → scenario10-bot-deployment-69bbf69f44-f9xsl: Using rule-based analysis... ✓
  → scenario10-bot-deployment-69bbf69f44-gspdw: Using rule-based analysis... ✓

──────────────────────────────────────────────────────────────────────
PLANNING SUMMARY
──────────────────────────────────────────────────────────────────────
Anomalies detected:     660831
Affected pods:          257
Analyses generated:     10
Avg anomalies/pod:      2571.3
LLM analysis:           ✗ Disabled
```

```
GUARDRAIL SUMMARY
──────────────────────────────────────────────────────────────────────
Approved actions:       20
Escalated actions:      10
Rejected actions:       0

Approved:
  - productpage-v1-94d68db49-jjkdt: scale_up (0.89)
  - productpage-v1-94d68db49-jjkdt: restart (0.87)
  - productpage-v1-94d68db49-jjkdt: trigger_profiling (0.85)
  - scenario10-bot-deployment-69bbf69f44-bhfd5: scale_up (0.89)
  - scenario10-bot-deployment-69bbf69f44-bhfd5: restart (0.87)
  - scenario10-bot-deployment-69bbf69f44-bhfd5: trigger_profiling (0.85)
  - scenario10-bot-deployment-69bbf69f44-c2fz7: scale_up (0.89)
  - scenario10-bot-deployment-69bbf69f44-c2fz7: restart (0.87)
  - scenario10-bot-deployment-69bbf69f44-c2fz7: trigger_profiling (0.85)
  - scenario10-bot-deployment-69bbf69f44-ccqk2: scale_up (0.89)
  - scenario10-bot-deployment-69bbf69f44-ccqk2: restart (0.87)
  - scenario10-bot-deployment-69bbf69f44-ccqk2: trigger_profiling (0.85)
  - scenario10-bot-deployment-69bbf69f44-dk25p: scale_up (0.89)
  - scenario10-bot-deployment-69bbf69f44-dk25p: restart (0.87)
  - scenario10-bot-deployment-69bbf69f44-dk25p: trigger_profiling (0.85)
  - scenario10-bot-deployment-69bbf69f44-dsd4c: scale_up (0.89)
  - scenario10-bot-deployment-69bbf69f44-dsd4c: trigger_profiling (0.85)
  - scenario10-bot-deployment-69bbf69f44-f62hr: scale_up (0.89)
  - scenario10-bot-deployment-69bbf69f44-f62hr: trigger_profiling (0.85)
  - scenario10-bot-deployment-69bbf69f44-f9wvp: scale_up (0.89)

Escalated:
  - scenario10-bot-deployment-69bbf69f44-dsd4c: restart (Rollback rate limit: 5 restarts/minute exceeded)
  - scenario10-bot-deployment-69bbf69f44-f62hr: restart (Rollback rate limit: 5 restarts/minute exceeded)
  - scenario10-bot-deployment-69bbf69f44-f9wvp: restart (Rate limit: 20 actions/minute exceeded)
  - scenario10-bot-deployment-69bbf69f44-f9wvp: trigger_profiling (Rate limit: 20 actions/minute exceeded)
  - scenario10-bot-deployment-69bbf69f44-f9xsl: scale_up (Rate limit: 20 actions/minute exceeded)
  ... and 5 more
```

```
Most Anomalous Pods:
  - productpage-v1-94d68db49-jjkdt                    :   9650 anomalies
  - scenario10-bot-deployment-69bbf69f44-bhfd5        :   9191 anomalies
  - scenario10-bot-deployment-69bbf69f44-c2fz7        :   9186 anomalies
  - scenario10-bot-deployment-69bbf69f44-ccqk2        :   9156 anomalies
  - scenario10-bot-deployment-69bbf69f44-dk25p        :   9150 anomalies

──────────────────────────────────────────────────────────────────────
Incident (from the KPI):
  2024-01-14 07:25 UTC to 2024-01-15 01:35 UTC (219 windows, KPI 0.388; 3 period(s) below 0.99)

──────────────────────────────────────────────────────────────────────
Evaluation Against the Fault Label:
  Root cause pod:         scenario10-malware-deployment-57db4df9f4-p8h7h
  Its rank:               80 of 257 pods (top 1: no, top 3: no)
  Actions on it:          no (30 actions on other pods)
  Labelled failure:       2024-01-14T07:26:39Z
  KPI incident start:     -1.6 min from the label
  First anomaly on it:    -1.6 min from the label
```

What this shows:

- **The KPI finds the incident without the label.** The largest period with more than 1% errors starts 1.6 minutes before the labelled failure (the first HTTP 503). Two smaller periods are reported too: an unlabelled one on 13 January, and one near the end of the recording.
- **The root cause is not found.** The z-score ranking puts the victim (`productpage-v1`) and the bot pods on top, and the malware pod ranks 80th. That is the difficulty the case was built for: its README notes that "the large number of cascading login attempts makes it difficult to locate the container of the original source of infection".
- **Every pod is affected.** All 257 pods cross 2 σ at least once in 219 windows, so the ranking matters, not the count.
- **The guardrails bound the damage.** The rules would restart and scale the victim and the bots. The restart limit and the rate limit stop at 5 restarts and 20 actions; 10 more are escalated to a person.

### A case whose root cause is not a pod: LEMMA-RCA 20240207

A `git push` deployed wrong resource limits. From `python run_pipeline.py --case 20240207`:

```
Looking for the incident in the KPI...
  ✓ 1 period(s) with the KPI below 0.99; analysing the largest:
    2024-02-06 05:17 UTC to 2024-02-07 04:57 UTC (285 windows; KPI 1.000 before, 0.439 during)

Evaluation Against the Fault Label:
  Root cause:             git user pushing manifest file with incorrect resource limits (not a pod: no ranking to score)
  Labelled failure:       2024-02-06T05:20:41Z
  KPI incident start:     -3.7 min from the label
```

## License

MIT; see [LICENSE](LICENSE). LEMMA-RCA data is CC BY-NC 4.0 and is downloaded, not included.
