import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from fastapi.testclient import TestClient

from backend.main import create_app
from conftest import session
from travel_agent.config import Settings
from travel_agent.llm import GeminiToolModel, LLMError, observe
from travel_agent.models import ToolCall


def auth(client, user="demo-an"):
    raw = client.post("/api/sessions", json={"user_id": user})
    assert raw.status_code == 201
    return {"Authorization": "Bearer " + raw.json()["token"]}


def test_api_end_to_end_and_isolation(factory):
    a = factory()
    with TestClient(create_app(a.settings, a.store)) as c:
        assert c.get("/api/health").json()["training_only"]
        h = auth(c)
        r = c.post("/api/runs", headers=h, json={"message": "Chuẩn bị TRIP-2026-001", "request_id": "api-request-001"})
        assert r.status_code == 200 and r.json()["state"]["outcome"] == "completed"
        rid = r.json()["state"]["run_id"]
        did = r.json()["response"]["artifacts"][0]["draft_id"]
        assert c.get("/api/runs/" + rid, headers=h).status_code == 200
        assert c.get("/api/drafts/" + did, headers=h).status_code == 200
        other = auth(c, "demo-binh")
        assert c.get("/api/runs/" + rid, headers=other).status_code == 404
        assert c.get("/api/drafts/" + did, headers=other).status_code == 404
        assert c.post("/api/runs", json={"message": "hi", "request_id": "api-noauth-01"}).status_code == 401
        assert c.delete("/api/sessions/current", headers=h).status_code == 200
        assert c.get("/api/preferences", headers=h).status_code == 401


def test_api_preference_requires_explicit_consent_and_approval_is_separate(factory):
    a = factory()
    with TestClient(create_app(a.settings, a.store)) as c:
        h = auth(c)
        for body in [{"response_language": "en"}, {"remember": False, "response_language": "en"},
                     {"remember": True, "passport_number": "SECRET"}]:
            assert c.put("/api/preferences", headers=h, json=body).status_code == 422
        assert c.put("/api/preferences", headers=h, json={"remember": True, "response_language": "en"}).status_code == 200
        assert c.get("/api/preferences", headers=h).json() == {"response_language": "en"}
        assert c.delete("/api/preferences", headers=h).json()["deleted"]
        assert c.post("/api/mock-approvals/TRIP-2026-003", headers=h, json={"status": "approved"}).status_code == 403
        approver = auth(c, "demo-approver")
        assert c.post("/api/mock-approvals/TRIP-2026-003", headers=approver, json={"status": "approved"}).json()["status"] == "approved"
        assert c.post("/api/mock-approvals/TRIP-2026-003", headers=approver, json={"status": "rejected"}).status_code == 409


def test_api_rejects_oversize_and_leaking_validation_errors(factory):
    a = factory()
    with TestClient(create_app(a.settings, a.store)) as c:
        h = auth(c)
        bad = c.post("/api/runs", headers=h, json={"message": "SECRET", "request_id": "x", "secret": "VERY_SECRET"})
        assert bad.status_code == 422 and "VERY_SECRET" not in bad.text
        assert c.post("/api/runs", headers=h, content=b"x" * 17000).status_code == 413
        assert c.get("/openapi.json").status_code == 200
        assert c.get("/api/tools").json()["tools"]


def gemini(tmp_path, **kwargs):
    return GeminiToolModel(Settings(workspace=tmp_path, provider="gemini", model="gemini-test-model",
                                    api_key="test-only-key", **kwargs))


def response(content=None, status=200, retry_after=None):
    r = Mock()
    r.status_code = status
    r.headers = {"Retry-After": retry_after} if retry_after else {}
    r.json.return_value = {"candidates": [{"finishReason": "STOP", "content": content or {
        "role": "model", "parts": [{"thoughtSignature": "opaque-signature", "functionCall": {
            "name": "get_trip_request", "args": {"trip_id": "TRIP-2026-001"}, "id": "call-001"}}]}}],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}}
    return r


