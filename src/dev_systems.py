"""
src/dev_systems.py - Mock systems + dispatcher TAM de chay/test workflow tren fixture that.

Doc truc tiep data/mock-systems (CSV/JSON/MD), KHONG sua fixture. Day la stand-in cho
dispatcher cua Quang (docs/agent-design/03): khi co ban chinh thuc, chi can thay doi tuong
dispatcher truyen vao run_agent(); workflows.py khong doi.

Thu tu kiem tra (03 §3): registry -> workflow allowlist -> role -> JSON Schema -> domain
(ID format, ton tai, actor scope) -> implementation. Budget do Executor trong workflows.py kiem.
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Callable, Optional

DEFAULT_DATA = Path(__file__).resolve().parents[1] / "data" / "mock-systems"
TRIP_ID = r"^TRIP-\d{4}-\d{3}$"
REPORT_ID = r"^(EXP|RPT)-\d{4}-\d{3}$"
RECEIPT_REQUIRED_OVER = Decimal("75")      # CHUNK-003 (gia lap)
MEALS_DAILY_REVIEW_OVER = Decimal("120")   # CHUNK-004 (gia lap)
RETRYABLE = {"TIMEOUT", "TOOL_UNAVAILABLE"}


def _ok(data: dict, source: str, read_only: bool = True) -> dict:
    return {"ok": True, "data": data, "meta": {"source_system": source, "read_only": read_only}}


def _err(code: str, msg: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": msg, "retryable": code in RETRYABLE}}


# ------------------------------------------------------------------ JSON Schema (toi gian)
def validate_schema(schema: dict, value, path: str = "$") -> Optional[str]:
    t = schema.get("type")
    py = {"string": str, "integer": int, "object": dict, "array": list}
    if t in py and (not isinstance(value, py[t]) or (t == "integer" and isinstance(value, bool))):
        return f"{path}: expected {t}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path}: not in enum"
    if t == "string":
        if "pattern" in schema and not re.match(schema["pattern"], value):
            return f"{path}: pattern mismatch"
        if len(value) > schema.get("maxLength", 10**6) or len(value) < schema.get("minLength", 0):
            return f"{path}: length out of bounds"
    if t == "integer" and not schema.get("minimum", -10**9) <= value <= schema.get("maximum", 10**9):
        return f"{path}: out of range"
    if t == "array":
        for i, v in enumerate(value):
            e = validate_schema(schema.get("items", {}), v, f"{path}[{i}]")
            if e:
                return e
    if t == "object":
        props = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in value:
                return f"{path}: missing {k}"
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(props)
            if extra:
                return f"{path}: unexpected field(s) {sorted(extra)}"
        for k, v in value.items():
            if k in props:
                e = validate_schema(props[k], v, f"{path}.{k}")
                if e:
                    return e
    return None


def _obj(**props):
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


S_TRIP = _obj(trip_id={"type": "string", "pattern": TRIP_ID})
S_REPORT = _obj(report_id={"type": "string", "pattern": REPORT_ID})
S_TRAVELER = _obj(traveler_id={"type": "string", "pattern": r"^EMP-\d{3}$"})
S_SEARCH = _obj(query={"type": "string", "minLength": 2, "maxLength": 200},
                category={"type": "string", "enum": ["travel", "expense", "visa", "insurance", "approval"]},
                max_results={"type": "integer", "minimum": 1, "maximum": 5})
S_DRAFT = _obj(payload={"type": "object"}, source_ids={"type": "array", "items": {"type": "string", "maxLength": 40}},
               idempotency_key={"type": "string", "minLength": 4, "maxLength": 120})

ALL_ROLES = {"employee", "travel_operations_reviewer", "approver"}
DRAFT_ROLES = {"employee", "travel_operations_reviewer"}
PRE, INT, POST = "pre_trip", "in_trip", "post_trip"


class MockSystems:
    def __init__(self, data_dir: Optional[Path] = None, *, extra_chunks: Optional[list] = None,
                 faults: Optional[dict] = None, always_fail: Optional[set] = None,
                 mutate: Optional[Callable] = None):
        d = Path(data_dir or DEFAULT_DATA)
        self.trips = {r["trip_id"]: r for r in self._csv(d / "travel-requests/travel_requests.csv")}
        self.profiles = {r["traveler_id"]: r for r in json.loads((d / "traveler-profiles/traveler_profiles.json").read_text("utf-8"))}
        self.itins = {r["trip_id"]: r for r in json.loads((d / "itineraries/itineraries.json").read_text("utf-8"))}
        self.approvals = self._csv(d / "approvals/approvals.csv")
        self.reports = {r["report_id"]: r for r in json.loads((d / "expenses/expense_reports.json").read_text("utf-8"))}
        self.chunks = self._load_policy(d / "policy-knowledge-base/documents") + list(extra_chunks or [])
        self.drafts: dict = {}              # idempotency_key -> draft record (in-memory sandbox)
        self.calls: list = []               # moi tool call toi implementation (de test)
        self.faults = {k: list(v) for k, v in (faults or {}).items()}
        self.always_fail = set(always_fail or ())
        if mutate:
            mutate(self)
        self.registry = {
            "get_trip_request": ({PRE, INT}, ALL_ROLES, S_TRIP, self.get_trip_request),
            "get_traveler_profile": ({PRE}, ALL_ROLES, S_TRAVELER, self.get_traveler_profile),
            "get_itinerary": ({INT}, ALL_ROLES, S_TRIP, self.get_itinerary),
            "get_approval_status": ({PRE}, ALL_ROLES, S_TRIP, self.get_approval_status),
            "search_travel_policy": ({PRE, INT, POST}, ALL_ROLES, S_SEARCH, self.search_travel_policy),
            "get_expense_report": ({POST}, ALL_ROLES, S_REPORT, self.get_expense_report),
            "calculate_expense_summary": ({POST}, ALL_ROLES, S_REPORT, self.calculate_expense_summary),
            "create_travel_checklist_draft": ({PRE}, DRAFT_ROLES, S_DRAFT, lambda a, ctx: self._draft("travel_checklist", a)),
            "create_escalation_or_support_draft": ({INT}, DRAFT_ROLES, S_DRAFT, lambda a, ctx: self._draft("disruption_escalation_note", a)),
            "create_expense_review_draft": ({POST}, DRAFT_ROLES, S_DRAFT, lambda a, ctx: self._draft("expense_review", a)),
        }

    # ---------------------------------------------------------------- loaders
    @staticmethod
    def _csv(p: Path) -> list:
        with p.open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    @staticmethod
    def _load_policy(folder: Path) -> list:
        chunks = []
        for md in sorted(folder.glob("*.md")):
            text = md.read_text("utf-8")
            m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
            meta = {}
            for line in m.group(1).splitlines():
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip().strip('"')
            for h in re.finditer(r"^## Chunk (CHUNK-\d+) — ([^\n]+)\n(.*?)(?=^## |\Z)", m.group(2), re.S | re.M):
                chunks.append({"chunk_id": h.group(1), "doc_id": meta["doc_id"], "source": meta["source"],
                               "section": h.group(2).strip(), "page": "", "version": meta["version"],
                               "category": meta["category"], "text": h.group(3).strip()})
        return chunks

    # ---------------------------------------------------------------- access guard
    @staticmethod
    def _scope_ok(ctx: dict, owner_id: str) -> bool:
        a = ctx.get("actor", {})
        return a.get("role") in ("travel_operations_reviewer", "approver") or a.get("actor_id") == owner_id

    # ---------------------------------------------------------------- dispatcher
    def __call__(self, tool: str, args: dict, ctx: dict) -> dict:
        entry = self.registry.get(tool)
        if not entry:
            return _err("INVALID_ARGUMENT", "Tool không có trong registry.")
        workflows, roles, schema, handler = entry
        if ctx.get("workflow") not in workflows:
            return _err("UNAUTHORIZED", "Tool không nằm trong allowlist của workflow.")
        if ctx.get("actor", {}).get("role") not in roles:
            return _err("UNAUTHORIZED", "Vai trò không được phép gọi tool này.")
        bad = validate_schema(schema, args)
        if bad:
            return _err("INVALID_ARGUMENT", "Tham số không hợp lệ.")
        self.calls.append(tool)
        if tool in self.always_fail:
            return _err("TIMEOUT", "Mock system timeout.")
        if self.faults.get(tool):
            return _err(self.faults[tool].pop(0), "Lỗi mô phỏng.")
        return handler(args, ctx)

    # ---------------------------------------------------------------- read tools
    def get_trip_request(self, args, ctx):
        t = self.trips.get(args["trip_id"])
        if not t:
            return _err("NOT_FOUND", "Không tìm thấy bản ghi mock.")
        if not self._scope_ok(ctx, t["traveler_id"]):
            return _err("UNAUTHORIZED", "Ngoài phạm vi actor.")
        return _ok(dict(t), "mock_travel_request_system")

    def get_traveler_profile(self, args, ctx):
        p = self.profiles.get(args["traveler_id"])
        return _ok(dict(p), "mock_traveler_profile_system") if p else _err("NOT_FOUND", "Không tìm thấy bản ghi mock.")

    def _trip_scope(self, trip_id, ctx):
        t = self.trips.get(trip_id)
        if not t:
            return _err("NOT_FOUND", "Không tìm thấy bản ghi mock.")
        return None if self._scope_ok(ctx, t["traveler_id"]) else _err("UNAUTHORIZED", "Ngoài phạm vi actor.")

    def get_itinerary(self, args, ctx):
        e = self._trip_scope(args["trip_id"], ctx)
        if e:
            return e
        i = self.itins.get(args["trip_id"])
        return _ok(json.loads(json.dumps(i)), "mock_itinerary_system") if i else _err("NOT_FOUND", "Không có itinerary.")

    def get_approval_status(self, args, ctx):
        e = self._trip_scope(args["trip_id"], ctx)
        if e:
            return e
        rows = sorted((a for a in self.approvals if a["trip_id"] == args["trip_id"]), key=lambda a: a["created_at"])
        if not rows:
            return _err("NOT_FOUND", "Không có bản ghi approval.")
        a = rows[-1]
        return _ok({k: a[k] for k in ("approval_id", "trip_id", "request_type", "status", "action_summary")}, "mock_approval_system")

    def get_expense_report(self, args, ctx):
        r = self.reports.get(args["report_id"])
        if not r:
            return _err("NOT_FOUND", "Không tìm thấy bản ghi mock.")
        if not self._scope_ok(ctx, r["traveler_id"]):
            return _err("UNAUTHORIZED", "Ngoài phạm vi actor.")
        return _ok(json.loads(json.dumps(r)), "mock_expense_system")

    # ---------------------------------------------------------------- deterministic
    def calculate_expense_summary(self, args, ctx):
        r = self.get_expense_report(args, ctx)
        if not r["ok"]:
            return r
        rep = r["data"]
        items = rep["line_items"]
        total, by_cat, meals_by_day, flags = Decimal("0"), defaultdict(Decimal), defaultdict(list), []
        for it in items:
            amt = Decimal(str(it["amount"]))
            total += amt
            by_cat[it["category"]] += amt
            if it["category"] == "meals":
                meals_by_day[it["date"]].append((it["item_id"], amt))
            if it["currency"] != rep["currency"]:
                flags.append({"code": "currency_mismatch", "item_ids": [it["item_id"]],
                              "detail": "Khác đơn vị tiền của báo cáo; không tự quy đổi."})
            if (it["category"] == "lodging" or amt > RECEIPT_REQUIRED_OVER) and not it["receipt_present"]:
                flags.append({"code": "missing_receipt", "item_ids": [it["item_id"]],
                              "detail": f"{it['category']} {amt} {it['currency']} thiếu chứng từ."})
        for day, rows in sorted(meals_by_day.items()):
            s = sum(a for _, a in rows)
            if s > MEALS_DAILY_REVIEW_OVER:
                flags.append({"code": "meals_daily_over_threshold", "item_ids": [i for i, _ in rows],
                              "detail": f"Ăn uống ngày {day}: {s} > {MEALS_DAILY_REVIEW_OVER}."})
        return _ok({"report_id": rep["report_id"], "currency": rep["currency"], "total": str(total),
                    "by_category": {k: str(v) for k, v in by_cat.items()}, "flags": flags,
                    "thresholds": {"receipt_required_over": str(RECEIPT_REQUIRED_OVER),
                                   "meals_daily_review_over": str(MEALS_DAILY_REVIEW_OVER)}},
                   "mock_expense_system")

    # ---------------------------------------------------------------- policy search
    @staticmethod
    def _tokens(s: str) -> set:
        s = unicodedata.normalize("NFC", s.lower())
        return {t for t in re.findall(r"\w+", s) if len(t) >= 3}

    def search_travel_policy(self, args, ctx=None):
        q = self._tokens(args["query"])
        scored = []
        for c in self.chunks:
            if c["category"] != args["category"]:
                continue
            score = len(q & self._tokens(c["section"] + " " + c["text"]))
            if score > 0:
                scored.append((score, c))
        scored.sort(key=lambda x: (-x[0], x[1]["chunk_id"]))
        res = [dict(c, score=s) for s, c in scored[: args["max_results"]]]
        return _ok({"results": res}, "mock_policy_knowledge_base")

    # ---------------------------------------------------------------- draft tools (idempotent)
    def _draft(self, artifact_type, args):
        key = args["idempotency_key"]
        if key in self.drafts:
            return _ok(dict(self.drafts[key], idempotent_replay=True), "mock_draft_workspace", False)
        rec = {"draft_id": f"DRAFT-2026-{len(self.drafts) + 1:03d}", "artifact_type": artifact_type,
               "status": "draft_created", "delivery_status": "not_sent", "source_ids": args["source_ids"],
               "content": args["payload"], "idempotency_key": key}
        self.drafts[key] = rec
        return _ok(dict(rec, idempotent_replay=False), "mock_draft_workspace", False)
