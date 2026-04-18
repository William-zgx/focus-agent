"""Agent evaluation framework.

Usage:
    python -m tests.eval --suite smoke
    python -m tests.eval --suite all --report-html reports/eval.html
    pytest tests/eval/test_golden_suite.py
"""

from pathlib import Path
import sys

_SRC_DIR = Path(__file__).resolve().parents[2] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from .schema import EvalCase, EvalResult, TrajectoryStep

__all__ = ["EvalCase", "EvalResult", "TrajectoryStep"]
