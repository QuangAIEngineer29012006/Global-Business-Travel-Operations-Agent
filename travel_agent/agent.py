import re
import time

from .dispatcher import Dispatcher
from .llm import FakeToolModel, GeminiToolModel, LLMError, POLICY_QUERIES, observe
from .models import Draft, RunState
from .policy import grounded_claim
from .safety import unsafe_user_request
from .storage import Store, digest
from .text import normalize
from .tools import MockTools


def classify(message):
    text = normalize(message)
    if text in {"hi", "hello", "xin chao", "chao", "hey"}:
        return "direct"
    if re.search(r"\b(viet lai|rewrite|rephrase)\b", text):
        return "rewrite"
    if re.search(r"\b(expense|chi phi|bao cao chi|exp \d{4})\b", text):
        return "expense"
    if re.search(r"\b(delay|delayed|cancelled|canceled|disruption|bi huy|tre chuyen|cham chuyen|ho tro khan)\b", text):
        return "in_trip"
    if re.search(r"\b(trang thai|status|da duyet|approval status|hanh trinh|itinerary)\b", text):
        return "status"
    if re.search(r"\b(policy|chinh sach|quy dinh)\b", text) and "trip " not in text:
        return "policy"
    return "pre_trip"


def policy_category(message):
    text = normalize(message)
    for category, cues in {"expense": ("chi phi", "expense", "chung tu"), "visa": ("visa", "nhap canh"),
                           "insurance": ("bao hiem", "insurance"), "approval": ("phe duyet", "approval", "duyet")}.items():
        if any(c in text for c in cues):
            return category
    return "travel"


def bind_ids(request, context):
    ids = {k: getattr(request, k) for k in ("trip_id", "report_id") if getattr(request, k)}
    tokens = re.findall(r"\b(?:TRIP|EXP)(?:[-_][A-Z0-9_-]+|\d[A-Z0-9_-]*)", request.message.upper())
    for prefix, field in [("TRIP", "trip_id"), ("EXP", "report_id")]:
        candidates = {t for t in tokens if t.startswith(prefix)}
        if any(not re.fullmatch(prefix + r"-\d{4}-\d{3}", t) for t in candidates):
            return ids, "invalid_identifier_format"
        if len(candidates) > 1 or (field in ids and candidates and ids[field] not in candidates):
            return ids, "ambiguous_identifier"
        if candidates:
            ids[field] = next(iter(candidates))
        elif field not in ids and context.get("active_" + field):
            ids[field] = context["active_" + field]
    return ids, None


