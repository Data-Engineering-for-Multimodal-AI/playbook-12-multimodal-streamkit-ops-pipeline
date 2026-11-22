"""Run the six stages quietly with one config change, for the Try this experiments.

    run(case, change)  ->  dict with the plan result, the guardrail decisions and the evaluation

`case` is None for the bundled sample or a downloaded case ID (python download_data.py --case ...).
`change(config)` edits the loaded config in place before the stages run. Nothing is written.
"""

import contextlib
import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.pop("LLM_API_KEY", None)   # rule-based analysis only: the experiments never call an LLM

from pipeline.act import execute_actions  # noqa: E402
from pipeline.check import check_actions  # noqa: E402
from pipeline.evaluate import evaluate_run  # noqa: E402
from pipeline.fuse import fuse_modalities  # noqa: E402
from pipeline.ingest import load_data  # noqa: E402
from pipeline.plan import plan_analysis  # noqa: E402

CONFIG = str(ROOT / "config" / "pipeline_config.yaml")


def case_from_env():
    case = os.environ.get("CASE") or None
    if case and not (ROOT / "data" / "lemma-rca" / case / "fault_labels.json").exists():
        sys.exit(f"Case {case} isn't downloaded: python download_data.py --case {case}")
    return case


def run(case, change=lambda config: None):
    with contextlib.redirect_stdout(io.StringIO()):
        data = load_data(CONFIG, case)
        change(data["config"])
        fused = fuse_modalities(data)
        plan = plan_analysis(fused, data["config"])
        approved, escalated, rejected = check_actions(plan, data["config"])
        log = execute_actions(approved, escalated, rejected)
    return {"plan": plan, "approved": approved, "escalated": escalated, "rejected": rejected,
            "evaluation": evaluate_run(plan, log), "windows": fused["window_start"].nunique()}


def describe(case):
    return f"case {case} (LEMMA-RCA)" if case else "the bundled synthetic sample"
