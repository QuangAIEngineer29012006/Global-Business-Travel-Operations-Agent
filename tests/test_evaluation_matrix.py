"""
tests/test_evaluation_matrix.py - Kiểm thử tự động toàn bộ 20 kịch bản trong Evaluation Matrix.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from src.eval_harness import EVALUATION_MATRIX, run_evaluation_suite, run_single_case  # noqa: E402


def test_evaluation_matrix_has_at_least_15_cases():
    assert len(EVALUATION_MATRIX) >= 15
    case_ids = [c["case_id"] for c in EVALUATION_MATRIX]
    assert len(set(case_ids)) == len(case_ids)


@pytest.mark.parametrize("case_def", EVALUATION_MATRIX, ids=[c["case_id"] for c in EVALUATION_MATRIX])
def test_individual_evaluation_case_passes(case_def):
    report = run_single_case(case_def, live_llm=False, semantic_mode="keyword")
    assert report["task_completed"], f"{case_def['case_id']} failed task completion: {report}"
    assert report["tool_audit"]["tool_accurate"], f"{case_def['case_id']} failed tool audit: {report['tool_audit']}"
    assert report["grounding_audit"]["grounded"], f"{case_def['case_id']} failed grounding: {report['grounding_audit']}"
    assert report["safety_passed"], f"{case_def['case_id']} failed safety checks: {report['safety_checks']}"
    assert report["passed"]


def test_aggregated_evaluation_metrics_reach_100_percent():
    suite = run_evaluation_suite(live_llm=False, semantic_mode="keyword")
    summary = suite["summary"]
    assert summary["total_cases"] == 20
    assert summary["overall_pass_rate"] == 100.0
    assert summary["task_completion_accuracy"] == 100.0
    assert summary["tool_selection_accuracy"] == 100.0
    assert summary["grounding_and_citation_accuracy"] == 100.0
    assert summary["citation_precision"] == 100.0
    assert summary["safety_and_guardrail_pass_rate"] == 100.0
    assert summary["efficiency"]["avg_steps_per_run"] <= 12
    assert summary["efficiency"]["avg_retrievals_per_run"] <= 6
