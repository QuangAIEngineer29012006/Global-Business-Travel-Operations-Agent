import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.llm_client import FakeClient, LLMError, ModelResult
from backend.main import create_app
from backend.service import LLMService
from src.dev_systems import MockSystems
from src.workflows import run_agent


def request(message="Chuẩn bị TRIP-2026-001", actor="EMP-001", role="employee", **context):
    return {"request_id": "REQ-2026-001", "actor": {"role": role, "actor_id": actor}, "session_id": "SES-001",
            "message": message, "context": context}


class CountingClient(FakeClient):
    def __init__(self, value=None, error=None):
        self.calls = 0
        self.value = value
        self.error = error

    def choose_highlights(self, message, highlights):
        self.calls += 1
        if self.error:
            raise self.error
        return ModelResult(self.value if self.value is not None else {"highlight_ids": list(highlights)[:3]}, 20, 5)

    def rewrite(self, text):
        self.calls += 1
        if self.error:
            raise self.error
        return ModelResult(self.value if self.value is not None else "Tôi gặp sự cố trễ chuyến bay và cần được hỗ trợ.", 10, 8)


@pytest.mark.parametrize("body,status,workflow", [
    (request(), "awaiting_approval", "pre_trip"),
    (request("Chuẩn bị TRIP-2026-002", actor="EMP-002"), "completed", "pre_trip"),
    (request("TRIP-2026-002 bị delay", actor="EMP-002"), "completed", "in_trip"),
    (request("TRIP-2026-003 bị hủy", actor="EMP-003"), "needs_human", "in_trip"),
    (request("Rà soát EXP-2026-001", actor="EMP-003"), "completed", "post_trip"),
    (request("Rà soát EXP-2026-003", role="travel_operations_reviewer", actor="REV-001"), "needs_human", "post_trip"),
])
def test_shared_workflows_fixtures_and_contract(body, status, workflow):
    ms, llm = MockSystems(), CountingClient()
    result = LLMService(llm, ms).run(body)
    assert result["status"] == status and result["workflow"] == workflow
    assert llm.calls == 1 and result["llm"]["calls"] == 1
    assert {"request_id", "run_id", "workflow", "status", "message", "data", "evidence", "artifacts", "next_action"} <= result.keys()
    if body["message"] == "Chuẩn bị TRIP-2026-001":
        assert result["data"]["approval_status"] == "pending"
        assert "chưa được duyệt" in result["llm"]["message"]
    if "EXP-2026-001" in body["message"]:
        assert result["data"]["summary"]["total"] == "70.5"
    assert all(a["delivery_status"] == "not_sent" for a in result["artifacts"])


@pytest.mark.parametrize("value", [{"highlight_ids": ["unknown"]}, {"highlight_ids": ["approval", "approval"]},
                                  {"highlight_ids": [], "status": "approved"}, {"highlight_ids": "approval"}])
def test_invalid_llm_plan_cannot_change_authoritative_result(value):
    body = request()
    expected = run_agent(body, MockSystems())
    result = LLMService(CountingClient(value=value), MockSystems()).run(body)
    for field in ("status", "message", "reason_code", "data", "evidence", "next_action"):
        assert result[field] == expected[field]
    assert result["llm"]["status"] == "fallback"
    assert result["llm"]["error_code"] == "invalid_presentation_plan"


def test_model_unavailable_preserves_created_draft_and_workflow_status():
    ms = MockSystems()
    result = LLMService(CountingClient(error=LLMError("llm_timeout", 1)), ms).run(request())
    assert result["status"] == "awaiting_approval" and len(result["artifacts"]) == 1
    assert len(ms.drafts) == 1 and result["llm"]["status"] == "fallback"
    assert result["llm"]["retry_count"] == 1
    assert result["trace"][-1]["action"] == "terminal"
    assert result["trace"][-2]["observation_status"] == "fallback"


@pytest.mark.parametrize("body,expected", [(request("Chuẩn bị công tác"), "needs_input"),
    (request("Chuẩn bị", trip_id="TRIP-26-1"), "failed_validation"),
    (request("Chuẩn bị TRIP-2026-001", actor="EMP-002"), "rejected"),
    (request("Chuẩn bị TRIP-2026-999"), "needs_input")])
def test_input_or_authorization_failures_do_not_call_llm(body, expected):
    client = CountingClient()
    result = LLMService(client, MockSystems()).run(body)
    assert result["status"] == expected and client.calls == 0


def test_real_rewrite_path_uses_client_once_without_retrieval():
    ms, client = MockSystems(), CountingClient()
    result = LLMService(client, ms).run(request("Viết lại chuyên nghiệp: tôi bị trễ chuyến bay, giúp với"))
    assert result["message"] == "Tôi gặp sự cố trễ chuyến bay và cần được hỗ trợ."
    assert result["workflow"] == "direct" and client.calls == 1 and ms.calls == []
    assert result["data"] == {} and result["evidence"] == [] and result["artifacts"] == []


def test_rewrite_failure_does_not_report_completion():
    client = CountingClient(error=LLMError("llm_auth"))
    result = LLMService(client, MockSystems()).run(request("Viết lại: nội dung mẫu"))
    assert result["status"] == "needs_human" and result["llm"]["error_code"] == "llm_auth"


def test_greeting_is_direct_and_fake_rewrite_is_honestly_labelled():
    ms, client = MockSystems(), CountingClient()
    result = LLMService(client, ms).run(request("Xin chào!"))
    assert result["status"] == "completed" and client.calls == 0 and ms.calls == []
    result = LLMService(FakeClient(), ms).run(request("Viết lại: nội dung mẫu"))
    assert "Offline simulator" in result["message"]


def test_api_accepts_documented_envelope_without_separate_login():
    with TestClient(create_app(Settings())) as client:
        response = client.post("/api/runs", json=request())
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "awaiting_approval" and result["data"]["approval_status"] == "pending"
        assert client.get("/api/health").json()["training_only"]
        assert client.get("/openapi.json").status_code == 200


def test_api_validates_roles_unknown_fields_and_body_without_leaking_input():
    with TestClient(create_app(Settings())) as client:
        bad = request()
        bad["actor"]["role"] = "admin"
        response = client.post("/api/runs", json=bad)
        assert response.status_code == 422
        bad = request()
        bad["secret"] = "DO_NOT_ECHO_THIS"
        response = client.post("/api/runs", json=bad)
        assert response.status_code == 422 and "DO_NOT_ECHO_THIS" not in response.text
        assert client.post("/api/runs", content=b"x" * 17000).status_code == 413


def test_replay_of_shared_draft_is_not_duplicated_and_facts_read_again():
    ms = MockSystems()
    service = LLMService(FakeClient(), ms)
    first = service.run(request())
    second = service.run(request())
    assert first["artifacts"][0]["draft_id"] == second["artifacts"][0]["draft_id"]
    assert len(ms.drafts) == 1
    ms.approvals[0]["status"] = "rejected"
    third = service.run({**request(), "request_id": "REQ-2026-002"})
    assert third["status"] == "needs_human" and third["reason_code"] == "APPROVAL_REJECTED"
    assert third["artifacts"] == []


def test_session_state_can_be_injected_from_the_memory_owner():
    service = LLMService(FakeClient(), MockSystems())
    session = {}
    service.run(request(), session=session)
    assert session == {"active_trip_id": "TRIP-2026-001"}
    followup = service.run(request("Chuẩn bị công tác"), session=session)
    assert followup["status"] == "awaiting_approval"
    other = service.run(request("Chuẩn bị công tác"), session={})
    assert other["status"] == "needs_input"
