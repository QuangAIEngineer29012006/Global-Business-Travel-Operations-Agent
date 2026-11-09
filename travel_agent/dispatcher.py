import json
import time

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from .models import ResultMeta, ToolError, ToolResult
from .safety import safe_arguments
from .storage import StoreError
from .tools import ToolFault


class Dispatcher:
    def __init__(self, tools, settings):
        self.tools = tools
        self.settings = settings
        self.registry = tools.registry()

    def _check(self, state, call, eligible):
        spec = self.registry.get(call.name)
        if spec is None:
            raise ToolFault("unknown_tool")
        if state.workflow not in spec.workflows or call.name not in eligible:
            raise ToolFault("tool_not_allowed_in_phase")
        if state.role not in spec.roles:
            raise ToolFault("role_not_allowed")
        if not self.tools.store.session_is_active(state.session_id):
            raise ToolFault("session_revoked")
        if len(json.dumps(call.arguments, ensure_ascii=False)) > 4096:
            raise ToolFault("arguments_too_large")
        if not Draft202012Validator(spec.arguments.model_json_schema()).is_valid(call.arguments):
            raise ToolFault("invalid_arguments")
        args = spec.arguments.model_validate(call.arguments)
        if spec.name == "search_travel_policy" and (state.phase != "policy:" + args.category):
            raise ToolFault("invalid_arguments")
        for field in ("trip_id", "report_id", "traveler_id"):
            value = getattr(args, field, None)
            if value is None:
                continue
            allowed = {state.requested_ids.get(field)}
            for name in ("get_trip_request", "get_expense_report"):
                fact = state.latest(name)
                if fact:
                    allowed.add(fact.get(field))
            if value not in allowed:
                raise ToolFault("identifier_out_of_scope")
        if spec.write:
            approval = state.latest("get_approval_status")
            required = "not_requested" if spec.name == "request_approval" else "approved"
            if not approval or approval["status"] != required:
                raise ToolFault("approval_required")
        return spec, args

    def execute(self, state, call, eligible):
        started = time.monotonic()
        spec = self.registry.get(call.name)
        was_executed = False
        if state.step_count >= state.max_steps:
            result = self._failure("budget_exceeded")
        else:
            state.step_count += 1
            try:
                spec, args = self._check(state, call, eligible)
                if call.name == "search_travel_policy":
                    if state.retrieval_calls >= self.settings.max_retrieval_calls:
                        raise ToolFault("retrieval_budget_exceeded")
                    state.retrieval_calls += 1
                was_executed = True
                data = self.tools.invoke(spec, state, args)
                # Output schema is checked even when an implementation returns an apparently successful dict.
                if not Draft202012Validator(spec.output.model_json_schema()).is_valid(data):
                    raise ToolFault("invalid_tool_output")
                data = spec.output.model_validate(data).model_dump()
                result = ToolResult(ok=True, data=data, meta=ResultMeta(source="mock_" + spec.name,
                                                                       read_only=not spec.write))
            except (ToolFault, StoreError) as err:
                result = self._failure(err.code, getattr(err, "retryable", False),
                                       bool(spec and spec.write and was_executed))
            except (ValidationError, ValueError, TypeError, KeyError):
                result = self._failure("invalid_tool_output" if was_executed else "invalid_arguments",
                                       uncertain=bool(spec and spec.write and was_executed))
            except Exception:
                result = self._failure("tool_internal_error", uncertain=bool(spec and spec.write and was_executed))
        dumped = result.model_dump()
        state.safe_tool_results.append({"tool": call.name if spec else "unregistered",
                                        "arguments": safe_arguments(call.arguments), "result": dumped})
        code = "ok" if result.ok else result.error.code
        state.trace.append({"case_id": state.case_id, "run_id": state.run_id, "phase": state.phase,
                            "action": call.name if spec else "unregistered", "safe_arguments": safe_arguments(call.arguments),
                            "observation_status": code, "executed": was_executed, "transition": "observed",
                            "budget": {"steps": state.step_count, "max_steps": state.max_steps,
                                       "retrieval_calls": state.retrieval_calls, "model_calls": state.model_calls},
                            "latency_ms": round((time.monotonic() - started) * 1000, 3), "outcome": None})
        return result

    @staticmethod
    def _failure(code, retryable=False, uncertain=False):
        return ToolResult(ok=False, error=ToolError(code=code, message="Training tool could not complete: " + code,
                                                  retryable=retryable),
                          meta=ResultMeta(source="dispatcher", read_only=not uncertain,
                                          side_effect_may_have_occurred=uncertain))
