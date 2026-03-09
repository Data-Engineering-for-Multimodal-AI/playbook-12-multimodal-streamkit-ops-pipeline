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
analysis = plan_analysis(fused_df, config)

# Stage 4: Check
from pipeline.check import check_actions
approved, escalated, rejected = check_actions(analysis, config)

# Stage 5: Act
from pipeline.act import execute_actions
execution_log = execute_actions(approved)

# Stage 6: Observe
from pipeline.observe import generate_report
report = generate_report(execution_log, analysis, config)
```

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
└── data/                        # Dataset directory (created by download_data.py)
    └── {case}/                  # Data for specific case
        ├── pod_level_data_*.npy
        ├── pod_level_log_*.npy
        └── kpi.csv
```

## Data Format

The LEMMA-RCA dataset includes:

- **Metrics**: Time-series data for CPU usage, memory, network I/O, storage I/O
- **Logs**: Golden signal logs and log frequency data from Kubernetes pods
- **KPI**: Service-level health indicators
- **Fault Labels**: Injected faults with timestamps and root cause identifiers

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

1. **Console Output**: Stage-by-stage progress with timing
2. **Observability Report**: JSON file with detailed metrics
3. **Execution Log**: Timestamped record of all actions taken

Example observability report metrics:
- Total events processed
- Anomalies detected (with confidence distribution)
- Actions taken (approved and escalated)
- Top root causes identified
- Service-level impact assessment

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