class TravelAgent:
    def __init__(self, settings, store=None, model=None, tools=None):
        self.settings = settings
        self.store = store or Store(settings.workspace)
        self.tools = tools or MockTools(self.store)
        self.dispatcher = Dispatcher(self.tools, settings)
        self.model = model or (FakeToolModel() if settings.provider == "fake" else GeminiToolModel(settings))

    @staticmethod
    def _search_or_stop(state, categories):
        searched = {item["arguments"]["category"]: item["result"]["data"]
                    for item in state.safe_tool_results if item["tool"] == "search_travel_policy" and item["result"]["ok"]}
        for category in categories:
            if category not in searched:
                return "search_travel_policy", category
            if not searched[category]["chunks"]:
                return "terminal", ("needs_human", "insufficient_evidence")
        return None

    @staticmethod
    def _approval_transition(state, request):
        approval = state.latest("get_approval_status")
        if not approval:
            return "get_approval_status", None
        status = approval["status"]
        if status == "approved":
            return None
        if status == "not_requested" and state.workflow == "pre_trip":
            explicit = re.search(r"\b(request approval|yeu cau phe duyet)\b", normalize(request.message))
            if explicit and not state.latest("request_approval"):
                return "request_approval", None
        return "terminal", ("awaiting_approval" if status in {"pending", "not_requested"} else "needs_human",
                            "approval_" + status)

    def _next(self, state, request):
        workflow = state.workflow
        if workflow == "status":
            text = normalize(request.message)
            tool = ("get_approval_status" if any(t in text for t in ("duyet", "approval")) else
                    "get_itinerary" if any(t in text for t in ("hanh trinh", "itinerary")) else "get_trip_request")
            return ("terminal", ("completed", "source_status")) if state.latest(tool) else (tool, None)
        if workflow == "policy":
            return self._search_or_stop(state, [policy_category(request.message)]) or ("terminal", ("completed", "policy_evidence"))
        if workflow in {"pre_trip", "in_trip"}:
            trip = state.latest("get_trip_request")
            if not trip:
                return "get_trip_request", None
            if trip["status"] == "cancelled":
                return "terminal", ("needs_human", "trip_cancelled")
            if workflow == "pre_trip":
                if any(not trip[k] for k in ("destination", "start_date", "end_date", "purpose")):
                    return "terminal", ("needs_input", "missing_trip_fields")
                if not state.latest("get_traveler_profile"):
                    return "get_traveler_profile", None
                blocked = self._approval_transition(state, request)
                if blocked:
                    return blocked
                search = self._search_or_stop(state, ["travel", "approval", "visa", "insurance"])
                if search:
                    return search
                validation = state.latest("validate_trip_requirements")
                if not validation:
                    return "validate_trip_requirements", None
                if validation["missing_fields"]:
                    return "terminal", ("needs_input", "missing_trip_fields")
                if validation["reviewer_flags"]:
                    return "terminal", ("needs_human", "trip_validation_flags")
                if not state.latest("create_travel_checklist_draft"):
                    return "create_travel_checklist_draft", None
                return "terminal", ("completed", "checklist_ready")
            itinerary = state.latest("get_itinerary")
            if not itinerary:
                return "get_itinerary", None
            if itinerary["disruption"] == "none":
                return "terminal", ("completed", "no_disruption_observed")
            blocked = self._approval_transition(state, request)
            if blocked:
                return blocked
            search = self._search_or_stop(state, ["travel"])
            if search:
                return search
            if not state.latest("create_escalation_or_support_draft"):
                return "create_escalation_or_support_draft", None
            return "terminal", ("needs_human" if itinerary["disruption"] == "cancelled" else "completed", "support_draft_ready")
        report = state.latest("get_expense_report")
        if not report:
            return "get_expense_report", None
        blocked = self._approval_transition(state, request)
        if blocked:
            return blocked
        if not state.latest("calculate_expense_summary"):
            return "calculate_expense_summary", None
        search = self._search_or_stop(state, ["expense"])
        if search:
            return search
        valid = state.latest("validate_expense_requirements")
        if not valid:
            return "validate_expense_requirements", None
        if not state.latest("create_expense_review_draft"):
            return "create_expense_review_draft", None
        outcome = "needs_input" if valid["missing_fields"] else "needs_human" if valid["reviewer_flags"] else "completed"
        return "terminal", (outcome, "expense_review_ready")

    def run(self, session, request):
        fingerprint = digest(request.model_dump(exclude={"case_id"}))
        rid, replayed = self.store.begin_run(session, request.request_id, fingerprint)
        if replayed is not None:
            return {**replayed, "replayed": True}
        workflow = request.workflow or classify(request.message)
        ids, error = bind_ids(request, session["context"])
        state = RunState(run_id=rid, case_id=request.case_id, user_id=session["user_id"], session_id=session["session_id"],
                         role=session["role"], request_id=request.request_id, workflow=workflow,
                         requested_ids=ids, max_steps=self.settings.max_steps)
        if unsafe_user_request(request.message):
            return self._finish(state, "needs_human", "unsafe_request")
        if error:
            return self._finish(state, "failed_validation", error)
        if workflow in {"direct", "rewrite"}:
            text = "Xin chào. Mình hỗ trợ checklist, sự cố hành trình và rà soát chi phí bằng dữ liệu training."
            if workflow == "rewrite":
                if ":" not in request.message:
                    return self._finish(state, "needs_input", "missing_rewrite_text")
                text = " ".join(request.message.split(":", 1)[1].split())
            return self._finish(state, "completed", "direct_response", direct_text=text)
        field = "report_id" if workflow == "expense" else "trip_id"
        if workflow != "policy" and field not in ids:
            return self._finish(state, "needs_input", "missing_" + field)
        history = []
        while state.outcome is None:
            name, parameter = self._next(state, request)
            if name == "terminal":
                return self._finish(state, *parameter)
            state.phase = "policy:" + parameter if name == "search_travel_policy" else name
            if state.step_count >= state.max_steps or state.model_calls >= self.settings.max_model_calls:
                return self._finish(state, "budget_exceeded", "run_budget_exceeded")
            identifiers = dict(state.requested_ids)
            for tool in ("get_trip_request", "get_expense_report"):
                fact = state.latest(tool)
                if fact:
                    identifiers.update({key: fact[key] for key in ("trip_id", "report_id", "traveler_id") if key in fact})
            context = {"user_message": request.message, "phase": state.phase, "identifiers": identifiers,
                       "category": parameter, "query_hint": POLICY_QUERIES.get(parameter),
                       "policy_question": request.message[:400] if workflow == "policy" else None}
            declarations = [self.dispatcher.registry[name].declaration()]
            state.model_calls += 1
            try:
                proposal = self.model.propose(declarations, context, history)
            except LLMError as err:
                state.retry_count += err.retry_count
                return self._finish(state, "partial" if state.artifacts else "tool_failed", err.code)
            state.retry_count += proposal.retry_count
            result = None
            for attempt in range(self.settings.tool_retries + 1):
                result = self.dispatcher.execute(state, proposal.call, {name})
                state.trace[-1].update(input_tokens=proposal.input_tokens, output_tokens=proposal.output_tokens)
                if result.ok or not result.error.retryable or attempt == self.settings.tool_retries:
                    break
                state.retry_count += 1
                state.trace[-1]["transition"] = "retry_same_call"
            observe(history, proposal, result)
            if not result.ok:
                return self._tool_failure(state, result)
            if proposal.call.name.startswith("create_"):
                state.artifacts.append(Draft.model_validate(result.data))
            if proposal.call.name in {"get_trip_request", "get_expense_report"}:
                updated = dict(session["context"])
                updated.update({"active_" + key: result.data[key] for key in ("trip_id", "report_id") if key in result.data})
                self.store.update_context(state.session_id, updated)
            state.trace[-1]["transition"] = state.phase + "->next"
        raise RuntimeError("Unreachable terminal state")

    def _tool_failure(self, state, result):
        code = result.error.code
        if code in {"budget_exceeded", "retrieval_budget_exceeded"}:
            outcome = "budget_exceeded"
        elif code == "not_found":
            outcome = "needs_input"
        elif code in {"policy_version_conflict", "insufficient_evidence", "ungrounded_policy_rule",
                      "insufficient_currency_or_category_policy", "approval_required"}:
            outcome = "needs_human"
        elif code in {"unknown_tool", "tool_not_allowed_in_phase", "role_not_allowed", "invalid_arguments",
                      "identifier_out_of_scope", "arguments_too_large", "session_revoked"}:
            outcome = "failed_validation"
        elif result.meta.side_effect_may_have_occurred:
            outcome = "partial" if state.artifacts else "failed_delivery"
        else:
            outcome = "partial" if state.artifacts else "tool_failed"
        return self._finish(state, outcome, code)

    def _finish(self, state, outcome, reason, direct_text=None):
        state.outcome = outcome
        previous = state.phase
        state.phase = "terminal"
        state.trace.append({"case_id": state.case_id, "run_id": state.run_id, "phase": "terminal", "action": "finish",
                            "safe_arguments": {}, "observation_status": reason, "executed": False,
                            "transition": previous + "->" + outcome,
                            "budget": {"steps": state.step_count, "max_steps": state.max_steps,
                                       "model_calls": state.model_calls, "retrieval_calls": state.retrieval_calls},
                            "outcome": outcome})
        claims = [grounded_claim(c) for c in state.chunks()]
        citations = list({c["citation"]["chunk_id"]: c["citation"] for c in claims}.values())
        facts = {name: state.latest(name) for name in ("get_trip_request", "get_traveler_profile", "get_itinerary",
                 "get_approval_status", "request_approval", "get_expense_report", "calculate_expense_summary",
                 "validate_trip_requirements", "validate_expense_requirements") if state.latest(name) is not None}
        preferences = self.store.preferences(state.user_id)
        labels = {"completed": "Đã hoàn tất xử lý trong sandbox.", "needs_input": "Cần bổ sung thông tin.",
                  "needs_human": "Cần người phụ trách xem xét.", "awaiting_approval": "Đang chờ phê duyệt mô phỏng.",
                  "failed_validation": "Yêu cầu không vượt qua kiểm tra.", "budget_exceeded": "Đã dừng vì hết budget.",
                  "tool_failed": "Đã dừng vì tool/model gặp lỗi.", "partial": "Chỉ hoàn tất một phần; cần kiểm tra draft đã tạo.",
                  "failed_delivery": "Chưa xác nhận được kết quả tạo draft; không báo hoàn tất."}
        summary = labels[outcome] if preferences.get("response_language", "vi") == "vi" else "Training workflow outcome: " + outcome + "."
        if state.artifacts:
            summary += " Draft: " + ", ".join(a.draft_id for a in state.artifacts) + "; delivery_status=not_sent."
        approval = facts.get("get_approval_status")
        if approval:
            summary += " Approval source: " + approval["status"] + "."
        if direct_text is not None:
            summary = direct_text
        response = {"summary": summary, "reason": reason, "facts": facts, "policy_claims": claims,
                    "citations": citations, "artifacts": [a.model_dump() for a in state.artifacts],
                    "delivery_status": "not_sent", "preferences_applied": preferences,
                    "interpretation_source": self.model.model_id, "training_only": True}
        payload = {"state": state.model_dump(), "response": response, "replayed": False}
        persisted = payload
        if state.workflow in {"direct", "rewrite"}:
            persisted = {**payload, "response": {**response, "summary": "[Direct response not persisted]"}}
        self.store.finish_run(state.run_id, persisted)
        return payload
