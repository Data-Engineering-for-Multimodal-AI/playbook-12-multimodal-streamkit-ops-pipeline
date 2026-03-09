# StreamKit Ops Playbook

A six-stage multimodal AI pipeline for IT operations root cause analysis using the LEMMA-RCA dataset.

This project demonstrates the complete workflow from Chapter 12 of "Data Engineering for Multimodal AI", implementing an automated root cause analysis system that ingests metrics and logs, fuses them intelligently, applies anomaly detection with optional LLM-powered reasoning, enforces safety guardrails, simulates remediation actions, and provides comprehensive observability.

## What This Project Does

The pipeline processes time-series operational data to detect anomalies and recommend intelligent remediation:

1. **Ingest** - Load metrics (CPU, memory, network, storage) and logs from the LEMMA-RCA dataset
2. **Fuse** - Align metrics and logs by pod name and time window into a unified feature space
3. **Plan** - Detect anomalies, compute baselines, and optionally use an LLM for intelligent analysis
4. **Check** - Apply guardrails: input validation, action filtering, confidence gating, escalation rules
5. **Act** - Simulate execution of approved actions with before/after state tracking
6. **Observe** - Aggregate results into observability dashboards and reports

## Prerequisites

- Python 3.9 or higher
- pip (Python package manager)
- Internet connection (for downloading LEMMA-RCA dataset from HuggingFace)
- Optional: LLM_API_KEY environment variable for LLM integration (any OpenAI-compatible API)

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Download Data

Download the LEMMA-RCA Cloud Computing dataset (default case 20240115):

```bash
python download_data.py
```

To download a different case (e.g., 20240207):

```bash
python download_data.py --case 20240207
```

Available cases: 20231207, 20231221, 20240115, 20240124, 20240207, 20240215

The data will be extracted to `data/{case}/`.

### 3. Configure Pipeline (Optional)

Edit `config/pipeline_config.yaml` to adjust:
- Case ID and dataset labels
- Data paths
- Metric thresholds
- Guardrail confidence gates
- Allowed remediation actions

## Running the Pipeline

### End-to-End Pipeline

Run all six stages sequentially:

```bash
python run_pipeline.py
```

With a specific case:

```bash
python run_pipeline.py --case 20240207
```

### Individual Stages

You can run each stage independently for testing:

```python
# Stage 1: Ingest
from pipeline.ingest import load_data
data_dict = load_data('config/pipeline_config.yaml')

# Stage 2: Fuse
from pipeline.fuse import fuse_modalities
fused_df = fuse_modalities(data_dict)

# Stage 3: Plan
from pipeline.plan import plan_analysis
plan_result = plan_analysis(fused_df, data_dict['config'])

# Stage 4: Check
from pipeline.check import check_actions
approved, escalated, rejected = check_actions(plan_result, data_dict['config'])

# Stage 5: Act
from pipeline.act import execute_actions
execution_log = execute_actions(approved, escalated, rejected)

# Stage 6: Observe
from pipeline.observe import generate_report
report = generate_report(execution_log, plan_result, data_dict['config'])
```

## Expected Output (Stage by Stage)

This section shows the actual output you should see at each stage when running the pipeline with the default case (`20240115`). Use this as a reference to verify your pipeline is working correctly.

### Step 0: Download Data

```bash
python download_data.py
```

**Expected output:**

```
Downloading LEMMA-RCA dataset for case 20240115...
Repository: Lemma-RCA-NEC/Cloud_Computing_Preprocessed
Output directory: data/20240115

Found 13 files in repository

Found 2 zip files for case 20240115:
  Log Data/20240115.zip
  Metrics Data/20240115.zip

Downloading Log Data/20240115.zip...
  Downloaded to: /Users/<you>/.cache/huggingface/hub/datasets--Lemma-RCA-NEC--Cloud_Computing_Preprocessed/...
  Extracting to data/20240115...
  Extraction complete

Downloading Metrics Data/20240115.zip...
  Downloaded to: /Users/<you>/.cache/huggingface/hub/datasets--Lemma-RCA-NEC--Cloud_Computing_Preprocessed/...
  Extracting to data/20240115...
  Extraction complete

Validating extracted files...
Found 301 data files:
  KPI20140115.csv
  adservice-7df8c84f69-kwldj_messages_structured.csv
  ... (additional pod log CSV files)

Metric files (21):
  pod_level_data_cpu_usage.npy
  pod_level_data_memory_usage.npy
  pod_level_data_rate_received_packets.npy
  ... (additional metric .npy files)

All required files found!

Dataset successfully downloaded and extracted to data/20240115
```

