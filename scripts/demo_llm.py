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
    parser.add_argument("--function-call", action="store_true", help="One native Gemini read call (requires Gemini configuration)")
    args = parser.parse_args()
    settings = Settings.from_env()
    client, systems = make_client(settings), MockSystems()
    if args.function_call:
        if settings.provider != "gemini":
            parser.error("--function-call requires LLM_PROVIDER=gemini, GEMINI_MODEL and GEMINI_API_KEY")
        result = tool_turn(client,
            [{"role": "user", "parts": [{"text": "Đọc yêu cầu công tác TRIP-2026-001."}]}],
            read_tool_declarations(systems.registry), ["get_trip_request"], systems,
            {"workflow": "pre_trip", "actor": {"role": "employee", "actor_id": "EMP-001"},
             "request_id": "REQ-DEMO-FC", "run_id": "RUN-DEMO-FC", "bound_arguments": {"trip_id": "TRIP-2026-001"}})
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
