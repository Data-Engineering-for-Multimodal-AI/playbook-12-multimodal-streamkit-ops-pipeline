"""
StreamKit Ops Playbook Pipeline

Six-stage multimodal AI pipeline for IT operations root cause analysis.

Stages:
    1. Ingest  - Load metrics and logs from LEMMA-RCA dataset
    2. Fuse    - Align data by pod and time window
    3. Plan    - Detect anomalies and recommend actions
    4. Check   - Apply guardrails and validate actions
    5. Act     - Simulate action execution
    6. Observe - Generate observability reports
"""

__version__ = "1.0.0"
__author__ = "Data Engineering for Multimodal AI"
