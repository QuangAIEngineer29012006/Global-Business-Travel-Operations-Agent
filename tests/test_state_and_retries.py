import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import run, session
from travel_agent.agent import TravelAgent
from travel_agent.models import RunRequest
from travel_agent.storage import Store, StoreError


def test_retry_transient_and_stop_after_limit(factory):
    a = factory()
    a.tools.inject_fault("get_trip_request", count=1)
    r = run(a, "Chuẩn bị TRIP-2026-001")
    assert r["state"]["outcome"] == "completed" and r["state"]["retry_count"] == 1
    assert a.tools.executions.count("get_trip_request") == 2
    a = factory()
    a.tools.inject_fault("get_trip_request", count=100)
    r = run(a, "Chuẩn bị TRIP-2026-001")
    assert r["state"]["outcome"] == "tool_failed"
    assert a.tools.executions == ["get_trip_request", "get_trip_request"]
    assert r["state"]["step_count"] == 2


@pytest.mark.parametrize("settings", [{"max_steps": 2}, {"max_model_calls": 2}, {"max_retrieval_calls": 1}])
def test_all_run_budgets_stop_without_draft(factory, settings):
    a = factory(**settings)
    r = run(a, "Chuẩn bị TRIP-2026-001")
    assert r["state"]["outcome"] == "budget_exceeded" and not r["response"]["artifacts"]
    assert r["state"]["step_count"] <= a.settings.max_steps


def test_retries_count_toward_step_budget(factory):
    a = factory(max_steps=1)
    a.tools.inject_fault("get_trip_request", count=5)
    r = run(a, "Chuẩn bị TRIP-2026-001")
    assert r["state"]["outcome"] == "budget_exceeded"
    assert len(a.tools.executions) == 1 and r["state"]["step_count"] == 1


def test_response_lost_after_draft_commit_retries_same_id_without_duplicate(factory):
    a = factory()
    a.tools.inject_fault("create_travel_checklist_draft", after_commit=True)
    r = run(a, "Chuẩn bị TRIP-2026-001")
    assert r["state"]["outcome"] == "completed" and r["state"]["retry_count"] == 1
    assert len(r["response"]["artifacts"]) == 1
    with a.store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 1


def test_unconfirmed_write_never_reports_success(factory):
    a = factory(tool_retries=0)
    a.tools.inject_fault("create_travel_checklist_draft", after_commit=True)
    r = run(a, "Chuẩn bị TRIP-2026-001")
    assert r["state"]["outcome"] == "failed_delivery"
    assert not r["response"]["artifacts"] and r["response"]["delivery_status"] == "not_sent"
    with a.store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 1


def test_run_replay_and_conflicting_key(factory):
    a = factory()
    caller, _ = session(a)
    r = run(a, "Chuẩn bị TRIP-2026-001", caller=caller, key="stable-request-001")
    count = len(a.tools.executions)
    again = run(a, "Chuẩn bị TRIP-2026-001", caller=caller, key="stable-request-001")
    assert again["replayed"] and r["state"]["run_id"] == again["state"]["run_id"]
    assert again["response"]["artifacts"] == r["response"]["artifacts"] and len(a.tools.executions) == count
    with pytest.raises(StoreError, match="idempotency_conflict"):
        run(a, "Chuẩn bị TRIP-2026-002", caller=caller, key="stable-request-001")


def test_atomic_run_reservation_under_concurrency(factory):
    a = factory()
    caller, _ = session(a)
    def reserve(_):
        try:
            return a.store.begin_run(caller, "same-request-001", "samehash")[0]
        except StoreError as err:
            return err.code
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(reserve, range(6)))
    assert results.count("run_in_progress") == 5


def test_session_context_user_and_run_ids_are_separate_and_scoped(factory):
    a = factory()
    caller, token = session(a)
    first = run(a, "Chuẩn bị TRIP-2026-001", caller=caller)
    refreshed = a.store.authenticate("Bearer " + token)
    second = run(a, "Kiểm tra trạng thái", caller=refreshed)
    assert second["response"]["facts"]["get_trip_request"]["trip_id"] == "TRIP-2026-001"
    assert len({first["state"]["run_id"], first["state"]["session_id"], first["state"]["user_id"]}) == 3
    other, _ = session(a)
    no_context = run(a, "Kiểm tra trạng thái", caller=other)
    assert no_context["state"]["outcome"] == "needs_input"
    with pytest.raises(StoreError):
        a.store.get_run(other, first["state"]["run_id"])
    with pytest.raises(StoreError):
        a.store.get_draft(other, first["response"]["artifacts"][0]["draft_id"])


def test_cross_user_business_ownership_and_preference_isolation(factory):
    a = factory()
    a.store.save_preferences("demo-an", {"response_language": "en"})
    r = run(a, "Chuẩn bị TRIP-2026-001", user="demo-binh")
    assert r["response"]["reason"] == "not_found" and not r["response"]["facts"]
    assert a.store.preferences("demo-binh") == {}
    same_user, _ = session(a)
    greeting = run(a, "Hello", caller=same_user)
    assert greeting["response"]["preferences_applied"]["response_language"] == "en"
    a.store.delete_preferences("demo-an")
    assert a.store.preferences("demo-an") == {}


def test_business_facts_refreshed_after_store_reopen_not_copied_from_context(factory):
    a = factory()
    caller, token = session(a)
    run(a, "Approval status TRIP-2026-001", caller=caller)
    approval = a.store.read_record("approvals", "TRIP-2026-001")
    a.store.replace_record("approvals", approval["trip_id"], {**approval, "status": "pending"})
    reopened = TravelAgent(a.settings, store=Store(a.settings.workspace))
    refreshed = reopened.store.authenticate("Bearer " + token)
    r = run(reopened, "Chuẩn bị TRIP-2026-001", caller=refreshed)
    assert r["state"]["outcome"] == "awaiting_approval"
    assert r["response"]["facts"]["get_approval_status"]["status"] == "pending"


def test_no_raw_conversation_or_tokens_persisted_and_trace_is_complete(factory):
    a = factory()
    caller, token = session(a)
    raw_text = "Viết lại:  A UNIQUE RAW MESSAGE"
    r = run(a, raw_text, caller=caller)
    assert r["response"]["summary"] == "A UNIQUE RAW MESSAGE"
    with a.store.connection() as conn:
        dump = "\n".join(conn.iterdump())
    assert token not in dump and raw_text not in dump and "UNIQUE RAW MESSAGE" not in dump
    r = run(a, "Chuẩn bị TRIP-2026-001", caller=caller, case_id="trace_case")
    required = {"case_id", "run_id", "phase", "action", "safe_arguments", "observation_status", "transition", "budget", "outcome"}
    assert all(required <= set(item) for item in r["state"]["trace"])
    assert r["state"]["trace"][-1]["outcome"] == "completed"
