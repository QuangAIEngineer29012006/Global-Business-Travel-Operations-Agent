from copy import deepcopy

import pytest

from conftest import run, seed_policies, session
from travel_agent.models import RunRequest


def test_pre_trip_fact_lineage_citations_and_draft(factory):
    a = factory()
    r = run(a, "Chuẩn bị công tác TRIP-2026-001")
    assert r["state"]["outcome"] == "completed"
    assert [t["action"] for t in r["state"]["trace"][:-1]] == [
        "get_trip_request", "get_traveler_profile", "get_approval_status", *["search_travel_policy"] * 4,
        "validate_trip_requirements", "create_travel_checklist_draft"]
    draft = r["response"]["artifacts"][0]
    assert draft["kind"] == "travel_checklist" and draft["delivery_status"] == "not_sent"
    assert "TRIP-2026-001" in draft["source_ids"]
    assert {c["citation"]["category"] for c in draft["policy_claims"]} == {"travel", "visa", "insurance", "approval"}
    chunks = {c["chunk_id"]: c for c in seed_policies()}
    for claim in draft["policy_claims"]:
        citation = claim["citation"]
        assert claim["text"] == claim["quote"]
        assert claim["quote"] in chunks[citation["chunk_id"]]["text"]
        assert all(citation[k] == chunks[citation["chunk_id"]][k] for k in citation)


@pytest.mark.parametrize("tid,user,expected", [("002", "demo-an", "completed"), ("008", "demo-chi", "needs_human")])
def test_disruption_reads_observation_and_keeps_guidance_separate(factory, tid, user, expected):
    a = factory()
    r = run(a, f"TRIP-2026-{tid} bị delay", user=user)
    assert r["state"]["outcome"] == expected
    draft = r["response"]["artifacts"][0]
    assert "itinerary" in draft["facts"] and "policy_claims" not in draft["facts"]
    assert draft["facts"]["itinerary"]["disruption"] == ("delayed" if tid == "002" else "cancelled")
    assert draft["status"] == "draft_created" and draft["delivery_status"] == "not_sent"


@pytest.mark.parametrize("report,outcome,total", [("001", "completed", 25500), ("002", "needs_input", 21000),
                                                 ("003", "needs_human", 45000)])
def test_expense_deterministic_summary_and_terminal(factory, report, outcome, total):
    a = factory()
    r = run(a, f"Rà soát chi phí EXP-2026-{report}")
    assert r["state"]["outcome"] == outcome
    calc = r["response"]["facts"]["calculate_expense_summary"]
    assert calc["total_minor"] == total and calc["currency"] == "SGD"
    assert calc["arithmetic"] == "integer_minor_units"
    draft = r["response"]["artifacts"][0]
    if report == "003":
        flags = {f["category"]: f for f in draft["items_for_review"] if isinstance(f, dict) and f["code"] == "over_daily_limit"}
        assert flags["meal"]["over_minor"] == 6000
        assert flags["meal"]["ratio_basis_points"] == 20000
        assert flags["hotel"]["ratio_basis_points"] == 15000
    if report == "002":
        assert "ITEM-01.amount_minor" in draft["items_for_review"]
        assert "ITEM-02.date" in draft["items_for_review"]


@pytest.mark.parametrize("tid,user,outcome", [("003", "demo-an", "awaiting_approval"),
                                             ("004", "demo-binh", "needs_human"),
                                             ("006", "demo-binh", "needs_human")])
def test_pending_rejected_cancelled_stop_before_any_draft_write(factory, tid, user, outcome):
    a = factory()
    r = run(a, f"Chuẩn bị công tác TRIP-2026-{tid}", user=user)
    assert r["state"]["outcome"] == outcome and r["response"]["artifacts"] == []
    assert not any(e.startswith("create_") for e in a.tools.executions)


def test_missing_trip_fields_stop_and_do_not_invent(factory):
    r = run(factory(), "Chuẩn bị TRIP-2026-005")
    assert r["state"]["outcome"] == "needs_input"
    assert r["response"]["facts"]["get_trip_request"]["purpose"] is None
    assert r["state"]["retrieval_calls"] == 0