The download retrieves 2 zip files (log data and metrics data) and extracts ~301 files including `.npy` metric arrays, `.npy` log arrays, KPI CSVs, and per-pod structured log CSVs.

### Stage 1: Ingest

The pipeline loads 7 metrics, 2 log types, and KPI data. Each metric is a 5000-timestamp x 8-pod array.

**Expected output:**

```
======================================================================
STAGE 1: INGEST
======================================================================

Loading configuration...
  Case: 20240115
  Service: book_info
  Data path: data/20240115/

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

Validating consistency...
  ✓ All metrics have consistent pod names and sequence lengths

Converting to DataFrames...
  ✓ cpu_usage: 5000 timestamps × 8 pods
  ✓ memory_usage: 5000 timestamps × 8 pods
  ✓ rate_received_packets: 5000 timestamps × 8 pods
  ✓ rate_transmitted_packets: 5000 timestamps × 8 pods
  ✓ rate_storage_iops: 5000 timestamps × 8 pods
  ✓ received_bandwidth: 5000 timestamps × 8 pods
  ✓ transmit_bandwidth: 5000 timestamps × 8 pods

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
```

**What to check:** All 7 metrics should load with shape `(5000, 8)`. The consistency check should pass. Golden signal logs, frequency logs, and KPI should all be marked `✓ Available`.

### Stage 2: Fuse

The fuse stage aligns all modalities by pod and time window. With 5000 timestamps and a window size of 300, it creates 17 windows per pod (16 full windows + 1 partial that meets the half-window threshold), and with 8 pods that yields 136 total rows.

**Expected output:**

```
======================================================================
STAGE 2: FUSE
======================================================================

Common pods across all modalities: 8
Total timestamps: 5000
Time windows created: 17 windows of size 300

Processing pod: api-server-def456
Processing pod: cache-layer-jkl012
Processing pod: db-service-ghi789
Processing pod: frontend-v1-abc123
Processing pod: gateway-stu901
Processing pod: queue-service-mno345
Processing pod: scenario10-malware-deployment-57db4df9f4-p8h7h
Processing pod: worker-pqr678

──────────────────────────────────────────────────────────────────────
FUSION SUMMARY
──────────────────────────────────────────────────────────────────────
Pods fused:         8
Windows per pod:    17
Total rows:         136
Total columns:      67
Feature groups:
  - Metrics: 49
  - Golden logs: 7
  - Frequency logs: 7
```

**What to check:** 8 pods should be found across all modalities. The fusion should produce 136 rows (8 pods x 17 windows) and 67 columns (7 metrics x 7 aggregations = 49, plus 7 golden log features, 7 frequency log features, and 4 metadata columns: pod, window_start, window_end, window_id).

### Stage 3: Plan

The plan stage computes baselines from the first 70% of data and detects anomalies in the remaining 30% using z-score thresholds. Without an LLM key, it falls back to rule-based analysis.

**Expected output:**

```
======================================================================
STAGE 3: PLAN
======================================================================

Computing baselines from first 70% of data...
  ✓ Baseline stats computed for 63 features

Detecting anomalies in remaining 30% of data...
  ✓ 386 anomalies detected

  Affected pods: 3

Generating analyses and recommendations...
  → queue-service-mno345: Using rule-based analysis... ✓
  → scenario10-malware-deployment-57db4df9f4-p8h7h: Using rule-based analysis... ✓
  → worker-pqr678: Using rule-based analysis... ✓

──────────────────────────────────────────────────────────────────────
PLANNING SUMMARY
──────────────────────────────────────────────────────────────────────
Anomalies detected:     386
Affected pods:          3
Analyses generated:     3
Avg anomalies/pod:      128.7
LLM analysis:           ✗ Disabled
```

