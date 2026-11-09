from .llm_client import LLMError, function_response
from .prompts import TOOL_PROMPT


def read_tool_declarations(registry):
    """Expose only the three entry reads; schemas come from the existing dispatcher registry."""
    descriptions = {"get_trip_request": "Read one synthetic travel request.",
                    "get_itinerary": "Read one synthetic itinerary and disruption status.",
                    "get_expense_report": "Read one synthetic expense report."}
    return [{"name": name, "description": description, "parametersJsonSchema": registry[name][2]}
            for name, description in descriptions.items() if name in registry]


def tool_turn(client, contents, declarations, allowed_names, dispatcher, context):
    """One model proposal and at most one dispatcher invocation; no autonomous loop or retries of writes."""
    proposal = client.propose_tool(contents, declarations, allowed_names, TOOL_PROMPT)
    calls = [p["functionCall"] for p in proposal.value["parts"] if "functionCall" in p]
    declared = {d["name"] for d in declarations}
    if len(calls) != 1 or calls[0].get("name") not in set(allowed_names) & declared:
        raise LLMError("invalid_function_call", proposal.retry_count)
    call = calls[0]
    if not isinstance(call.get("args"), dict):
        raise LLMError("invalid_function_call", proposal.retry_count)
    # Caller binds IDs before the turn. A model cannot silently switch to another source record.
    bindings = context.get("bound_arguments", {})
    if not bindings or any(call["args"].get(key) != value for key, value in bindings.items()):
        raise LLMError("unbound_function_arguments", proposal.retry_count)
    ctx = {key: value for key, value in context.items() if key != "bound_arguments"}
    observation = dispatcher(call["name"], call["args"], ctx)
    if not isinstance(observation, dict) or type(observation.get("ok")) is not bool:
        raise LLMError("invalid_tool_result", proposal.retry_count)
    history = [*contents, *function_response(proposal.value, observation)]
    return {"observation": observation, "contents": history, "input_tokens": proposal.input_tokens,
            "output_tokens": proposal.output_tokens, "retry_count": proposal.retry_count}
