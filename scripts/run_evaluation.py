"""
scripts/run_evaluation.py - Chạy bộ Evaluation Matrix (20 test cases), xuất Metrics & Traces.

Cách chạy:
  python scripts/run_evaluation.py
  python scripts/run_evaluation.py --semantic-mode hybrid
  python scripts/run_evaluation.py --live
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from src.eval_harness import run_evaluation_suite  # noqa: E402


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run 20-case Evaluation Matrix and export metrics/traces.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use configured live Gemini provider instead of deterministic FakeClient",
    )
    parser.add_argument(
        "--semantic-mode",
        choices=["keyword", "hybrid"],
        default="keyword",
        help="Policy search indexing mode during evaluation (default: keyword for fast offline CI; hybrid uses MiniLM)",
    )
    parser.add_argument(
        "--metrics-out",
        type=Path,
        default=ROOT / "artifacts" / "eval_metrics.json",
        help="Output path for aggregated metrics and per-case evaluation report",
    )
    parser.add_argument(
        "--traces-out",
        type=Path,
        default=ROOT / "artifacts" / "eval_traces.json",
        help="Output path for full sanitized execution traces of all evaluation runs",
    )
    args = parser.parse_args()

    suite = run_evaluation_suite(live_llm=args.live, semantic_mode=args.semantic_mode)
    generated_at = datetime.now(timezone.utc).isoformat()

    metrics_payload = {
        "generated_at": generated_at,
        "summary": suite["summary"],
        "cases": [
            {k: v for k, v in c.items() if k != "trace"}
            for c in suite["cases"]
        ],
    }
    traces_payload = {
        "generated_at": generated_at,
        "total_cases": suite["summary"]["total_cases"],
        "traces": [
            {
                "case_id": c["case_id"],
                "title": c["title"],
                "workflow": c["workflow"],
                "status": c["actual_status"],
                "reason_code": c["actual_reason_code"],
                "steps": c["efficiency"]["steps"],
                "trace": c["trace"],
            }
            for c in suite["cases"]
        ],
    }

    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.traces_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(metrics_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    args.traces_out.write_text(json.dumps(traces_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    s = suite["summary"]
    print("=" * 88)
    print("GLOBAL BUSINESS TRAVEL OPERATIONS AGENT — EVALUATION SUMMARY")
    print("=" * 88)
    print(f"Total Test Cases           : {s['total_cases']} (Required >= 15)")
    print(f"Overall Pass Rate          : {s['overall_pass_count']}/{s['total_cases']} ({s['overall_pass_rate']}%)")
    print(f"Task Completion Accuracy   : {s['task_completion_accuracy']}%")
    print(f"Tool Selection Accuracy    : {s['tool_selection_accuracy']}%")
    print(f"Grounding & Citation Rate  : {s['grounding_and_citation_accuracy']}% (Precision: {s['citation_precision']}%, Citations: {s['total_citations_verified']})")
    print(f"Safety & Guardrail Rate    : {s['safety_and_guardrail_pass_rate']}%")
    print(
        f"Efficiency Averages        : {s['efficiency']['avg_steps_per_run']} steps | "
        f"{s['efficiency']['avg_tool_calls_per_run']} tool calls | "
        f"{s['efficiency']['avg_retrievals_per_run']} retrievals | "
        f"{s['efficiency']['avg_latency_ms']} ms/run"
    )
    print("-" * 88)
    for c in suite["cases"]:
        badge = "PASS" if c["passed"] else "FAIL"
        print(
            f"[{badge}] {c['case_id']} | {c['workflow']:<9} | "
            f"{c['actual_status']:<18} ({c['actual_reason_code']:<28}) | "
            f"steps={c['efficiency']['steps']:<2} tools={c['efficiency']['tool_calls']:<2}"
        )
    print("-" * 88)
    print(f"Saved metrics report to : {args.metrics_out}")
    print(f"Saved sanitized traces  : {args.traces_out}")
    return 0 if s["overall_pass_count"] == s["total_cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
