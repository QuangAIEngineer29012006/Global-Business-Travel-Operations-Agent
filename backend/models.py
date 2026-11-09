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


class PresentationPlan(StrictModel):
    highlight_ids: Annotated[list[Annotated[str, StringConstraints(max_length=40)]], Field(max_length=6)]
