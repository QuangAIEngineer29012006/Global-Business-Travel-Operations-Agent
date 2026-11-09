"""Opt-in live Gemini smoke test. Sends only the repository's synthetic training examples."""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import Settings
from backend.function_calling import read_tool_declarations, tool_turn
from backend.llm_client import LLMError, make_client
from backend.main import create_app
from backend.service import LLMService
from src.dev_systems import MockSystems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True, help="Explicitly allow real Gemini API calls")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/gemini_live_smoke.json")
    args = parser.parse_args()
    settings = Settings.from_env()
    if settings.provider != "gemini":
        parser.error("Configure Gemini in .env before using --live")
    client, systems = make_client(settings), MockSystems()
    service = LLMService(client, systems)
    report = {"tested_at_utc": datetime.now(timezone.utc).isoformat(), "model": client.model_id,
              "provider": "gemini", "live_api": True, "training_data_only": True, "cases": []}

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def check(name, callback):
        start = time.monotonic()
        try:
            details = callback()
        except Exception as exc:
            code = exc.code if isinstance(exc, LLMError) else type(exc).__name__
            report["cases"].append({"case": name, "passed": False, "error_code": code,
                                    "seconds": round(time.monotonic() - start, 3)})
            save()
            print(name + ": FAIL (" + code + ")", flush=True)
            raise SystemExit(1) from None
        report["cases"].append({"case": name, "passed": True, "seconds": round(time.monotonic() - start, 3), **details})
        save()
        print(name + ": PASS", flush=True)

    def workflow(message, actor, context, expected):
        result = service.run({"request_id": "REQ-LIVE-" + str(len(report["cases"]) + 1), "session_id": "SES-LIVE-" + actor,
                              "actor": {"role": "employee", "actor_id": actor}, "message": message, "context": context})
        llm = result["llm"]
        if result["status"] != expected or llm["status"] != "ok" or llm["calls"] != 1:
            raise LLMError(llm["error_code"] or "unexpected_workflow_outcome")
        if result["reason_code"] == "TEXT_REWRITE":
            edited = llm["message"].lower()
            if "tôi" not in edited or "chuyến bay" not in edited or not re.search(r"hỗ trợ|giúp", edited) or re.search(
                    r"chào bạn|vui lòng cung cấp|mã đặt chỗ|mã vé|hãng hàng không|để tôi", edited):
                raise LLMError("rewrite_answered_instead_of_editing")
        return {"workflow": result["workflow"], "outcome": result["status"], "llm_message": llm["message"],
                "input_tokens": llm["input_tokens"], "output_tokens": llm["output_tokens"], "retry_count": llm["retry_count"]}

    cases = [("pre_trip_approved", "Chuẩn bị công tác Tokyo", "EMP-002", {"trip_id": "TRIP-2026-002"}, "completed"),
             ("in_trip_delay", "Chuyến bay bị delay", "EMP-002", {"trip_id": "TRIP-2026-002"}, "completed"),
             ("expense_review", "Rà soát báo cáo chi phí", "EMP-003", {"report_id": "EXP-2026-001"}, "completed"),
             ("pending_approval", "Chuẩn bị công tác Singapore", "EMP-001", {"trip_id": "TRIP-2026-001"}, "awaiting_approval"),
             ("text_rewrite", "Viết lại chuyên nghiệp: tôi bị trễ chuyến bay, giúp với", "EMP-002", {}, "completed")]
    for name, message, actor, context, expected in cases:
        check(name, lambda m=message, a=actor, c=context, e=expected: workflow(m, a, c, e))

    turn = {}

    def native_call():
        turn.update(tool_turn(client,
            [{"role": "user", "parts": [{"text": "Đọc yêu cầu công tác TRIP-2026-001."}]}],
            read_tool_declarations(systems.registry), ["get_trip_request"], systems,
            {"workflow": "pre_trip", "actor": {"role": "employee", "actor_id": "EMP-001"},
             "run_id": "RUN-LIVE-FC", "request_id": "REQ-LIVE-FC", "bound_arguments": {"trip_id": "TRIP-2026-001"}}))
        observation = turn["observation"]
        if not observation["ok"] or observation["data"]["travel_status"] != "pending_approval":
            raise LLMError("unexpected_tool_observation")
        return {"tool": "get_trip_request", "trip_id": observation["data"]["trip_id"],
                "observed_status": observation["data"]["travel_status"], "input_tokens": turn["input_tokens"],
                "output_tokens": turn["output_tokens"], "retry_count": turn["retry_count"]}

    check("native_function_call", native_call)

    def continuation():
        contents = [*turn["contents"], {"role": "user", "parts": [{"text": "Chỉ trả lời đúng mã travel_status trong kết quả tool vừa nhận; không gọi tool nữa."}]}]
        result = client._generate("Report only the observed travel_status; never infer approval.", contents,
                                  tools=[{"functionDeclarations": read_tool_declarations(systems.registry)}],
                                  toolConfig={"functionCallingConfig": {"mode": "NONE"}})
        answer = client._text(result)
        if "pending_approval" not in answer:
            raise LLMError("tool_response_not_grounded")
        return {"answer": answer, "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
                "retry_count": result.retry_count}

    check("function_response_roundtrip", continuation)

    def api_endpoint():
        with TestClient(create_app(settings, dispatcher=systems, client=client)) as api:
            response = api.post("/api/runs", json={"request_id": "REQ-LIVE-API", "session_id": "SES-LIVE-API",
                "actor": {"role": "employee", "actor_id": "EMP-001"},
                "message": "Tôi chuẩn bị công tác Singapore, đã đủ điều kiện chưa?", "context": {"trip_id": "TRIP-2026-001"}})
        result = response.json()
        if response.status_code != 200 or result["status"] != "awaiting_approval" or result["data"]["approval_status"] != "pending":
            raise LLMError("api_contract_mismatch")
        llm = result["llm"]
        if llm["status"] != "ok" or not llm["input_tokens"] or not llm["output_tokens"]:
            raise LLMError(llm["error_code"] or "api_llm_fallback")
        return {"http_status": response.status_code, "outcome": result["status"], "observed_approval": "pending",
                "llm_message": llm["message"], "input_tokens": llm["input_tokens"], "output_tokens": llm["output_tokens"],
                "retry_count": llm["retry_count"]}

    check("live_api_endpoint", api_endpoint)
    report["passed"] = len(report["cases"])
    report["total"] = len(report["cases"])
    save()
    print(f"Live Gemini: {report['passed']}/{report['total']} passed. Evidence: {args.output}", flush=True)


if __name__ == "__main__":
    main()
