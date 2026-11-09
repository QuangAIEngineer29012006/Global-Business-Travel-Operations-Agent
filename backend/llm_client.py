import copy
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests

from .models import PresentationPlan
from .prompts import PRESENTATION_PROMPT, REWRITE_PROMPT


class LLMError(Exception):
    def __init__(self, code, retry_count=0):
        self.code = code
        self.retry_count = retry_count
        super().__init__(code)


@dataclass
class ModelResult:
    value: object
    input_tokens: int | None = None
    output_tokens: int | None = None
    retry_count: int = 0


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate JSON key")
        obj[key] = value
    return obj


def parse_json(text):
    if not isinstance(text, str) or not text.strip() or len(text) > 16000:
        raise ValueError("Invalid model JSON")
    return json.loads(text, object_pairs_hook=_unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON")))


def _retry_delay(header, attempt):
    try:
        seconds = float(header)
    except (ValueError, TypeError):
        try:
            seconds = (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            seconds = 0
    return max(0.25 * 2 ** attempt, seconds)


class FakeClient:
    """Offline simulator. It does not measure language-model quality."""
    model_id = "fake-llm-v2"

    def choose_highlights(self, message, highlights):
        return ModelResult({"highlight_ids": list(highlights)[:3]})

    def rewrite(self, text):
        return ModelResult("[Offline simulator; chưa viết lại bằng LLM] " + text)


class GeminiClient:
    def __init__(self, settings):
        self.settings = settings
        self.model_id = settings.model

    def _generate(self, system, contents, **options):
        url = "https://generativelanguage.googleapis.com/v1beta/models/" + quote(self.model_id, safe="-") + ":generateContent"
        payload = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                   "generationConfig": {"temperature": 0, "maxOutputTokens": 1024}}
        generation = options.pop("generation", {})
        payload["generationConfig"].update(generation)
        payload.update(options)
        for attempt in range(self.settings.max_retries + 1):
            header = None
            try:
                response = requests.post(url, headers={"x-goog-api-key": self.settings.api_key}, json=payload,
                                         timeout=self.settings.timeout, allow_redirects=False)
            except (requests.Timeout, requests.ConnectionError):
                code = "llm_timeout"
            except requests.RequestException:
                raise LLMError("llm_transport", attempt) from None
            else:
                if response.status_code == 429 or 500 <= response.status_code <= 599:
                    code = "llm_rate_limit" if response.status_code == 429 else "llm_unavailable"
                    header = response.headers.get("Retry-After")
                elif response.status_code != 200:
                    raise LLMError("llm_auth" if response.status_code in {401, 403} else "llm_request", attempt)
                else:
                    try:
                        body = response.json()
                        candidate = body["candidates"][0]
                        if body.get("promptFeedback", {}).get("blockReason") or candidate.get("finishReason") != "STOP":
                            raise LLMError("llm_refusal", attempt)
                        content = candidate["content"]
                        if content.get("role") != "model" or not isinstance(content["parts"], list):
                            raise ValueError("Malformed content")
                        usage = body.get("usageMetadata", {})
                        return ModelResult(copy.deepcopy(content), usage.get("promptTokenCount"),
                                           usage.get("candidatesTokenCount"), attempt)
                    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                        raise LLMError("llm_response", attempt) from None
            if attempt == self.settings.max_retries:
                raise LLMError(code, attempt)
            delay = _retry_delay(header, attempt)
            if delay > 3:
                raise LLMError(code, attempt)
            time.sleep(delay)

    @staticmethod
    def _text(result):
        try:
            parts = result.value["parts"]
            if any("functionCall" in part for part in parts):
                raise ValueError("Unexpected call")
            text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
            if not text.strip() or len(text) > 16000:
                raise ValueError("Invalid text")
            return text.strip()
        except (ValueError, TypeError, AttributeError):
            raise LLMError("llm_response", result.retry_count) from None

    def choose_highlights(self, message, highlights):
        prompt = json.dumps({"USER_MESSAGE": message, "HIGHLIGHTS": highlights}, ensure_ascii=False)
        result = self._generate(PRESENTATION_PROMPT, [{"role": "user", "parts": [{"text": prompt}]}],
                                generation={"responseMimeType": "application/json",
                                            "responseJsonSchema": PresentationPlan.model_json_schema()})
        try:
            result.value = parse_json(self._text(result))
        except ValueError:
            raise LLMError("llm_response", result.retry_count) from None
        return result

    def rewrite(self, text):
        result = self._generate(REWRITE_PROMPT, [{"role": "user", "parts": [{"text": text}]}])
        result.value = self._text(result)
        return result

    def propose_tool(self, contents, declarations, allowed_names, system):
        declared = {d["name"] for d in declarations}
        if not allowed_names or not set(allowed_names) <= declared:
            raise ValueError("Allowed tools must be declared")
        result = self._generate(system, copy.deepcopy(contents), tools=[{"functionDeclarations": declarations}],
                                toolConfig={"functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": list(allowed_names)}})
        try:
            calls = [p["functionCall"] for p in result.value["parts"] if "functionCall" in p]
            if len(calls) != 1 or calls[0]["name"] not in allowed_names or not isinstance(calls[0]["args"], dict):
                raise ValueError("Invalid function call")
        except (KeyError, TypeError, ValueError):
            raise LLMError("invalid_function_call", result.retry_count) from None
        return result


def function_response(model_content, observation):
    """Return a Gemini tool-result turn; keep the original model content, including thought signatures."""
    calls = [p["functionCall"] for p in model_content["parts"] if "functionCall" in p]
    if len(calls) != 1:
        raise ValueError("Expected one function call")
    call = calls[0]
    response = {"name": call["name"], "response": observation}
    if "id" in call:
        response["id"] = call["id"]
    return [copy.deepcopy(model_content), {"role": "user", "parts": [{"functionResponse": response}]}]


def make_client(settings):
    return FakeClient() if settings.provider == "fake" else GeminiClient(settings)
