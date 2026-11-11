from copy import deepcopy
from dataclasses import dataclass, field

from .llm_client import LLMError, ModelResult, function_response, single_function_call
from .prompts import TOOL_PROMPT


@dataclass(frozen=True)
class ToolProposal:
    name: str
    arguments: dict
    generation: ModelResult = field(repr=False)


def read_tool_declarations(registry):
    """Expose entry reads and the explicitly requested pending-only approval simulation."""
    descriptions = {"get_trip_request": "Read one synthetic travel request.",
                    "get_approval_status": "Read the current approval status of one synthetic trip.",
                    "get_itinerary": "Read one synthetic itinerary and disruption status.",
                    "get_expense_report": "Read one synthetic expense report.",
                    "request_approval": "Create a pending-only approval simulation when explicitly requested by the user."}
    return [{"name": name, "description": description, "parametersJsonSchema": registry[name][2]}
            for name, description in descriptions.items() if name in registry]


def propose_tool_call(client, contents, declarations, allowed_names, *, bound_arguments,
                      explicit_approval_request=False):
    """Request one proposal. The caller owns execution, trace and the remaining budget."""
    allowed = set(allowed_names)
    if not allowed or not allowed <= {d["name"] for d in declarations}:
        raise ValueError("Allowed tools must be declared")
    if explicit_approval_request is not True:
        allowed.discard("request_approval")
        if not allowed:
            raise LLMError("approval_request_not_explicit")
    if not bound_arguments:
        raise LLMError("unbound_function_arguments")

    candidates = [d for d in declarations if d["name"] in allowed]
    generation = client.propose_tool(contents, candidates, sorted(allowed), TOOL_PROMPT)
    try:
        call = single_function_call(generation.value)
        if call["name"] not in allowed:
            raise ValueError("Tool outside caller allowlist")
    except ValueError:
        raise LLMError("invalid_function_call", generation.retry_count, result=generation) from None

    name, arguments = call["name"], call["args"]
    if any(key not in arguments or arguments[key] != value for key, value in bound_arguments.items()):
        raise LLMError("unbound_function_arguments", generation.retry_count, result=generation)
    if name == "request_approval" and set(arguments) != set(bound_arguments):
        raise LLMError("unbound_function_arguments", generation.retry_count, result=generation)
    return ToolProposal(name, deepcopy(arguments), generation)


def complete_tool_turn(contents, proposal, observation):
    """Validate an executor observation and preserve the Gemini function-response history."""
    generation = proposal.generation
    if not isinstance(observation, dict) or type(observation.get("ok")) is not bool:
        raise LLMError("invalid_tool_result", generation.retry_count, result=generation)
    if observation["ok"]:
        meta = observation.get("meta")
        valid = (isinstance(observation.get("data"), dict) and "error" not in observation
                 and isinstance(meta, dict) and isinstance(meta.get("source_system"), str)
                 and bool(meta["source_system"].strip()) and type(meta.get("read_only")) is bool)
    else:
        error = observation.get("error")
        valid = (isinstance(error, dict) and "data" not in observation
                 and isinstance(error.get("code"), str) and bool(error["code"].strip())
                 and isinstance(error.get("message"), str) and bool(error["message"].strip())
                 and type(error.get("retryable")) is bool)
    if not valid:
        raise LLMError("invalid_tool_result", generation.retry_count, result=generation)
    history = [*contents, *function_response(generation.value, observation)]
    return {"tool_name": proposal.name, "observation": observation, "contents": history,
            "input_tokens": generation.input_tokens, "output_tokens": generation.output_tokens,
            "retry_count": generation.retry_count}


def tool_turn(client, contents, declarations, allowed_names, dispatcher, context):
    """Run a single proposal and dispatch for the standalone demo and smoke tests."""
    proposal = propose_tool_call(
        client, contents, declarations, allowed_names,
        bound_arguments=context.get("bound_arguments", {}),
        explicit_approval_request=context.get("explicit_approval_request", False),
    )
    ctx = {key: value for key, value in context.items() if key != "bound_arguments"}
    observation = dispatcher(proposal.name, proposal.arguments, ctx)
    return complete_tool_turn(contents, proposal, observation)
