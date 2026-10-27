#!/usr/bin/env python3
"""
StreamKit Ops Playbook - End-to-End Pipeline Orchestrator

Runs all six stages sequentially:
  1. Ingest   - Load metrics and logs
  2. Fuse     - Align data by pod and time window
  3. Plan     - Detect anomalies and plan remediation
  4. Check    - Apply guardrails and validate actions
  5. Act      - Execute approved actions
  6. Observe  - Generate observability reports

Usage:
    python run_pipeline.py                  # Run with default config
    python run_pipeline.py --case 20240115  # A LEMMA-RCA case downloaded with download_data.py
    python run_pipeline.py --config custom_config.yaml
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pipeline.ingest import load_data
from pipeline.fuse import fuse_modalities
from pipeline.plan import plan_analysis
from pipeline.check import check_actions
from pipeline.act import execute_actions
from pipeline.observe import generate_report


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_header():
    """Print pipeline header."""
    print("\n" + "="*70)
    print("STREAMKIT OPS PLAYBOOK")
    print("Six-Stage Multimodal AI Pipeline for RCA")
    print("="*70)
    print(f"Started: {datetime.now(timezone.utc).isoformat()}\n")


def print_footer(total_time: float, config_case: str):
    """Print pipeline footer."""
    print("\n" + "="*70)
    print("PIPELINE EXECUTION COMPLETE")
    print("="*70)
    print(f"Case:           {config_case}")
    print(f"Total time:     {total_time:.1f} seconds")
    print(f"Finished:       {datetime.now(timezone.utc).isoformat()}")
    print("="*70 + "\n")


def run_pipeline(
    config_path: str = "config/pipeline_config.yaml",
    case: Optional[str] = None,
) -> int:
    """
    Run the complete StreamKit Ops pipeline.

    Args:
        config_path: Path to pipeline configuration file
        case: Optional case ID to override config

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    start_time = time.time()
    print_header()

    try:
        # Stage 1: Ingest
        print("Executing Stage 1: INGEST")
        print("─" * 70)
        stage1_start = time.time()

        data_dict = load_data(config_path, case)

        stage1_time = time.time() - stage1_start
        print(f"Stage 1 completed in {stage1_time:.1f}s\n")

        # Stage 2: Fuse
        print("Executing Stage 2: FUSE")
        print("─" * 70)
        stage2_start = time.time()

        fused_df = fuse_modalities(data_dict)

        stage2_time = time.time() - stage2_start
        print(f"Stage 2 completed in {stage2_time:.1f}s\n")

        # Stage 3: Plan
        print("Executing Stage 3: PLAN")
        print("─" * 70)
        stage3_start = time.time()

        plan_result = plan_analysis(fused_df, data_dict['config'])

        stage3_time = time.time() - stage3_start
        print(f"Stage 3 completed in {stage3_time:.1f}s\n")

        # Stage 4: Check
        print("Executing Stage 4: CHECK")
        print("─" * 70)
        stage4_start = time.time()

        approved, escalated, rejected = check_actions(
            plan_result,
            data_dict['config'],
        )

        stage4_time = time.time() - stage4_start
        print(f"Stage 4 completed in {stage4_time:.1f}s\n")

        # Stage 5: Act
        print("Executing Stage 5: ACT")
        print("─" * 70)
        stage5_start = time.time()

        execution_log = execute_actions(approved, escalated, rejected)

        stage5_time = time.time() - stage5_start
        print(f"Stage 5 completed in {stage5_time:.1f}s\n")

        # Stage 6: Observe
        print("Executing Stage 6: OBSERVE")
        print("─" * 70)
        stage6_start = time.time()

        observe_result = generate_report(
            execution_log,
            plan_result,
            data_dict['config'],
        )

        stage6_time = time.time() - stage6_start
        print(f"Stage 6 completed in {stage6_time:.1f}s\n")

        # Print timing summary
        total_time = time.time() - start_time
        print("\n" + "="*70)
        print("PIPELINE TIMING SUMMARY")
        print("="*70)
        print(f"Stage 1 (Ingest):       {stage1_time:6.1f}s")
        print(f"Stage 2 (Fuse):         {stage2_time:6.1f}s")
        print(f"Stage 3 (Plan):         {stage3_time:6.1f}s")
        print(f"Stage 4 (Check):        {stage4_time:6.1f}s")
        print(f"Stage 5 (Act):          {stage5_time:6.1f}s")
        print(f"Stage 6 (Observe):      {stage6_time:6.1f}s")
        print(f"{'─'*70}")
        print(f"Total:                  {total_time:6.1f}s")

        case_id = data_dict['config'].get('case', 'unknown')
        print_footer(total_time, case_id)

        logger.info("Pipeline execution completed successfully")
        return 0

    except FileNotFoundError as e:
        print(f"\n✗ Error: {e}")
        logger.error(str(e))
        return 1

    except KeyError as e:
        print(f"\n✗ Error: Missing configuration key: {e}")
        logger.error(f"Missing configuration key: {e}")
        return 1

    except Exception as e:
        print(f"\n✗ Error: Pipeline execution failed: {e}")
        logger.exception(f"Pipeline execution failed: {e}")
        return 1


def main():
    """Command-line interface for pipeline execution."""
    parser = argparse.ArgumentParser(
        description="StreamKit Ops Playbook - RCA Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_pipeline.py                    # Run with default config
  python run_pipeline.py --case 20240115    # LEMMA-RCA case (python download_data.py --case 20240115)
  python run_pipeline.py --config my_config.yaml
        """,
    )

    parser.add_argument(
        "--config",
        type=str,
        default="config/pipeline_config.yaml",
        help="Path to pipeline configuration file (default: config/pipeline_config.yaml)",
    )

    parser.add_argument(
        "--case",
        type=str,
        default=None,
        help="LEMMA-RCA case to analyze (download it first with download_data.py); default: the bundled synthetic sample",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Check if config file exists
    if not Path(args.config).exists():
        print(f"Error: Configuration file not found: {args.config}")
        print(f"Expected file at: {Path(args.config).absolute()}")
        return 1

    exit_code = run_pipeline(
        config_path=args.config,
        case=args.case,
    )

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
