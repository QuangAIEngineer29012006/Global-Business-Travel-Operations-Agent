"""
src/workflows.py - Ba workflow (pre_trip, in_trip, post_trip) cho Travel Operations Agent.

Orchestration DETERMINISTIC: bo LLM van chay dung. LLM (neu co) chi nen viet lai
narrative tu draft/response da co; khong quyet dinh routing, approval, so lieu, citation.

Tuan thu docs/agent-design/02..05:
  - request/response envelope (02), terminal outcomes (02 §4)
  - dispatcher(tool, args, ctx) -> {"ok", "data", "meta"} | {"ok": False, "error": {code, message, retryable}} (03)
  - draft tool: create_*_draft(payload, source_ids, idempotency_key) (03 §4)
  - du lieu theo schema trong 04 va fixture trong data/mock-systems

ctx truyen cho dispatcher: {"workflow", "actor": {"role","actor_id"}, "run_id", "request_id"}.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Optional

Dispatcher = Callable[[str, dict, dict], dict]

# --------------------------------------------------------------------------
# Terminal outcomes (02 §4)
# --------------------------------------------------------------------------
COMPLETED = "completed"
NEEDS_INPUT = "needs_input"
NEEDS_HUMAN = "needs_human"
AWAITING_APPROVAL = "awaiting_approval"
FAILED_VALIDATION = "failed_validation"
PARTIAL = "partial"
FAILED_DELIVERY = "failed_delivery"
REJECTED = "rejected"

PRE_TRIP, IN_TRIP, POST_TRIP = "pre_trip", "in_trip", "post_trip"

ROLES = {"employee", "travel_operations_reviewer", "approver"}
ALLOWED_DELIVERY = {"not_sent", "not_published"}

TRIP_ID_RE = re.compile(r"^TRIP-\d{4}-\d{3}$")
# 04 ghi RPT-YYYY-NNN nhung fixture dung EXP-YYYY-NNN -> chap nhan ca hai (can Quang chot)
REPORT_ID_RE = re.compile(r"^(?:EXP|RPT)-\d{4}-\d{3}$")

DISRUPTION_STATUSES = {"delayed", "cancelled", "canceled"}
EXPENSE_ITEM_REQUIRED = ("item_id", "category", "amount", "date", "receipt_present")
CHUNK_REQUIRED_META = ("chunk_id", "doc_id", "source", "section", "version", "category", "text")

PRE_TRIP_TOOLS = frozenset({"get_trip_request", "get_approval_status", "search_travel_policy",
                            "create_travel_checklist_draft", "request_approval"})
IN_TRIP_TOOLS = frozenset({"get_itinerary", "search_travel_policy",
                           "create_escalation_or_support_draft"})
POST_TRIP_TOOLS = frozenset({"get_expense_report", "calculate_expense_summary",
                             "search_travel_policy", "create_expense_review_draft"})

# --------------------------------------------------------------------------
# Untrusted-text heuristics
# --------------------------------------------------------------------------
# Chunk policy that su co cau "cam" (vd "khong cho phep Agent mua ve") -> regex chunk chi bat
# cau lenh chen vao, khong bat cau phat bieu quy tac.
INJECTION_CHUNK_RE = re.compile(
    r"(ignore (all |any )?(previous|prior|above)|disregard (all|the|previous)|system prompt|"
    r"you are now|approve (this|the) (trip|expense|report)|send (an )?e-?mail to|"
    r"bỏ qua (mọi|các|tất cả|những) (hướng dẫn|chỉ dẫn|quy tắc|chỉ thị)|"
    r"hãy (phê duyệt|duyệt) )", re.IGNORECASE)
# Input user: chi dung de GAN CO trong trace; khong bao gio dung de chon tool.
USER_FLAG_RE = re.compile(
    r"(ignore (all |any )?(previous|prior)|system prompt|bỏ qua (mọi|các|tất cả)|"
    r"(đặt|mua|book)\s+(lại\s+)?(vé|khách sạn|flight|hotel)|gửi (email|mail|tin nhắn)|send (an )?e-?mail|"
    r"phê duyệt (giúp|luôn|ngay)|hoàn tiền|refund)", re.IGNORECASE)
_SENSITIVE_KEY_RE = re.compile(r"(passport|visa_no|card|account|token|password|secret|address)", re.I)

ID_TOKEN_RE = re.compile(r"\b(?:TRIP|EXP|RPT)-[A-Za-z0-9-]*", re.IGNORECASE)
DISRUPTION_KW_RE = re.compile(r"(delay|cancel|disrupt|hoãn|trễ|hủy|huỷ|gián đoạn)", re.I)
PRETRIP_KW_RE = re.compile(r"(chuẩn bị|checklist|điều kiện|đủ điều kiện|công tác|prepare|ready|eligible)", re.I)
EXPENSE_KW_RE = re.compile(r"(expense|chi phí|báo cáo chi|rà soát báo cáo)", re.I)


# --------------------------------------------------------------------------
# Run state + trace (02 §5, 03 §7)
# --------------------------------------------------------------------------
class BudgetExceeded(Exception):
    pass


def _safe(args: Optional[dict]) -> dict:
    out: dict[str, Any] = {}
    for k, v in (args or {}).items():
        if _SENSITIVE_KEY_RE.search(k) or k in {"action_summary", "payload"}:
            out[k] = "[redacted]"
        elif isinstance(v, str):
            out[k] = v[:80]
        elif isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        else:
            out[k] = f"<{type(v).__name__}:{len(v) if hasattr(v, '__len__') else ''}>"
    return out


@dataclass
class RunState:
    workflow: str
    request_id: str = ""
    session_id: str = ""
    actor: dict = field(default_factory=dict)
    case_id: str = ""
    run_id: str = field(default_factory=lambda: f"RUN-{uuid.uuid4().hex[:8]}")
    phase: str = "start"
    step_count: int = 0
    max_steps: int = 12
    max_retries: int = 2
    retrieval_calls: int = 0
    max_retrieval: int = 6
    trace: list = field(default_factory=list)
    source_ids: set = field(default_factory=set)
    artifacts: list = field(default_factory=list)
    outcome: Optional[str] = None

    def log(self, action: str, args: Optional[dict] = None, status: str = "ok",
            transition: Optional[str] = None, retry: int = 0,
            observation_summary: Optional[dict] = None) -> None:
        n = len(self.trace) + 1
        self.trace.append({
            "trace_id": f"{self.run_id}:{n}", "case_id": self.case_id, "run_id": self.run_id,
            "step": self.step_count, "workflow": self.workflow, "phase": self.phase,
            "action": action, "safe_args": _safe(args), "observation_status": status,
            "observation_summary": observation_summary or {},
            "retry_count": retry, "transition": transition,
            "budget": {"steps": f"{self.step_count}/{self.max_steps}",
                       "retrieval": f"{self.retrieval_calls}/{self.max_retrieval}"},
            "outcome": self.outcome,
        })


class Executor:
    """Moi tool call di qua day: allowlist (phong thu them) -> budget -> dispatcher -> retry."""

    def __init__(self, dispatcher: Dispatcher, state: RunState, allowlist: frozenset):
        self.dispatcher, self.state, self.allowlist = dispatcher, state, allowlist

    def _ctx(self) -> dict:
        s = self.state
        return {"workflow": s.workflow, "actor": s.actor, "run_id": s.run_id, "request_id": s.request_id}

    @staticmethod
    def _observation_summary(result: dict) -> dict:
        """Keep audit metadata without copying business values or raw tool output into traces."""
        if result.get("ok") is True:
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
            summary = {"ok": True, "data_fields": sorted(data)[:30]}
            source = meta.get("source_system")
            if isinstance(source, str):
                summary["source_system"] = source[:80]
            return summary
        error = result.get("error") if isinstance(result.get("error"), dict) else {}
        code = error.get("code")
        return {"ok": False, "error_code": code[:60] if isinstance(code, str) else "INTERNAL_ERROR"}

    def call(self, tool: str, args: dict, phase: str) -> dict:
        st = self.state
        st.phase = phase
        if tool not in self.allowlist:
            st.log(tool, args, "denied:TOOL_NOT_ALLOWED", "rejected_before_execution")
            return {"ok": False, "error": {"code": "TOOL_NOT_ALLOWED", "retryable": False,
                                           "message": "Tool nằm ngoài allowlist của workflow."}}
        attempt = 0
        while True:
            if st.step_count >= st.max_steps:
                st.log(tool, args, "budget_exceeded", "stop", attempt)
                raise BudgetExceeded("max_steps")
            if tool == "search_travel_policy":
                if st.retrieval_calls >= st.max_retrieval:
                    st.log(tool, args, "budget_exceeded", "stop", attempt)
                    raise BudgetExceeded("max_retrieval")
                st.retrieval_calls += 1
            st.step_count += 1
            res = self.dispatcher(tool, args, self._ctx())
            observation = self._observation_summary(res)
            if res.get("ok"):
                st.log(tool, args, "ok", "next", attempt, observation)
                return res
            err = res.get("error", {})
            code = err.get("code", "INTERNAL_ERROR")
            if err.get("retryable") and attempt < st.max_retries:
                attempt += 1
                st.log(tool, args, f"error:{code}", f"retry {attempt}/{st.max_retries}", attempt, observation)
                continue
            st.log(tool, args, f"error:{code}", "no_retry", attempt, observation)
            return res


def finish(st: RunState, status: str, reason: str, message: str = "", *, data: Optional[dict] = None,
           evidence: Optional[list] = None, next_action: Optional[str] = None) -> dict:
    """Response envelope (02 §3) + reason_code + trace."""
    st.outcome, st.phase = status, "terminal"
    st.log("terminal", {"reason_code": reason}, "ok", "end")
    return {"request_id": st.request_id, "run_id": st.run_id, "workflow": st.workflow,
            "status": status, "reason_code": reason, "message": message, "data": data or {},
            "evidence": evidence or [], "artifacts": list(st.artifacts), "next_action": next_action,
            "steps": st.step_count, "trace": st.trace}


def _read_failure(st: RunState, res: dict, what: str) -> dict:
    code = res.get("error", {}).get("code", "INTERNAL_ERROR")
    if code == "NOT_FOUND":
        return finish(st, NEEDS_INPUT, f"{what}_NOT_FOUND", "Không tìm thấy bản ghi theo mã đã cung cấp.",
                      next_action="Vui lòng kiểm tra lại mã.")
    if code == "INVALID_ARGUMENT":
        return finish(st, FAILED_VALIDATION, f"{what}_INVALID", "Tham số không hợp lệ.")
    if code in ("UNAUTHORIZED", "TOOL_NOT_ALLOWED"):
        return finish(st, REJECTED, code, "Không có quyền truy cập bản ghi này trong phạm vi hiện tại.")
    # loi ha tang / tam thoi da het retry
    if st.artifacts:
        return finish(st, PARTIAL, code, "Một phần đã hoàn tất; bước sau gặp lỗi.")
    return finish(st, NEEDS_HUMAN, code, "Hệ thống mock tạm thời không khả dụng; cần xử lý thủ công.",
                  next_action="Thử lại sau hoặc chuyển reviewer.")


# --------------------------------------------------------------------------
# Retrieval + grounding
# --------------------------------------------------------------------------
def clean_evidence(chunks: list, category: str) -> tuple[list, list]:
    good, rejected = [], []
    for c in chunks or []:
        cid = c.get("chunk_id", "?")
        if any(not c.get(k) for k in CHUNK_REQUIRED_META):
            rejected.append({"chunk_id": cid, "reason": "missing_metadata"})
        elif c["category"] != category:
            rejected.append({"chunk_id": cid, "reason": "category_mismatch"})
        elif INJECTION_CHUNK_RE.search(c["text"]):
            rejected.append({"chunk_id": cid, "reason": "injection_like_text"})
        else:
            good.append(c)
    return good, rejected


def cite(c: dict) -> dict:
    out = {k: c[k] for k in ("chunk_id", "doc_id", "source", "section", "version")}
    if c.get("page"):
        out["page"] = c["page"]
    return out


def supports(c: dict, terms: list) -> bool:
    """Claim-to-evidence check toi thieu: chunk phai chua cac thuat ngu/so ma claim dua vao."""
    t = c["text"].lower()
    return all(x.lower() in t for x in terms)


def retrieve(ex: Executor, category: str, query: str, fallback_query: Optional[str] = None,
             k: int = 2) -> dict:
    """Bounded retrieval. Query rewrite toi da 1 lan/branch (fallback_query), co trace."""
    out = {"category": category, "evidence": [], "rejected": [], "conflicts": [], "error": None}
    queries = [query] + ([fallback_query] if fallback_query else [])
    for i, q in enumerate(queries):
        if i == 1:
            ex.state.log("query_rewrite", {"category": category, "query": q}, "ok", "rewrite_once")
        res = ex.call("search_travel_policy",
                      {"query": q[:200], "category": category, "max_results": k}, "retrieve")
        if not res.get("ok"):
            out["error"] = res.get("error", {}).get("code", "INTERNAL_ERROR")
            return out
        good, rejected = clean_evidence(res.get("data", {}).get("results", []), category)
        if rejected:
            out["rejected"] += rejected
            ex.state.log("evidence_filter",
                         {"rejected": "; ".join(f"{r['chunk_id']}:{r['reason']}" for r in rejected)},
                         "filtered", "excluded_from_evidence")
        if good:
            versions: dict = {}
            for c in good:
                versions.setdefault(c["doc_id"], set()).add(c["version"])
            out["conflicts"] = sorted(d for d, v in versions.items() if len(v) > 1)
            out["evidence"] = good
            return out
    return out


def _usable(f: dict) -> bool:
    return bool(f["evidence"]) and not f["conflicts"]


def _gap_reason(f: dict) -> str:
    if f["conflicts"]:
        return "version_conflict"
    if f["error"]:
        return f"retrieval_error:{f['error']}"
    return "no_evidence"


def _create_draft(ex: Executor, tool: str, payload: dict, source_ids: list, key: str) -> tuple:
    res = ex.call(tool, {"payload": payload, "source_ids": sorted(set(source_ids)),
                         "idempotency_key": key}, "draft")
    if not res.get("ok"):
        return None, res
    d = res["data"]
    ex.state.artifacts.append({k: d.get(k) for k in ("draft_id", "artifact_type", "status", "delivery_status")})
    return d, None


def _after_draft(st: RunState, d: Optional[dict], err: Optional[dict]) -> Optional[dict]:
    """Tra ve response loi neu draft that bai / delivery khong trung thuc; None neu OK."""
    if err:
        code = err.get("error", {}).get("code", "INTERNAL_ERROR")
        return finish(st, PARTIAL, "DRAFT_FAILED", "Đã thu thập dữ kiện nhưng tạo draft thất bại.",
                      data={"error_code": code}, next_action="Thử lại (idempotent) hoặc chuyển reviewer.")
    ds = d.get("delivery_status")
    if ds == "failed_delivery":
        return finish(st, FAILED_DELIVERY, "DELIVERY_SIMULATION_FAILED",
                      "Draft đã tạo nhưng mô phỏng delivery thất bại; không có gì được gửi.")
    if ds not in ALLOWED_DELIVERY:
        return finish(st, FAILED_VALIDATION, "UNEXPECTED_DELIVERY_STATUS",
                      "Draft trả delivery_status không hợp lệ; dừng để kiểm tra.")
    return None


# --------------------------------------------------------------------------
# Workflow: pre_trip
# --------------------------------------------------------------------------
def _missing_required(trip: dict) -> list:
    req = trip.get("required_fields") or "destination|dates|purpose"
    names = req if isinstance(req, list) else str(req).split("|")
    missing = []
    for n in (x.strip() for x in names):
        if not n:
            continue
        if n == "dates":
            if not (trip.get("start_date") and trip.get("end_date")):
                missing.append("dates")
        elif not trip.get(n):
            missing.append(n)
    return missing


def workflow_pre_trip(ex: Executor, trip_id: str) -> dict:
    st = ex.state
    r = ex.call("get_trip_request", {"trip_id": trip_id}, "fetch_trip")
    if not r.get("ok"):
        return _read_failure(st, r, "TRIP")
    trip = r["data"]
    st.source_ids.add(trip_id)
    ts = trip.get("travel_status")

    if ts in ("cancelled", "rejected"):
        return finish(st, NEEDS_HUMAN, f"TRIP_{ts.upper()}",
                      f"Chuyến đi đang ở trạng thái {ts}; không tạo checklist.",
                      data={"travel_status": ts}, next_action="Chuyển reviewer xem xét.")
    if ts in ("in_progress", "completed"):
        return finish(st, FAILED_VALIDATION, "TRIP_NOT_PRE_TRIP",
                      f"Chuyến đi ở trạng thái {ts}, không thuộc giai đoạn trước chuyến đi.",
                      data={"travel_status": ts})
    missing = _missing_required(trip)
    if missing:
        return finish(st, NEEDS_INPUT, "MISSING_REQUIRED_FIELDS",
                      "Yêu cầu chuyến đi còn thiếu trường bắt buộc; không suy đoán.",
                      data={"missing_fields": missing},
                      next_action="Vui lòng bổ sung: " + ", ".join(missing))

    a = ex.call("get_approval_status", {"trip_id": trip_id}, "fetch_approval")
    if a.get("ok"):
        approval, approval_id = a["data"].get("status", "unknown"), a["data"].get("approval_id")
        if approval_id:
            st.source_ids.add(approval_id)
    elif a.get("error", {}).get("code") == "NOT_FOUND":
        approval, approval_id = "none", None            # chua co approval record
    else:
        return _read_failure(st, a, "APPROVAL")

    if approval == "rejected":
        return finish(st, NEEDS_HUMAN, "APPROVAL_REJECTED", "Approval đã bị từ chối; không tạo checklist.",
                      data={"approval_status": approval}, next_action="Chuyển reviewer xem xét.")
    if ts == "approved" and approval != "approved":     # approval system moi la nguon dung
        return finish(st, NEEDS_HUMAN, "APPROVAL_STATUS_MISMATCH",
                      "Trạng thái chuyến đi và approval system không khớp; không xác nhận đã duyệt.",
                      data={"travel_status": ts, "approval_status": approval},
                      next_action="Reviewer đối chiếu nguồn approval.")

    dest, purpose = trip["destination"], trip["purpose"]
    plan = [("travel", f"danh sách kiểm tra trước chuyến đi {dest} {purpose}", "danh sách kiểm tra trước chuyến đi", 2, True),
            ("visa", f"điều kiện nhập cảnh giấy tờ {dest}", "điều kiện nhập cảnh giấy tờ", 2, True),
            ("insurance", "phạm vi bảo hiểm", None, 1, False)]
    if approval != "approved":
        plan.append(("approval", "quyết định đang chờ phê duyệt", None, 1, False))
    findings = []
    for cat, q, fb, k, required in plan:
        f = retrieve(ex, cat, q, fb, k)
        f["required"] = required
        findings.append(f)

    guidance, gaps, evidence = [], [], []
    for f in findings:
        if _usable(f):
            for c in f["evidence"]:
                guidance.append({"category": f["category"], "text": c["text"], "citation": cite(c)})
                evidence.append(cite(c))
                st.source_ids.add(c["chunk_id"])
        else:
            gaps.append({"category": f["category"], "reason": _gap_reason(f), "required": f["required"]})

    facts = [f"Chuyến {trip_id}: {dest}, {trip['start_date']} đến {trip['end_date']}, mục đích: {purpose}.",
             f"Trạng thái approval (từ approval system): {approval}."]
    payload = {"trip": {k: trip.get(k) for k in ("trip_id", "destination", "start_date", "end_date",
                                                  "purpose", "travel_status")},
               "approval": {"status": approval, "approval_id": approval_id},
               "observed_facts": facts, "policy_guidance": guidance, "limitations": gaps}
    d, err = _create_draft(ex, "create_travel_checklist_draft", payload, list(st.source_ids),
                           f"{st.request_id}:pre_trip:{trip_id}:travel_checklist")
    bad = _after_draft(st, d, err)
    if bad:
        return bad

    req_gaps = [g for g in gaps if g["required"]]
    data = {"approval_status": approval, "limitations": gaps}
    if approval == "none":
        s, rc, msg, nxt = NEEDS_HUMAN, "NO_APPROVAL_RECORD", "Chưa có bản ghi approval; không thể xem là đã duyệt.", \
            "Tạo yêu cầu phê duyệt (mô phỏng) hoặc chuyển reviewer."
    elif req_gaps:
        s, rc, msg, nxt = NEEDS_HUMAN, "POLICY_EVIDENCE_INSUFFICIENT", \
            "Thiếu hoặc xung đột evidence policy cho một số mục bắt buộc; checklist ghi rõ phần chưa xác minh.", \
            "Reviewer xác minh các mục chưa có evidence."
    elif approval == "pending":
        s, rc, msg, nxt = AWAITING_APPROVAL, "APPROVAL_PENDING", \
            "Đã tạo checklist draft. Yêu cầu đang chờ phê duyệt, chưa được duyệt.", "Chờ người phê duyệt quyết định."
    elif approval == "approved":
        s, rc, msg, nxt = COMPLETED, "CHECKLIST_READY", "Đã tạo checklist draft (chưa gửi).", None
    else:
        s, rc, msg, nxt = NEEDS_HUMAN, "APPROVAL_STATUS_UNKNOWN", "Trạng thái approval không xác định.", \
            "Reviewer kiểm tra approval."
    return finish(st, s, rc, msg, data=data, evidence=evidence, next_action=nxt)


# --------------------------------------------------------------------------
# Workflow: in_trip
# --------------------------------------------------------------------------
def extract_disruptions(itin: dict) -> list:
    out = []
    for seg in itin.get("segments", []):
        s = (seg.get("status") or "").lower()
        if s in DISRUPTION_STATUSES:
            out.append({"segment_id": seg.get("segment_id"), "type": seg.get("type"),
                        "origin": seg.get("origin"), "destination": seg.get("destination"),
                        "status": "cancelled" if s.startswith("cancel") else "delayed",
                        "note": seg.get("disruption_note")})
    top = (itin.get("disruption_status") or "none").lower()
    if not out and top in DISRUPTION_STATUSES:        # chi top-level bao disruption
        out.append({"segment_id": None, "type": None, "origin": None, "destination": None,
                    "status": "cancelled" if top.startswith("cancel") else "delayed",
                    "note": "disruption_status cấp itinerary; không có segment khớp"})
    return out


def workflow_in_trip(ex: Executor, trip_id: str) -> dict:
    st = ex.state
    r = ex.call("get_itinerary", {"trip_id": trip_id}, "fetch_itinerary")
    if not r.get("ok"):
        return _read_failure(st, r, "ITINERARY")
    itin = r["data"]
    st.source_ids.update({trip_id, itin.get("itinerary_id", trip_id)})
    disruptions = extract_disruptions(itin)
    if not disruptions:
        return finish(st, COMPLETED, "NO_DISRUPTION_OBSERVED",
                      "Itinerary không ghi nhận delay/cancel nên không xác nhận được sự cố từ nguồn này.",
                      data={"disruption_status": itin.get("disruption_status")})
    st.source_ids.update(d["segment_id"] for d in disruptions if d["segment_id"])
    cancelled = any(d["status"] == "cancelled" for d in disruptions)

    f = retrieve(ex, "insurance", "chuyển cấp khi lịch trình gián đoạn ghi chú chuyển cấp",
                 "lịch trình gián đoạn", 2)
    sup = [c for c in f["evidence"] if supports(c, ["chuyển cấp"])] if not f["conflicts"] else []
    guidance_ok = bool(sup)
    guidance = [{"text": c["text"], "citation": cite(c)} for c in f["evidence"]] if guidance_ok and not f["conflicts"] else []
    evidence = [g["citation"] for g in guidance]
    st.source_ids.update(g["citation"]["chunk_id"] for g in guidance)
    limitations = [] if guidance_ok else [{"category": "insurance", "reason": _gap_reason(f) if not f["evidence"] or f["conflicts"] else "evidence_does_not_support_claim"}]

    payload = {"itinerary": {k: itin.get(k) for k in ("itinerary_id", "trip_id", "disruption_status", "last_updated")},
               "observed_facts": disruptions,            # tu itinerary
               "policy_guidance": guidance,              # tu policy, tach rieng
               "limitations": limitations,
               "actions_not_taken": ["rebooking", "hotel_booking", "payment", "contact_carrier"],
               "note": "Chỉ là bản nháp ghi chú chuyển cấp; chưa gửi cho ai."}
    d, err = _create_draft(ex, "create_escalation_or_support_draft", payload, list(st.source_ids),
                           f"{st.request_id}:in_trip:{trip_id}:disruption_escalation")
    bad = _after_draft(st, d, err)
    if bad:
        return bad
    data = {"disruptions": disruptions, "limitations": limitations}
    if cancelled:
        return finish(st, NEEDS_HUMAN, "CANCELLED_REQUIRES_HUMAN",
                      "Chuyến bay bị hủy: Agent không tự đổi chuyến; đã tạo escalation draft cho nhân viên phụ trách.",
                      data=data, evidence=evidence, next_action="Chuyển nhân viên Travel Operations xử lý.")
    if not guidance_ok:
        return finish(st, NEEDS_HUMAN, "POLICY_INSUFFICIENT",
                      "Policy không đủ chi tiết cho tình huống này; đã tạo draft ghi rõ giới hạn.",
                      data=data, evidence=evidence, next_action="Reviewer quyết định bước tiếp theo.")
    return finish(st, COMPLETED, "ESCALATION_DRAFT_READY",
                  "Đã tạo ghi chú chuyển cấp (draft, chưa gửi). Dữ kiện lấy từ itinerary; hướng dẫn lấy từ policy có trích dẫn.",
                  data=data, evidence=evidence)


# --------------------------------------------------------------------------
# Workflow: post_trip
# --------------------------------------------------------------------------
def _dec(x: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError):
        return None


def structural_problems(items: list) -> list:
    problems = []
    for it in items:
        miss = [f for f in EXPENSE_ITEM_REQUIRED if it.get(f) is None or it.get(f) == ""]
        if miss:
            problems.append({"item_id": it.get("item_id"), "issue": "missing_fields", "fields": miss})
        elif _dec(it["amount"]) is None:
            problems.append({"item_id": it["item_id"], "issue": "invalid_amount"})
    return problems


# rule -> (query, fallback, terms phai xuat hien trong chunk: khop voi nguong cua tool)
EXPENSE_RULES = {
    "missing_receipt": ("chứng từ hóa đơn lưu trú", "quy định chi phí chứng từ", ["chứng từ", "75"]),
    "meals_daily_over_threshold": ("chi phí ăn uống vượt ngưỡng giải trình", "quy định chi phí ăn uống", ["ăn uống", "120"]),
}


def workflow_post_trip(ex: Executor, report_id: str) -> dict:
    st = ex.state
    r = ex.call("get_expense_report", {"report_id": report_id}, "fetch_report")
    if not r.get("ok"):
        return _read_failure(st, r, "REPORT")
    report = r["data"]
    items = report.get("line_items") or []
    st.source_ids.add(report_id)
    if not items:
        return finish(st, NEEDS_INPUT, "EMPTY_REPORT", "Báo cáo chi phí chưa có khoản chi nào.",
                      next_action="Vui lòng bổ sung line items.")
    prob = structural_problems(items)
    if prob:
        return finish(st, NEEDS_INPUT, "MISSING_EXPENSE_FIELDS",
                      "Một số khoản chi thiếu trường bắt buộc; không suy đoán.", data={"problems": prob},
                      next_action="Vui lòng bổ sung các trường còn thiếu.")

    s = ex.call("calculate_expense_summary", {"report_id": report_id}, "calculate")
    if not s.get("ok"):
        return _read_failure(st, s, "SUMMARY")
    summary = s["data"]                                   # tong/co: do tool tinh, khong tinh tay
    flags = list(summary.get("flags", []))
    local_total = sum((_dec(i["amount"]) for i in items), Decimal("0"))
    tool_total = _dec(summary.get("total"))
    mismatch = tool_total is None or tool_total != local_total

    rules = ["missing_receipt"] + (["meals_daily_over_threshold"] if any(i["category"] == "meals" for i in items) else [])
    notes, evidence, limitations = [], [], []
    for rule in rules:
        q, fb, terms = EXPENSE_RULES[rule]
        f = retrieve(ex, "expense", q, fb, 2)
        sup = [c for c in f["evidence"] if supports(c, terms)] if not f["conflicts"] else []
        if sup:
            for c in sup:
                notes.append({"rule": rule, "text": c["text"], "citation": cite(c)})
                evidence.append(cite(c))
                st.source_ids.add(c["chunk_id"])
        else:
            limitations.append({"rule": rule, "reason": _gap_reason(f) if not f["evidence"] or f["conflicts"]
                                else "evidence_does_not_support_threshold"})

    payload = {"report": {k: report.get(k) for k in ("report_id", "trip_id", "traveler_id", "status",
                                                      "currency", "receipts_status")},
               "summary": summary, "flags": flags, "policy_notes": notes, "limitations": limitations,
               "reviewer_items": [{"item_ids": f.get("item_ids"), "code": f.get("code")} for f in flags],
               "disclaimer": "Chỉ nêu dữ kiện và evidence policy; không kết luận hoàn tiền hoặc phê duyệt."}
    d, err = _create_draft(ex, "create_expense_review_draft", payload, list(st.source_ids),
                           f"{st.request_id}:post_trip:{report_id}:expense_review")
    bad = _after_draft(st, d, err)
    if bad:
        return bad
    data = {"summary": summary, "flags": flags, "limitations": limitations}
    if mismatch:
        return finish(st, NEEDS_HUMAN, "TOTAL_MISMATCH",
                      "Tổng từ tool không khớp tổng line items; cần reviewer kiểm tra.", data=data,
                      evidence=evidence, next_action="Reviewer đối chiếu số liệu.")
    if flags or limitations:
        return finish(st, NEEDS_HUMAN, "FLAGS_FOR_REVIEW" if flags else "POLICY_EVIDENCE_INSUFFICIENT",
                      "Đã tạo review draft: có mục cần reviewer kiểm tra. Không kết luận hoàn tiền/phê duyệt.",
                      data=data, evidence=evidence, next_action="Reviewer xem các mục bị gắn cờ.")
    return finish(st, COMPLETED, "NO_ISSUE_FOUND",
                  "Đã tạo review draft: không có cờ theo quy tắc ngưỡng đã cấu hình. Chưa phải quyết định hoàn tiền/phê duyệt.",
                  data=data, evidence=evidence)


# --------------------------------------------------------------------------
# Router + entrypoint
# --------------------------------------------------------------------------
WORKFLOWS = {
    PRE_TRIP: (workflow_pre_trip, PRE_TRIP_TOOLS, TRIP_ID_RE),
    IN_TRIP: (workflow_in_trip, IN_TRIP_TOOLS, TRIP_ID_RE),
    POST_TRIP: (workflow_post_trip, POST_TRIP_TOOLS, REPORT_ID_RE),
}


def route(message: str, context: dict, session: Optional[dict] = None) -> tuple:
    """Router deterministic. Text user chi chon workflow + ID, KHONG bao gio chon tool."""
    tokens = [m.group(0).upper() for m in ID_TOKEN_RE.finditer(message)]
    trips = [t for t in tokens if t.startswith("TRIP")]
    reps = [t for t in tokens if not t.startswith("TRIP")]
    rid = context.get("report_id") or (reps[0] if reps else None)
    if rid or EXPENSE_KW_RE.search(message):
        return POST_TRIP, rid
    tid = context.get("trip_id") or (trips[0] if trips else None)
    disrupt = bool(DISRUPTION_KW_RE.search(message))
    if not tid and (disrupt or PRETRIP_KW_RE.search(message)):
        tid = (session or {}).get("active_trip_id")     # chi la ngu canh session; facts doc lai tu mock
    if not tid:
        return "unrouted", None
    return (IN_TRIP if disrupt else PRE_TRIP), tid


def run_agent(request: dict, dispatcher: Dispatcher, *, session: Optional[dict] = None,
              case_id: str = "", max_steps: int = 12, max_retries: int = 2, max_retrieval: int = 6) -> dict:
    actor = request.get("actor") or {}
    message = str(request.get("message") or "")[:2000]
    context = request.get("context") or {}
    wf, ident = route(message, context, session)
    st = RunState(workflow=wf, request_id=request.get("request_id") or f"REQ-{uuid.uuid4().hex[:8]}",
                  session_id=request.get("session_id", ""), actor={"role": actor.get("role"),
                  "actor_id": actor.get("actor_id")}, case_id=case_id, max_steps=max_steps,
                  max_retries=max_retries, max_retrieval=max_retrieval)
    if USER_FLAG_RE.search(message):
        st.log("input_check", {"flag": "injection_like_input"}, "flagged", "treated_as_data_only")
    if actor.get("role") not in ROLES or not actor.get("actor_id"):
        return finish(st, REJECTED, "INVALID_ACTOR", "Thiếu hoặc sai vai trò/actor.")
    if wf == "unrouted" or not ident:
        return finish(st, NEEDS_INPUT, "MISSING_ID", "Cần mã chuyến đi hoặc mã báo cáo chi phí.",
                      next_action="Vui lòng cung cấp trip_id (TRIP-YYYY-NNN) hoặc report_id (EXP-YYYY-NNN).")
    fn, allow, id_re = WORKFLOWS[wf]
    if not id_re.match(str(ident)):
        return finish(st, FAILED_VALIDATION, "INVALID_ID_FORMAT", "Mã không đúng định dạng.",
                      data={"id": str(ident)[:40]})
    ex = Executor(dispatcher, st, allow)
    try:
        res = fn(ex, ident)
    except BudgetExceeded as e:
        res = finish(st, PARTIAL, "BUDGET_EXCEEDED", "Đạt giới hạn ngân sách bước/retrieval; dừng an toàn.",
                     data={"limit": str(e)}, next_action="Chuyển reviewer hoặc thử lại.")
    if session is not None and wf in (PRE_TRIP, IN_TRIP) and \
            res["status"] not in (FAILED_VALIDATION, REJECTED) and not res["reason_code"].endswith("_NOT_FOUND"):
        session["active_trip_id"] = ident
    return res