**What to check:** The pipeline detects ~386 anomalies across 3 affected pods (out of 8 total). The malware deployment pod (`scenario10-malware-deployment-57db4df9f4-p8h7h`) has the most severe anomalies, which makes sense since the LEMMA-RCA dataset includes injected fault scenarios. Note that LLM analysis shows `✗ Disabled` unless you set the `LLM_API_KEY` environment variable.

### Stage 4: Check (Guardrails)

The check stage applies confidence gating: actions with confidence >= 0.85 are auto-approved, 0.60-0.85 are escalated for human review, and < 0.60 are rejected.

**Expected output:**

```
======================================================================
STAGE 4: CHECK (GUARDRAILS)
======================================================================

Validating 3 analyses against guardrails...
  → queue-service-mno345
      Rec 1: ⚠ Escalated: Confidence 0.72 requires escalation
      Rec 2: ⚠ Escalated: Confidence 0.64 requires escalation
      Rec 3: ⚠ Escalated: Confidence 0.68 requires escalation
  → scenario10-malware-deployment-57db4df9f4-p8h7h
      Rec 1: ✓ Approved (0.89 confidence)
      Rec 2: ✓ Approved (0.87 confidence)
      Rec 3: ✓ Approved (0.85 confidence)
      Rec 4: ⚠ Escalated: Confidence 0.83 requires escalation
  → worker-pqr678
      Rec 1: ⚠ Escalated: Confidence 0.67 requires escalation
      Rec 2: ⚠ Escalated: Confidence 0.65 requires escalation
      Rec 3: ⚠ Escalated: Confidence 0.69 requires escalation
      Rec 4: ⚠ Escalated: Confidence 0.67 requires escalation

──────────────────────────────────────────────────────────────────────
GUARDRAIL SUMMARY
──────────────────────────────────────────────────────────────────────
Approved actions:       3
Escalated actions:      8
Rejected actions:       0

Approved:
  - scenario10-malware-deployment-57db4df9f4-p8h7h: scale_up (0.89)
  - scenario10-malware-deployment-57db4df9f4-p8h7h: restart (0.87)
  - scenario10-malware-deployment-57db4df9f4-p8h7h: trigger_profiling (0.85)

Escalated:
  - queue-service-mno345: scale_up
  - queue-service-mno345: collect_logs
  - queue-service-mno345: trigger_profiling
  - scenario10-malware-deployment-57db4df9f4-p8h7h: trigger_profiling
  - worker-pqr678: restart_with_debug
```

**What to check:** Only the malware-deployment pod generates high enough confidence (0.85+) for auto-approval. The 3 approved actions are `scale_up`, `restart`, and `trigger_profiling` for that pod. The remaining 8 actions across all 3 pods are escalated to human review. No actions are rejected, meaning all are above the 0.60 minimum confidence threshold.

### Stage 5: Act

The act stage simulates execution of the 3 approved actions. Duration values are randomized, so your exact seconds will vary.

**Expected output:**

```
======================================================================
STAGE 5: ACT
======================================================================

Executing 3 approved actions...
  → scenario10-malware-deployment-57db4df9f4-p8h7h: scale_up... ✓ (20s)
  → scenario10-malware-deployment-57db4df9f4-p8h7h: restart... ✓ (23s)
  → scenario10-malware-deployment-57db4df9f4-p8h7h: trigger_profiling... ✓ (20s)

──────────────────────────────────────────────────────────────────────
EXECUTION SUMMARY
──────────────────────────────────────────────────────────────────────
Actions executed:       3
Affected pods:          1
Actions by type:
  - restart: 1
  - scale_up: 1
  - trigger_profiling: 1
Actions escalated:      8
Actions rejected:       0
```

**What to check:** Exactly 3 actions should execute successfully (all targeting the malware-deployment pod). Each should show `✓` with a simulated duration (5-30 seconds, randomized). The summary should reflect 1 affected pod, 3 executed, 8 escalated, 0 rejected.

