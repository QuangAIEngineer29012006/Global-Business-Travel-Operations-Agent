"""Run the LLM layer against the shared fixtures. Default fake mode needs no key or network."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import Settings
from backend.function_calling import read_tool_declarations, tool_turn
from backend.llm_client import make_client
from backend.service import LLMService
from src.dev_systems import MockSystems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--function-call", action="store_true", help="One native Gemini tool call (requires Gemini configuration)")
    parser.add_argument("--approval-request", action="store_true", help="Explicitly simulate one pending approval request")
    args = parser.parse_args()
    settings = Settings.from_env()
    client, systems = make_client(settings), MockSystems()
    if args.approval_request and not args.function_call:
        parser.error("--approval-request requires --function-call")
    if args.function_call:
        if settings.provider != "gemini":
            parser.error("--function-call requires LLM_PROVIDER=gemini, GEMINI_MODEL and GEMINI_API_KEY")
        if args.approval_request:
            name = "request_approval"
            message = "Gửi yêu cầu approval mô phỏng cho TRIP-2026-001 để Travel Operations xem xét."
            bindings = {"trip_id": "TRIP-2026-001", "action_summary": "Rà soát checklist chuyến công tác Singapore",
                        "idempotency_key": "REQ-DEMO-FC:approval:TRIP-2026-001"}
        else:
            name = "get_trip_request"
            message = "Đọc yêu cầu công tác TRIP-2026-001."
            bindings = {"trip_id": "TRIP-2026-001"}
        result = tool_turn(client,
            [{"role": "user", "parts": [{"text": message}]}],
            read_tool_declarations(systems.registry), [name], systems,
            {"workflow": "pre_trip", "actor": {"role": "employee", "actor_id": "EMP-001"},
             "request_id": "REQ-DEMO-FC", "run_id": "RUN-DEMO-FC", "explicit_approval_request": args.approval_request,
             "bound_arguments": bindings})
        # Thought signatures and raw history remain transient; the walkthrough prints only the observation.
        print(json.dumps(result["observation"], ensure_ascii=False, indent=2))
        return
    service = LLMService(client, systems)
    cases = [("Chuẩn bị công tác Tokyo", "EMP-002", {"trip_id": "TRIP-2026-002"}),
             ("Chuyến bay bị delay", "EMP-002", {"trip_id": "TRIP-2026-002"}),
             ("Rà soát báo cáo chi phí", "EMP-003", {"report_id": "EXP-2026-001"}),
             ("Chuẩn bị công tác Singapore", "EMP-001", {"trip_id": "TRIP-2026-001"})]
    for i, (message, actor_id, context) in enumerate(cases, 1):
        result = service.run({"request_id": f"REQ-LLM-DEMO-{i:03d}", "session_id": f"SES-{actor_id}",
                              "actor": {"role": "employee", "actor_id": actor_id}, "message": message, "context": context})
        print(json.dumps({key: result[key] for key in ("workflow", "status", "reason_code", "llm")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