def inputs():
    return [{"name": "get_trip_request", "description": "Read training trip", "parametersJsonSchema": {
        "type": "object", "properties": {"trip_id": {"type": "string"}}, "required": ["trip_id"], "additionalProperties": False}}], {
        "user_message": "Chuẩn bị TRIP-2026-001", "phase": "get_trip_request", "identifiers": {"trip_id": "TRIP-2026-001"}}


def test_native_gemini_function_call_payload_and_thought_signature_roundtrip(tmp_path, monkeypatch, factory):
    post = Mock(return_value=response())
    monkeypatch.setattr("travel_agent.llm.requests.post", post)
    model = gemini(tmp_path)
    decl, ctx = inputs()
    history = []
    proposal = model.propose(decl, ctx, history)
    assert proposal.call.name == "get_trip_request" and proposal.input_tokens == 10
    payload = post.call_args.kwargs["json"]
    assert payload["tools"][0]["functionDeclarations"] == decl
    assert payload["toolConfig"]["functionCallingConfig"] == {"mode": "ANY", "allowedFunctionNames": ["get_trip_request"]}
    assert "responseFormat" not in payload["generationConfig"]
    a = factory()
    from travel_agent.dispatcher import Dispatcher
    from travel_agent.models import ResultMeta, ToolResult
    result = ToolResult(ok=True, data={"trip_id": "TRIP-2026-001"}, meta=ResultMeta(source="mock", read_only=True))
    observe(history, proposal, result)
    assert history[-2]["parts"][0]["thoughtSignature"] == "opaque-signature"
    assert history[-1]["parts"][0]["functionResponse"]["id"] == "call-001"
    model.propose(decl, ctx, history)
    assert post.call_args.kwargs["json"]["contents"][-3]["parts"][0]["thoughtSignature"] == "opaque-signature"
    assert post.call_args.kwargs["allow_redirects"] is False


def test_provider_timeout_retry_and_daily_budget(tmp_path, monkeypatch):
    post = Mock(side_effect=requests.Timeout("SECRET RAW PROVIDER ERROR"))
    monkeypatch.setattr("travel_agent.llm.requests.post", post)
    monkeypatch.setattr("travel_agent.llm.time.sleep", lambda _: None)
    model = gemini(tmp_path, transport_retries=1, daily_limit=2)
    with pytest.raises(LLMError) as err:
        model.propose(*inputs(), [])
    assert err.value.code == "llm_timeout" and post.call_count == 2
    with pytest.raises(LLMError) as err:
        model.propose(*inputs(), [])
    assert err.value.code == "llm_daily_limit" and post.call_count == 2


@pytest.mark.parametrize("status,header,expected", [(401, None, "llm_auth"), (429, "30", "llm_rate_limit"),
                                                  (503, "30", "llm_unavailable")])
def test_provider_does_not_retry_auth_or_ignore_long_retry_after(tmp_path, monkeypatch, status, header, expected):
    post = Mock(return_value=response(status=status, retry_after=header))
    monkeypatch.setattr("travel_agent.llm.requests.post", post)
    model = gemini(tmp_path)
    with pytest.raises(LLMError) as err:
        model.propose(*inputs(), [])
    assert err.value.code == expected and post.call_count == 1


@pytest.mark.parametrize("content", [{"role": "model", "parts": [{"text": "I already approved it"}]},
    {"role": "model", "parts": [{"functionCall": {"name": "one", "args": {}}}, {"functionCall": {"name": "two", "args": {}}}]}])
def test_native_noncall_or_multiple_calls_fail_without_execution(tmp_path, monkeypatch, content):
    monkeypatch.setattr("travel_agent.llm.requests.post", Mock(return_value=response(content=content)))
    with pytest.raises(LLMError) as err:
        gemini(tmp_path).propose(*inputs(), [])
    assert err.value.code == "invalid_function_call"
