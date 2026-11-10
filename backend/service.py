import re
from datetime import datetime, timezone

from src.workflows import RunState, finish, run_agent

from .llm_client import LLMError
from .models import PresentationPlan


def highlights_for(result):
    highlights = {}
    data = result["data"]
    if "approval_status" in data:
        highlights["approval"] = "Trạng thái từ approval system: " + data["approval_status"] + "."
    summary = data.get("summary", {})
    if "total" in summary and "currency" in summary:
        highlights["expense_total"] = f"Tổng do tool tính: {summary['total']} {summary['currency']}."
    if data.get("flags"):
        highlights["review_flags"] = f"Có {len(data['flags'])} cờ cần reviewer kiểm tra."
    if data.get("missing_fields"):
        highlights["missing_fields"] = "Trường còn thiếu: " + ", ".join(data["missing_fields"]) + "."
    for index, artifact in enumerate(result["artifacts"][:3]):
        highlights[f"draft_{index}"] = f"Bản nháp {artifact['draft_id']}: delivery_status={artifact['delivery_status']}."
    return highlights


class LLMService:
    """Presentation around the shared workflow, with no business store or retrieval implementation."""

    def __init__(self, client, dispatcher, state_store=None):
        self.client = client
        self.dispatcher = dispatcher
        self.state_store = state_store

    def run(self, request, *, session=None):
        actor_id = request.get("actor", {}).get("actor_id", "")
        session_id = request.get("session_id", "")
        if session is None and self.state_store is not None:
            session = self.state_store.load_session(actor_id, session_id)
        text = request["message"]
        direct = re.fullmatch(r"\s*(?:xin chào|chào|hi|hello)[!.?\s]*", text, re.I)
        rewrite = re.fullmatch(r"\s*(?:viết lại|rewrite|rephrase)(?:\s+(?:chuyên nghiệp|lịch sự|professional|politely))?\s*:\s*(.+)", text, re.I | re.S)
        if direct or rewrite:
            state = RunState(workflow="direct", request_id=request["request_id"], session_id=request["session_id"],
                             actor=request["actor"])
            if direct:
                result = finish(state, "completed", "GREETING", "Xin chào. Mình hỗ trợ chuyến công tác trên dữ liệu giả lập.")
                return self._record(request, session, self._metadata(result, "skipped", calls=0))
            generated = None
            try:
                generated = self.client.rewrite(rewrite.group(1))
                if not isinstance(generated.value, str) or not generated.value.strip() or len(generated.value) > 8000:
                    raise LLMError("llm_response", generated.retry_count)
                result = finish(state, "completed", "TEXT_REWRITE", generated.value)
                return self._record(request, session, self._metadata(result, "ok", generated=generated))
            except LLMError as err:
                result = finish(state, "needs_human", "LLM_UNAVAILABLE", "Chưa viết lại được nội dung; vui lòng thử lại.")
                return self._record(request, session, self._metadata(result, "fallback", generated=generated, error=err))

        result = run_agent(request, self.dispatcher, session=session)
        if result["status"] in {"rejected", "failed_validation"}:
            return self._record(request, session, self._metadata(result, "skipped", calls=0))
        highlights = highlights_for(result)
        if not highlights:
            return self._record(request, session, self._metadata(result, "skipped", calls=0))
        generated = None
        try:
            generated = self.client.choose_highlights(text, highlights)
            plan = PresentationPlan.model_validate(generated.value)
            ids = plan.highlight_ids
            if len(set(ids)) != len(ids) or any(key not in highlights for key in ids):
                raise ValueError("Unknown or duplicate highlight")
            # Only verified source sentences reach the final narrative. The model cannot change a fact or citation.
            narrative = " ".join([result["message"], *[highlights[key] for key in ids], result["next_action"] or ""]).strip()
            return self._record(request, session, self._metadata(result, "ok", generated=generated, narrative=narrative))
        except (LLMError, ValueError, TypeError) as err:
            if not isinstance(err, LLMError):
                err = LLMError("invalid_presentation_plan", generated.retry_count if generated else 0)
            return self._record(request, session, self._metadata(result, "fallback", generated=generated, error=err))

    def _record(self, request, session, result):
        if self.state_store is not None:
            actor_id = request.get("actor", {}).get("actor_id", "")
            session_id = request.get("session_id", "")
            self.state_store.save_run(request, result)
            self.state_store.save_session(actor_id, session_id, session or {})
        return result

    def _metadata(self, result, status, *, generated=None, error=None, calls=1, narrative=None):
        usage = generated if generated is not None else error
        result["llm"] = {"status": status, "provider_model": self.client.model_id, "calls": calls,
                         "message": narrative or result["message"],
                         "input_tokens": getattr(usage, "input_tokens", None),
                         "output_tokens": getattr(usage, "output_tokens", None),
                         "retry_count": error.retry_count if error else generated.retry_count if generated else 0,
                         "error_code": error.code if error else None}
        if calls:
            result["trace"].insert(-1, {"trace_id": result["run_id"] + ":llm", "run_id": result["run_id"],
                "step": result["steps"], "workflow": result["workflow"], "phase": "presentation", "action": "llm_presentation",
                "safe_args": {}, "observation_status": status, "retry_count": result["llm"]["retry_count"],
                "budget": {"model_calls": calls, "max_model_calls": 1}, "transition": "preserve_workflow_outcome",
                "outcome": result["status"], "timestamp": datetime.now(timezone.utc).isoformat()})
        return result
