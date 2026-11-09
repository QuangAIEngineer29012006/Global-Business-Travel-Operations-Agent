from unittest.mock import Mock

import pytest
import requests

from backend.config import Settings
from backend.function_calling import read_tool_declarations, tool_turn
from backend.llm_client import GeminiClient, LLMError, parse_json
from src.dev_systems import MockSystems


def client():
    return GeminiClient(Settings(provider="gemini", model="gemini-test-model", api_key="fake-test-key"))


def envelope(parts, status=200, finish="STOP", retry_after=None):
    response = Mock(status_code=status)
    response.headers = {"Retry-After": retry_after} if retry_after else {}
    response.json.return_value = {"candidates": [{"finishReason": finish, "content": {"role": "model", "parts": parts}}],
                                  "usageMetadata": {"promptTokenCount": 18, "candidatesTokenCount": 6}}
    return response


def test_structured_generation_and_token_counts(monkeypatch):
    post = Mock(return_value=envelope([{"text": '{"highlight_ids":["approval"]}'}]))
    monkeypatch.setattr("backend.llm_client.requests.post", post)
    result = client().choose_highlights("Chuẩn bị TRIP-2026-001", {"approval": "pending"})
    assert result.value == {"highlight_ids": ["approval"]} and result.input_tokens == 18
    payload = post.call_args.kwargs["json"]
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    assert payload["generationConfig"]["responseJsonSchema"]["additionalProperties"] is False
    assert "tools" not in payload and post.call_args.kwargs["allow_redirects"] is False


def test_rewrite_is_a_text_generation_call(monkeypatch):
    post = Mock(return_value=envelope([{"text": "Tôi cần hỗ trợ vì chuyến bay bị trễ."}]))
    monkeypatch.setattr("backend.llm_client.requests.post", post)
    result = client().rewrite("tôi bị trễ chuyến bay, giúp với")
    assert result.value == "Tôi cần hỗ trợ vì chuyến bay bị trễ."
    assert "responseMimeType" not in post.call_args.kwargs["json"]["generationConfig"]
    prompt = post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
    assert parse_json(prompt) == {"TEXT_TO_REWRITE": "tôi bị trễ chuyến bay, giúp với"}


@pytest.mark.parametrize("raw", ['{"highlight_ids":[],"highlight_ids":["approval"]}', '{"x": NaN}', '```json\n{}\n```', ''])
def test_bad_model_json_is_rejected(raw):
    with pytest.raises(ValueError):
        parse_json(raw)


def test_timeout_retries_are_bounded_and_do_not_reveal_provider_exception(monkeypatch):
    post = Mock(side_effect=requests.Timeout("SECRET RAW ERROR"))
    monkeypatch.setattr("backend.llm_client.requests.post", post)
    monkeypatch.setattr("backend.llm_client.time.sleep", lambda _: None)
    with pytest.raises(LLMError) as caught:
        client().rewrite("test")
    assert caught.value.code == "llm_timeout" and caught.value.retry_count == 1
    assert post.call_count == 2 and "SECRET" not in str(caught.value)


@pytest.mark.parametrize("status,header,expected", [(401, None, "llm_auth"), (400, None, "llm_request"),
                                                   (429, "30", "llm_rate_limit"), (503, "30", "llm_unavailable")])
def test_non_retryable_and_long_retry_after_stop(monkeypatch, status, header, expected):
    post = Mock(return_value=envelope([], status=status, retry_after=header))
    monkeypatch.setattr("backend.llm_client.requests.post", post)
    with pytest.raises(LLMError) as caught:
        client().rewrite("test")
    assert caught.value.code == expected and post.call_count == 1


def test_transient_error_then_success_counts_retry(monkeypatch):
    post = Mock(side_effect=[envelope([], status=503), envelope([{"text": "Nội dung đã viết lại."}])])
    monkeypatch.setattr("backend.llm_client.requests.post", post)
    monkeypatch.setattr("backend.llm_client.time.sleep", lambda _: None)
    result = client().rewrite("Nội dung")
    assert result.retry_count == 1 and post.call_count == 2


