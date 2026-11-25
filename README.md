# Playbook 12: Find the root cause of failures in a Kubernetes cluster
**How to build an end-to-end multimodal root cause analysis pipeline.** Chapter 12 of [*Data Engineering for Multimodal AI*](https://oreil.ly/data-engineering-multimodal) (O'Reilly, 2026), pages 494–499.

When a system breaks, the clues are spread across metrics, logs and alerts, and someone has to put them together to find the cause. The chapter's running example is StreamKit, a fictional contact-center agent framework; in this repo, we apply the same pattern to IT operations with the LEMMA-RCA dataset, a Kubernetes cluster with injected failures. Follow along to build all six stages, from ingesting the signals to acting on the diagnosis and watching the result.

**The problem.** Each stage works in its own chapter, but running all of them together, and moving the design to new data, is a separate problem.

**What you'll work with.** You'll keep each stage isolated, validate data against contracts, align signals by time and session, fuse them, check every action before it runs, and watch each modality in production.

> Following the book? Its steps are in [Run it the way the book does](#run-it-the-way-the-book-does) and still work as printed. Want the code exactly as printed? Use the `first-edition` tag. This branch is the 2026 maintenance update; see [Differences from the printed book](#differences-from-the-printed-book).

## Run it

You need [uv](https://docs.astral.sh/uv/) and `make`. No Docker, no API keys: the analysis is rule-based unless you set an LLM key. Or open the repo in a GitHub Codespace, where both are ready. On Windows without `make`, use a Codespace or the book's steps below.

**1. Get the code.**

```bash
git clone https://github.com/Data-Engineering-for-Multimodal-AI/playbook-12-multimodal-streamkit-ops-pipeline.git
cd playbook-12-multimodal-streamkit-ops-pipeline
```

**2. Run the six stages on the bundled sample.** Installs the locked dependencies and runs `python run_pipeline.py` on the synthetic sample in `data/20240115/`. The reports go to `output/make-run/`, so the committed files in `output/` stay as they are. This took 15 s on a Mac, almost all of it loading Python's libraries; the stages themselves took 0.1 s.

```bash
make run
```

You should see the six stages, then the dashboard, ending with the score against the fault label:

```
Evaluation Against the Fault Label:
  Root cause pod:         scenario10-malware-deployment-57db4df9f4-p8h7h
  Its rank:               1 of 8 pods (top 1: yes, top 3: yes)
  Actions on it:          yes (24 actions on other pods)
```

**3. Run it on a real cluster.** Downloads LEMMA-RCA case 20240115 (`python download_data.py --case 20240115`: a 193 MB download, 35 MB kept) and runs the same stages on its 257 pods (`python run_pipeline.py --case 20240115`). This took 26 s on a Mac.

```bash
make run-lemma
```

```
  Its rank:               80 of 257 pods (top 1: no, top 3: no)
  Actions on it:          no (30 actions on other pods)
  Labelled failure:       2024-01-14T07:26:39Z
  KPI incident start:     -1.6 min from the label
```

The KPI finds the incident 1.6 minutes before the labelled failure, but the malware pod that caused it ranks 80th: the bots it infected deviate in more features. [Expected output](#expected-output) explains the case.

**4. Ask why a pod ranks where it does.** Prints a pod's rank, its strongest deviations from its own baseline, and what the guardrails did with the actions recommended for it. A name can be the start of a pod name.

```bash
make explain POD=scenario10-malware CASE=20240115
```

```
scenario10-malware-deployment-57db4df9f4-p8h7h: rank 80 of 257, 1619 anomalies, first at 2024-01-14 07:25 UTC
Ranked above it: productpage-v1-94d68db49-jjkdt (9650), scenario10-bot-deployment-69bbf69f44-bhfd5 (9191), ...

Strongest deviations from its baseline (in standard deviations):
  window                 feature                                     value   baseline  std devs
  2024-01-14 07:40 UTC   metric_rate_received_packets_min             3.43    0.00871      23.2
  2024-01-14 07:35 UTC   metric_received_bandwidth_min                 674       1.73      22.9
  ...
Recommended actions: none (only the top pods get recommendations)
```

The malware pod's network traffic jumped to more than 20 standard deviations above its normal at 07:35, minutes after the failure. The ranking counts anomalies, not their size, so it doesn't see this. Without `CASE=`, it explains a pod of the sample, for example `make explain POD=gateway-stu901`.

**5. Clean up.**

```bash
make clean
```

This deletes the downloaded cases (`data/lemma-rca/`), their reports (`output/lemma-rca-*`), the `make run` reports (`output/make-run/`) and the test cache. The sample and the committed `output/` files stay. The download cache in `~/.cache/huggingface` stays too; delete it to free the 193 MB.

## How much time do you have?

| Time | What to do |
|---|---|
| 15 minutes | [Run it](#run-it), steps 1 to 4. On a Mac, step 2 took 15 s and step 3 took 26 s. |
| 1 hour | The three [Try this](#try-this) experiments, on the sample (2 s each) and on case 20240115 (15 to 20 s each), then `make explain` on the pods they point to. |
| 1 day | [Use your own data](#use-your-own-data) with an export from your own cluster, the other five cases (`python download_data.py --list`), and [Before production](#before-production). |

## Try this

Each experiment changes one setting in `config/pipeline_config.yaml` (in memory; the file isn't changed) and runs the six stages again, rule-based. They run on the sample by default; `CASE=20240115` runs them on the downloaded case. The numbers below are from a Mac on 2026-11-21.

**1. How many standard deviations make an anomaly?** The plan stage flags a value more than 2 standard deviations above its pod's baseline and ranks pods by how many they have. This tries 1.5 to 8.

```bash
make try-anomaly-threshold
CASE=20240115 make try-anomaly-threshold
```

```
Anomaly threshold on the bundled synthetic sample

std devs  anomalies  pods with any  root cause rank  its anomalies  next pod  approved  on root cause
     1.5        557              8           1 of 8            315        41         4              3
     2.0        446              8           1 of 8            315        26         4              3
     3.0        348              8           1 of 8            315         7         4              3
     5.0        317              3           1 of 3            315         1         3              3
     8.0        312              2           1 of 2            311         1         3              3

Anomaly threshold on case 20240115 (LEMMA-RCA)

std devs  anomalies  pods with any  root cause rank  its anomalies  next pod  approved  on root cause
     1.5     760863            257       104 of 257           1624     10597        20              0
     2.0     660831            257        80 of 257           1619      9650        20              0
     3.0     559765            257        93 of 257            560      9189        20              0
     5.0     473476            213        83 of 213            336      9180        20              0
     8.0     412922            154        79 of 154            292      9158        20              0
```

On the sample, a higher threshold removes the false positives and the root cause stays first. On the real case, no threshold helps: even at 8 standard deviations, 154 pods have anomalies and the malware pod ranks 79th, because the bots and the victim deviate in many more features. The threshold can't fix a ranking that counts anomalies; try ranking by `max_deviation` in `rank_pods()` (`pipeline/plan.py`).

**2. How long should a fusion window be?** The fuse stage aligns metrics and logs in 5-minute windows, and the incident is 3 windows in a row with the KPI below its threshold. This tries 1 to 20 minutes.

```bash
CASE=20240115 make try-window-size
```

```
Window size on case 20240115 (LEMMA-RCA)

  window  windows  incident found  incident start vs label  root cause rank  run time
   1 min     2720             yes                 +0.3 min        79 of 257     10.6s
 2.5 min     1088             yes                 +0.8 min        79 of 257      4.0s
   5 min      544             yes                 -1.6 min        80 of 257      2.3s
  10 min      272             yes                 -6.7 min        83 of 256      1.2s
  20 min      136             yes                 -6.7 min       100 of 254      0.8s
```

Short windows put the incident start within a minute of the label but take longer to compute; long windows blur it by several minutes. On the sample (`make try-window-size`), 10- and 20-minute windows miss the incident altogether: its 20 minutes are fewer than 3 windows.

**3. How confident must a recommendation be to run without a person?** The check stage runs an action by itself at 0.85 confidence or more and sends the rest (down to 0.6) to a person. This tries 0.75 to 0.90.

```bash
make try-auto-approve
CASE=20240115 make try-auto-approve
```

```
Auto-approve confidence on the bundled synthetic sample

confidence   run  to a person  rejected  run on root cause  run on other pods  stopped by a limit
      0.75    11           17         0                  4                  7  0
      0.80     7           21         0                  4                  3  0
      0.85     4           24         0                  3                  1  0
      0.88     1           27         0                  1                  0  0
      0.90     0           28         0                  0                  0  0

Auto-approve confidence on case 20240115 (LEMMA-RCA)

confidence   run  to a person  rejected  run on root cause  run on other pods  stopped by a limit
      0.75    20           10         0                  0                 20  10
      0.80    20           10         0                  0                 20  10
      0.85    20           10         0                  0                 20  10
      0.88    10           20         0                  0                 10  0
      0.90     0           30         0                  0                  0  0
```

On the real case, every action that runs at the default bar hits a victim or a bot, never the root cause, and only the limits (5 restarts and 20 actions a minute) stop more. Lowering the bar adds actions on the wrong pods on the sample too. The confidences come from fixed rule templates (0.89 for `scale_up`, 0.87 for `restart`), so the bar decides which kinds of action run, not which pods.

## Use your own data

Export your cluster's metrics and the signal your users see as CSV files in one folder:

```
my_cluster/
  metrics.csv        timestamp, pod, metric, value          one row per sample; metric is any of
                     cpu_usage, memory_usage, rate_received_packets, rate_transmitted_packets,
                     rate_storage_iops, received_bandwidth, transmit_bandwidth
  kpi.csv            timestamp, error_rate (0 to 1)  or  timestamp, latency_ms
  logs.csv           timestamp, pod, golden_signal, frequency   (optional) log counts per pod
  fault_label.json   {"root_cause_pod": "...", "failure_time": "2026-03-02T04:10:00Z"}   (optional)
```

Timestamps are unix seconds or ISO 8601 with a time zone. The recording needs at least an hour, so there is a baseline before the incident. Check the folder first. This reads every file and writes nothing:

```bash
make check-data DIR=my_cluster
```

```
my_cluster: 8 pods, 3 metrics, 6.0 hours, KPI from error_rate, logs, a fault label. All checks passed.
```

It reports every problem with the file and the reason (at most 5 of each kind per file, then a count), and writes nothing if there is one. These are from a copy of that folder with mistakes put in on purpose:

```
7 problem(s) in broken; nothing was written:
  metrics.csv line 2: metric 'cpu_seconds_total' is not one the pipeline reads (cpu_usage, memory_usage, rate_received_packets, rate_transmitted_packets, rate_storage_iops, received_bandwidth, transmit_bandwidth)
  metrics.csv line 3: timestamp '2026-03-02 00:00:00' has no time zone (add Z for UTC)
  metrics.csv line 4: value 'n/a' is not a number
  metrics.csv line 6: second sample for web-5d8f-b2 cpu_usage at the same timestamp
  kpi.csv line 11: error_rate 5.0 is outside 0 to 1 (a share, not a percent)
  logs.csv: not UTF-8 text (byte 52)
  fault_label.json: root_cause_pod 'payments-7f9c' has no rows in metrics.csv
```

It also checks for missing files and columns, Git LFS pointers, timestamps in milliseconds, a latency of 0 or less, a recording shorter than an hour, and a KPI whose timestamps don't overlap the metrics. Each of these would make the pipeline ignore data or find the wrong incident without saying so. When everything passes, convert and run it:

```bash
make load DIR=my_cluster
```

```
Converted to data/lemma-rca/own-my_cluster/. Running the pipeline: python run_pipeline.py --case own-my_cluster
...
    2026-03-02 04:10 UTC to 2026-03-02 05:55 UTC (22 windows; KPI 0.998 before, 0.951 during)
...
Evaluation Against the Fault Label:
  Root cause pod:         payments-7f9c-q2
  Its rank:               1 of 8 pods (top 1: yes, top 3: yes)
  Actions on it:          yes (18 actions on other pods)
  Labelled failure:       2026-03-02T04:10:00Z
  KPI incident start:     +0.0 min from the label
```

This folder was generated for the test: 8 pods over 6 hours at 15-second samples, in which one pod's CPU and memory climb from 04:10 UTC and the error rate rises with them. `make load` converts it the way `download_data.py` converts a LEMMA-RCA case (30-second means, one array per metric) and runs `python run_pipeline.py --case own-my_cluster`; the reports go to `output/lemma-rca-own-my_cluster/`. It took 2 s on a Mac. The pipeline warns about the 4 metrics the folder doesn't have and runs on the other 3. `make clean` deletes the converted folder and its reports.

## What you end up with

A six-stage root cause pipeline that runs on the sample, on six real LEMMA-RCA cases and on your own cluster's exports, with a score against the fault label for every run and a way to see why each pod ranks where it does.

Skills you'll practice:
- Aligning metrics, logs and a KPI from many pods on one time grid
- Finding an incident from what users see, and baselining each pod against its own normal
- Checking recommended actions against confidence gates, policies and rate limits
- Scoring a diagnosis against labelled failures, and reading why it missed
- Converting and validating your own monitoring exports before they reach the pipeline

## Before production

This playbook runs offline on recordings, and the act stage only simulates. Before you run something like it for real:

1. **Rank by more than anomaly counts.** On case 20240115 the malware pod ranked 79th to 104th at every threshold tried ([Try this 1](#try-this)), although its network traffic was more than 20 standard deviations above normal ([Run it](#run-it), step 4). Weigh deviation size and timing (who deviated first), and follow the dependencies between pods. *Chapter 12, "Cross-Modal Correlation: Detect Cascading Failures" (page 476).*
2. **Handle features that never varied.** A feature with no variation in the baseline is scored against a floor of 1e-9, so any rise counts: 126,171 of the 660,831 anomalies in case 20240115 are of this kind, and `make explain POD=gateway-stu901` shows a deviation of 1,000,000,000. Give such features a minimum spread, or score them separately. *Chapter 12, "Signal Granularity: Instrument Each Lane" (page 474).*
3. **Tie confidence to evidence.** The rule-based confidences are fixed per action type, so a false positive gets the same score as the root cause: on the own-data test, a pod with 29 anomalies got the same three auto-approved actions as the root cause with 434 ([Use your own data](#use-your-own-data)). *Chapter 12, "Actionable Diagnostics: From Alert to Fix" (page 478).*
4. **Run in shadow mode first.** On case 20240115, every action that would have run targeted a victim or a bot, and the rate limits stopped 10 more ([Try this 3](#try-this)). Log what the pipeline would do next to what people did, and promote it action by action. *Chapter 12, "Shadow Mode and Safe Promotion" (page 484).*
5. **Pick the window for how fast you must know.** One-minute windows put the incident within 0.3 minutes of the label and took 10.6 s; 20-minute windows were 6.7 minutes off ([Try this 2](#try-this)). On a live stream, the window also sets the delay before an alert. *Chapter 12, "Benchmarking Production Readiness" (page 482).*
6. **Enforce the data contract where data enters.** The ingest stage logs a warning for a missing metric file and goes on. `make check-data` checks a folder before a run; a live pipeline should check every batch and quarantine what fails. *Chapter 12, "Pattern 1: On-the-Wire Contracts" (page 455); Chapter 12, "Schema Validation at the Edge" (page 469).*
7. **Say when a modality is missing.** Case 20240207 has no logs and 20240124 has no log-frequency file; the pipeline runs on what it has but the report doesn't say its evidence is thinner. *Chapter 12, "Resilient Operation Under Modality Failure" (page 490).*
8. **Keep a labelled set of incidents.** Every run is scored against its fault label (`pipeline/evaluate.py`); keep scoring every change against all six cases and your own past incidents. *Chapter 12, "Evaluation and Feedback Loops" (page 493).*
9. **Treat LLM answers as untrusted.** With an LLM key set, the model's own confidence goes straight into the confidence gate; only its action name is checked against the allowed list. Check its answer against the evidence before it can approve anything. *Chapter 11, "Adversarial Threats to Multimodal LLMs" (page 424).*

## What it costs

| Where you run it | Cost |
|---|---|
| Your machine | $0 with the rule-based analysis (the default): no API keys, no paid services. About 140 MB for the environment; each LEMMA-RCA case adds about 35 MB, plus about 200 MB in the download cache. |
| A GitHub Codespace (2 cores, 8 GB, the default size; this repo asks for none) | Estimated $0.18 per hour at GitHub's list price (November 2026). A free personal account includes 120 core-hours a month, about 60 hours on this machine. In CI, `make run` in a clean devcontainer (the dependencies were installed while the container was created) took 2 s; the whole job took under a minute. |
| An LLM for the analysis (optional) | Not run for this update. Estimated at most $0.09 per run of case 20240115 with `gpt-4o` and at most $0.06 per run of the sample, at OpenAI's list price of $2.50 per million input tokens and $10.00 per million output tokens ([OpenAI pricing](https://developers.openai.com/api/docs/pricing), November 2026). The run makes one call per analysed pod: 10 calls with 50,409 characters of prompts for case 20240115, and 8 calls with 17,277 characters for the sample, measured by recording the prompts without sending them; at about 4 characters per token that is about 12,600 and 4,300 input tokens, plus at most 500 output tokens per call. |

## How it works

The pipeline has six stages, for IT-operations root cause analysis (RCA) on the LEMMA-RCA cloud dataset: a Kubernetes cluster of about 260 pods, with injected failures.

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

## Run it the way the book does

These are the book's steps in "Running the Playbook" (page 498), with the fixes listed in [Differences from the printed book](#differences-from-the-printed-book).

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

With [uv](https://docs.astral.sh/uv/): `uv sync`, then prefix commands with `uv run`. The Makefile has shortcuts: `make run`, `make run-lemma`, `make run-20240207`, `make smoke`; `make explain`, `make check-data`, `make load` and `make try-*` are described in [Run it](#run-it), [Use your own data](#use-your-own-data) and [Try this](#try-this).

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

The LLM gets each top pod's 50 strongest deviations and returns a root cause, an action and a confidence. If a call fails, that pod falls back to the rule-based analysis. This path was not run for this update; all output below is rule-based. The book's `export ANTHROPIC_API_KEY=...` (page 498) is not read by the code; use the three variables above with the provider's OpenAI-compatible endpoint. They are listed in `.env.example`.

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
| 2026-10-27 | Ubuntu (GitHub Actions) | 3.12 | Cases 20231207, 20231221, 20240124, 20240215: same results as the table |
| 2026-10-26 | Ubuntu (GitHub Actions) | 3.12, 3.13 | `make smoke`, then after `pip install -r requirements.txt`: the sample, and both cases downloaded and run |

Versions are pinned in `uv.lock` and `requirements.txt` (NumPy 2.5, pandas 3.1, huggingface_hub 2.3, openai 3.39).

## Differences from the printed book

The printed commands still work: `pip install -r requirements.txt`, `python download_data.py --case 20240115`, `python run_pipeline.py`, and the stage functions in the snippet above. The left column is the first edition: the code at the `first-edition` tag, which the book describes.

| Area | First edition | Now |
|---|---|---|
| Folder | The book's `cd streamkit-ops-playbook` (page 498) | `cd playbook-12-multimodal-streamkit-ops-pipeline` |
| `python run_pipeline.py` after the download (page 498) | Ran the synthetic sample | Still runs the sample, and prints the `--case` command for the downloaded case |
| LLM | The book's `ANTHROPIC_API_KEY` (page 498) was never read; the code read `LLM_API_KEY` | Unchanged: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` |
| Other cases (page 498) | Could not run | All six run (table above) |
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
| LEMMA-RCA cases (downloaded) | [Lemma-RCA-NEC/Cloud_Computing_Preprocessed](https://huggingface.co/datasets/Lemma-RCA-NEC/Cloud_Computing_Preprocessed), revision `03f82a2c`. L. Zheng, Z. Chen, D. Wang, C. Deng, R. Matsuoka, H. Chen, "LEMMA-RCA: A Large Multi-modal Multi-domain Dataset for Root Cause Analysis", [arXiv:2406.05375](https://arxiv.org/abs/2406.05375) | CC BY-NC 4.0 (non-commercial), per the dataset card at that revision; the book (page 495) says CC BY-ND 4.0. Not redistributed here; `download_data.py` fetches it |

The full list, with sources, licenses and citations, is in [DATA_LICENSES.md](DATA_LICENSES.md).

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

If this playbook helped you, a star helps other readers find it.

## License

MIT; see [LICENSE](LICENSE). LEMMA-RCA data is CC BY-NC 4.0 and is downloaded, not included.