### Stage 6: Observe

The observe stage generates a JSON report and a text dashboard, writing both to the `output/` directory.

**Expected output:**

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
  Anomalies detected:     386
  Affected pods:          3
  Analyses generated:     3

──────────────────────────────────────────────────────────────────────
Actions Taken:
  ✓ Executed:             3
  ⚠ Escalated:            8
  ✗ Rejected:             0
  Pods affected:          1

  Actions by type:
    - restart                  :   1 actions (avg confidence: 0.87)
    - scale_up                 :   1 actions (avg confidence: 0.89)
    - trigger_profiling        :   1 actions (avg confidence: 0.85)

──────────────────────────────────────────────────────────────────────
Confidence Distribution:
  Very High (≥0.85):         3 actions
  High (0.75-0.85):          0 actions
  Medium (0.60-0.75):        0 actions
  Low (0.40-0.60):           0 actions
  Very Low (<0.40):          0 actions

──────────────────────────────────────────────────────────────────────
Root Causes Identified:
  - Unknown                                 :   3 occurrences

──────────────────────────────────────────────────────────────────────
Top Anomalous Features:
  - metric_rate_storage_iops_max                      :   10 times
  - metric_rate_transmitted_packets_p95               :    9 times
  - metric_memory_usage_mean                          :    8 times
  - metric_rate_storage_iops_std                      :    8 times
  - log_golden_std                                    :    8 times
  - metric_rate_received_packets_max                  :    8 times
  - log_frequency_std                                 :    8 times
  - metric_rate_transmitted_packets_mean              :    7 times
  - metric_rate_received_packets_p50                  :    7 times
  - metric_transmit_bandwidth_p99                     :    7 times

======================================================================
```

**What to check:** Two output files should be created in `output/`. The dashboard shows that storage IOPS, transmitted packets, and memory usage are the top anomalous features -- consistent with the malware injection scenario in the LEMMA-RCA dataset. Root causes show "Unknown" because rule-based analysis does not classify root causes (LLM mode would populate this with specific diagnoses). All 3 executed actions have "Very High" confidence (>= 0.85).

### Pipeline Timing Summary

After all six stages complete, the pipeline prints a timing summary:

```
======================================================================
PIPELINE TIMING SUMMARY
======================================================================
Stage 1 (Ingest):          0.0s
Stage 2 (Fuse):            0.2s
Stage 3 (Plan):            0.0s
Stage 4 (Check):           0.0s
Stage 5 (Act):             0.0s
Stage 6 (Observe):         0.0s
──────────────────────────────────────────────────────────────────────
Total:                     0.2s

======================================================================
PIPELINE EXECUTION COMPLETE
======================================================================
Case:           20240115
Total time:     0.2 seconds
Finished:       <your-run-timestamp>
======================================================================
```

**What to check:** The entire pipeline should complete in under 1 second. The Fuse stage is the most computationally expensive due to windowed aggregation across all pods and metrics. If your run takes significantly longer, check that the data was loaded correctly and no warnings were printed during ingestion.

### Output Files

After the pipeline completes, check the `output/` directory:

```
output/
├── observability_report.json    # Machine-readable JSON report
└── observability_dashboard.txt  # Human-readable text dashboard
```

The JSON report contains structured data including anomaly counts, action summaries by type with average confidence, confidence distribution buckets, root cause tallies, and the top 10 most frequent anomalous features.

## Project Structure

```
streamkit-ops-playbook/
├── README.md                    # This file
├── requirements.txt             # Python dependencies
├── download_data.py             # Download LEMMA-RCA dataset from HuggingFace
├── run_pipeline.py              # End-to-end pipeline orchestrator
├── config/
│   └── pipeline_config.yaml     # Pipeline configuration
├── pipeline/
│   ├── __init__.py
│   ├── ingest.py               # Stage 1: Load and validate data
│   ├── fuse.py                 # Stage 2: Align metrics and logs
│   ├── plan.py                 # Stage 3: Anomaly detection and analysis
│   ├── check.py                # Stage 4: Guardrails and validation
│   ├── act.py                  # Stage 5: Action execution simulation
│   └── observe.py              # Stage 6: Observability and reporting
├── output/                      # Generated reports (created by pipeline)
│   ├── observability_report.json
│   └── observability_dashboard.txt
└── data/                        # Dataset directory (created by download_data.py)
    └── {case}/                  # Data for specific case
        ├── pod_level_data_*.npy # Per-metric time series (7 files)
        ├── pod_level_log_*.npy  # Log signal arrays (2 files)
        ├── kpi.csv              # Service-level KPI data
        └── fault_labels.json    # Injected fault metadata