@pytest.mark.parametrize("body", [{}, {"candidates": []}, {"candidates": [{"finishReason": "SAFETY"}]}])
def test_malformed_or_refused_response_fails_safely(monkeypatch, body):
    response = envelope([])
    response.json.return_value = body
    monkeypatch.setattr("backend.llm_client.requests.post", Mock(return_value=response))
    with pytest.raises(LLMError):
        client().rewrite("test")


def tool_content(name="get_trip_request", args=None):
    return {"role": "model", "parts": [{"thoughtSignature": "opaque-signature", "functionCall": {
        "name": name, "args": args if args is not None else {"trip_id": "TRIP-2026-001"}, "id": "call-1"}}]}


def tool_context():
    return {"workflow": "pre_trip", "actor": {"role": "employee", "actor_id": "EMP-001"},
            "run_id": "RUN-TEST", "request_id": "REQ-TEST", "bound_arguments": {"trip_id": "TRIP-2026-001"}}


def test_native_tool_turn_uses_existing_dispatcher_and_preserves_thought_signature(monkeypatch):
    ms = MockSystems()
    content = tool_content()
    post = Mock(return_value=envelope(content["parts"]))
    monkeypatch.setattr("backend.llm_client.requests.post", post)
    declarations = read_tool_declarations(ms.registry)
    contents = [{"role": "user", "parts": [{"text": "Đọc TRIP-2026-001"}]}]
    result = tool_turn(client(), contents, declarations, ["get_trip_request"], ms, tool_context())
    assert result["observation"]["data"]["travel_status"] == "pending_approval"
    assert ms.calls == ["get_trip_request"]
    assert result["contents"][-2] == content
    assert result["contents"][-1]["parts"][0]["functionResponse"]["id"] == "call-1"
    payload = post.call_args.kwargs["json"]
    assert payload["toolConfig"]["functionCallingConfig"]["mode"] == "ANY"
    assert payload["tools"][0]["functionDeclarations"] == declarations


@pytest.mark.parametrize("name,args,expected", [("shell", {"command": "whoami"}, "invalid_function_call"),
    ("get_trip_request", {"trip_id": "TRIP-2026-002"}, "unbound_function_arguments")])
def test_native_unknown_or_unbound_tool_proposal_never_executes(monkeypatch, name, args, expected):
    ms = MockSystems()
    monkeypatch.setattr("backend.llm_client.requests.post", Mock(return_value=envelope(tool_content(name, args)["parts"])))
    with pytest.raises(LLMError) as caught:
        tool_turn(client(), [], read_tool_declarations(ms.registry), ["get_trip_request"], ms, tool_context())
    assert caught.value.code == expected and ms.calls == []


def test_native_arguments_and_authorization_still_checked_by_shared_dispatcher(monkeypatch):
    ms = MockSystems()
    content = tool_content(args={"trip_id": "TRIP-2026-001", "path": "/etc/passwd"})
    monkeypatch.setattr("backend.llm_client.requests.post", Mock(return_value=envelope(content["parts"])))
    result = tool_turn(client(), [], read_tool_declarations(ms.registry), ["get_trip_request"], ms, tool_context())
    assert result["observation"]["error"]["code"] == "INVALID_ARGUMENT" and ms.calls == []
    content = tool_content()
    monkeypatch.setattr("backend.llm_client.requests.post", Mock(return_value=envelope(content["parts"])))
    ctx = tool_context()
    ctx["actor"]["actor_id"] = "EMP-002"
    result = tool_turn(client(), [], read_tool_declarations(ms.registry), ["get_trip_request"], ms, ctx)
    assert result["observation"]["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize("parts", [[{"text": "I approved it"}], tool_content()["parts"] * 2])
def test_native_requires_exactly_one_call(monkeypatch, parts):
    ms = MockSystems()
    monkeypatch.setattr("backend.llm_client.requests.post", Mock(return_value=envelope(parts)))
    with pytest.raises(LLMError):
        tool_turn(client(), [], read_tool_declarations(ms.registry), ["get_trip_request"], ms, tool_context())
    assert ms.calls == []


@pytest.mark.parametrize("kwargs", [{"provider": "other"}, {"provider": "gemini"}, {"timeout": 0}, {"max_retries": 3}])
def test_config_rejects_invalid_provider_key_or_budget(kwargs):
    with pytest.raises(ValueError):
        Settings(**kwargs)
