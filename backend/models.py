from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class Actor(StrictModel):
    role: Literal["employee", "travel_operations_reviewer", "approver"]
    actor_id: Identifier


class Context(StrictModel):
    # The shared workflow returns failed_validation for malformed domain IDs.
    trip_id: Annotated[str, StringConstraints(max_length=40)] | None = None
    report_id: Annotated[str, StringConstraints(max_length=40)] | None = None


class AgentRequest(StrictModel):
    request_id: Identifier
    actor: Actor
    session_id: Identifier
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    context: Context = Field(default_factory=Context)


class PreferenceUpdate(StrictModel):
    key: Literal["response_language", "preferred_output_format"]
    value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class ApprovalRequest(StrictModel):
    request_id: Identifier
    actor: Actor
    session_id: Identifier
    trip_id: Annotated[str, StringConstraints(pattern=r"^TRIP-\d{4}-\d{3}$", max_length=40)]
    action_summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=240)]
    idempotency_key: Annotated[str, StringConstraints(min_length=4, max_length=120)]


PreferenceKey = Literal["response_language", "preferred_output_format"]


class PresentationPlan(StrictModel):
    highlight_ids: Annotated[list[Annotated[str, StringConstraints(max_length=40)]], Field(max_length=6)]