def test_no_evidence_and_version_conflict_are_human_outcomes(factory):
    policies = [p for p in seed_policies() if p["category"] != "visa"]
    r = run(factory(policies=policies), "Chuẩn bị TRIP-2026-001")
    assert r["state"]["outcome"] == "needs_human" and not r["response"]["artifacts"]
    policies = seed_policies()
    duplicate = deepcopy(policies[0])
    duplicate.update(chunk_id="POL-CONFLICT@2.0", version="2.0")
    r = run(factory(policies=policies + [duplicate]), "Chuẩn bị TRIP-2026-001")
    assert r["response"]["reason"] == "policy_version_conflict"


def test_approval_request_pending_then_human_simulation_and_fresh_run(factory):
    a = factory()
    caller, _ = session(a)
    r = run(a, "Yêu cầu phê duyệt TRIP-2026-009", caller=caller)
    assert r["state"]["outcome"] == "awaiting_approval" and not r["response"]["artifacts"]
    assert r["response"]["facts"]["request_approval"]["status"] == "pending"
    assert a.tools.executions[-1] == "request_approval"
    approver, _ = session(a, "demo-approver")
    a.store.resolve_mock_approval(approver, "TRIP-2026-009", "approved")
    later = run(a, "Chuẩn bị TRIP-2026-009", caller=caller)
    assert later["state"]["outcome"] == "completed"
    assert later["response"]["facts"]["get_approval_status"]["status"] == "approved"


def test_daily_limit_groups_line_items_by_day_and_category(factory):
    a = factory()
    report = a.store.read_record("reports", "EXP-2026-001")
    report["items"] = [
        {"item_id": "A", "category": "meal", "date": "2026-11-20", "amount_minor": 4000, "currency": "SGD", "receipt": True},
        {"item_id": "B", "category": "meal", "date": "2026-11-20", "amount_minor": 3000, "currency": "SGD", "receipt": True}]
    a.store.replace_record("reports", report["report_id"], report)
    r = run(a, "Expense pre-check EXP-2026-001")
    flags = r["response"]["facts"]["validate_expense_requirements"]["reviewer_flags"]
    assert flags[0]["amount_minor"] == 7000 and flags[0]["over_minor"] == 1000


def test_currency_mismatch_and_missing_currency_policy_not_silently_converted(factory):
    a = factory()
    report = a.store.read_record("reports", "EXP-2026-001")
    report["items"][0]["currency"] = "USD"
    a.store.replace_record("reports", report["report_id"], report)
    r = run(a, "Rà soát chi phí EXP-2026-001")
    assert r["state"]["outcome"] == "needs_human"
    assert r["response"]["facts"]["calculate_expense_summary"]["currency_errors"] == ["ITEM-01"]
    report["currency"] = "USD"
    for item in report["items"]:
        item["currency"] = "USD"
    a.store.replace_record("reports", report["report_id"], report)
    r = run(a, "Rà soát chi phí EXP-2026-001")
    assert r["response"]["reason"] == "insufficient_currency_or_category_policy"


@pytest.mark.parametrize("message,workflow", [("Xin chào", "direct"), ("Viết lại:  Nội dung   mẫu", "rewrite"),
                                            ("Trạng thái TRIP-2026-001", "status"),
                                            ("Approval status TRIP-2026-003", "status")])
def test_direct_and_status_do_not_retrieve(factory, message, workflow):
    r = run(factory(), message)
    assert r["state"]["workflow"] == workflow and r["state"]["retrieval_calls"] == 0
    assert r["state"]["outcome"] == "completed"


def test_direct_policy_retrieval_and_unrelated_query(factory):
    a = factory()
    r = run(a, "Chính sách visa Singapore")
    assert r["state"]["workflow"] == "policy" and r["response"]["citations"]
    r = run(a, "Chính sách lương thưởng")
    assert r["state"]["outcome"] == "needs_human" and not r["response"]["citations"]