```

## Data Format

The LEMMA-RCA dataset includes:

- **Metrics** (`.npy` arrays): Time-series data for 7 metrics -- CPU usage, memory usage, rate of received/transmitted packets, storage IOPS, and received/transmit bandwidth. Each file contains a dictionary keyed by service label (e.g., `book_info`), with `Pod_Name`, `Sequence` (numpy 2D array: timestamps x pods), and `KPI_Feature` fields.
- **Logs** (`.npy` arrays): Golden signal logs and log frequency data from Kubernetes pods, structured identically to metrics but using `Node_Name` instead of `Pod_Name`.
- **KPI** (`kpi.csv`): Service-level health indicators with 5000 rows and 2 columns.
- **Fault Labels** (`fault_labels.json`): Metadata about injected faults for the scenario, including timestamps and root cause identifiers.

## Configuration

Key configuration parameters in `pipeline_config.yaml`:

```yaml
case: 20240115                           # Dataset case ID
label: book_info                         # Service label
data_path: data/20240115/               # Data directory
metrics:                                # Metrics to analyze
  - cpu_usage
  - memory_usage
  - rate_received_packets
  - rate_transmitted_packets
  - rate_storage_iops
  - received_bandwidth
  - transmit_bandwidth
thresholds:
  std_multiplier: 2.0                  # Std dev for anomaly detection
  confidence_high: 0.85                # High confidence threshold
  confidence_medium: 0.6               # Medium confidence threshold
guardrails:
  max_replica_scale: 10               # Max pods in scale action
  max_rollback_rate: 5                # Max rollbacks per minute
allowed_actions:                        # Approved remediation actions
  - scale_up
  - scale_down
  - restart
  - restart_with_debug
  - collect_logs
```

## LLM Integration (Optional)

For intelligent analysis with any OpenAI-compatible LLM, set your API key and base URL:

```bash
export LLM_API_KEY="your-api-key"
export LLM_BASE_URL="https://api.your-provider.com/v1"  # optional, defaults to OpenAI
export LLM_MODEL="gpt-4o"  # optional, defaults to gpt-4o
python run_pipeline.py
```

The pipeline will use the LLM for reasoning about root causes and generating contextual recommendations. Without the API key, the pipeline uses rule-based analysis. This works with any provider that exposes an OpenAI-compatible chat completions endpoint.

## Understanding the Output

The pipeline generates:

1. **Console Output**: Stage-by-stage progress with checkmarks (✓/✗/⚠), summaries, and a final timing breakdown
2. **JSON Report** (`output/observability_report.json`): Machine-readable report with anomaly counts, action breakdowns, confidence distribution, root causes, and top anomalous features
3. **Text Dashboard** (`output/observability_dashboard.txt`): Human-readable formatted dashboard summarizing the full pipeline run

Key metrics in the observability report:
- Total anomalies detected and affected pods
- Actions executed, escalated, and rejected (with per-type breakdown and average confidence)
- Confidence distribution across 5 buckets (very low through very high)
- Root causes identified (populated when LLM is enabled, otherwise "Unknown")
- Top 10 most frequently anomalous features

## References

- **Dataset**: LEMMA-RCA dataset from HuggingFace (Lemma-RCA-NEC/Cloud_Computing_Preprocessed)
- **Paper**: See the LEMMA-RCA baseline repository for dataset documentation
- **Chapter**: Chapter 12, "Data Engineering for Multimodal AI"

## License

This code is provided as-is for educational and operational use.

## Copyright

Copyright (c) 2025 Data Engineering for Multimodal AI

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.