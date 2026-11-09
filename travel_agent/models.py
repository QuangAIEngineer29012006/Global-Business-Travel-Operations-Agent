from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


Role = Literal["employee", "reviewer", "approver"]
Workflow = Literal["pre_trip", "in_trip", "expense", "status", "policy", "direct", "rewrite"]
TripID = Annotated[str, StringConstraints(pattern=r"^TRIP-\d{4}-\d{3}$")]
ReportID = Annotated[str, StringConstraints(pattern=r"^EXP-\d{4}-\d{3}$")]
TravelerID = Annotated[str, StringConstraints(pattern=r"^TRV-\d{3}$")]
RequestKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{8,100}$")]
Category = Literal["travel", "expense", "visa", "insurance", "approval"]
Outcome = Literal["completed", "needs_input", "needs_human", "awaiting_approval", "failed_validation",
                  "budget_exceeded", "tool_failed", "partial", "failed_delivery"]


class RunRequest(StrictModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    request_id: RequestKey
    workflow: Workflow | None = None
    trip_id: TripID | None = None
    report_id: ReportID | None = None
    case_id: Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{1,80}$")] | None = None


class SessionRequest(StrictModel):
    user_id: Annotated[str, StringConstraints(pattern=r"^demo-[a-z]+$")]


class PreferenceRequest(StrictModel):
    remember: Literal[True]
    response_language: Literal["vi", "en"] | None = None
    preferred_output_format: Literal["markdown", "json"] | None = None

    @model_validator(mode="after")
    def has_preference(self):
        if self.response_language is None and self.preferred_output_format is None:
            raise ValueError("Choose at least one preference")
        return self


class ToolCall(StrictModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    arguments: dict[str, Any]


class ToolError(StrictModel):
    code: str
    message: str
    retryable: bool = False


class ResultMeta(StrictModel):
    source: str
    read_only: bool
    side_effect_may_have_occurred: bool = False


class ToolResult(StrictModel):
    ok: bool
    data: dict[str, Any] | None = None
    error: ToolError | None = None
    meta: ResultMeta

    @model_validator(mode="after")
    def consistent(self):
        if self.ok and (self.data is None or self.error is not None):
            raise ValueError("Successful tool requires data only")
        if not self.ok and self.error is None:
            raise ValueError("Failed tool requires an error")
        return self


class TripArgs(StrictModel):
    trip_id: TripID


class ProfileArgs(StrictModel):
    traveler_id: TravelerID


class ReportArgs(StrictModel):
    report_id: ReportID


class SearchArgs(StrictModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)]
    category: Category
    max_results: Annotated[int, Field(ge=1, le=5)]


class ApprovalArgs(StrictModel):
    trip_id: TripID
    action_summary: Literal["Review training travel request"]


class ResolveApproval(StrictModel):
    status: Literal["approved", "rejected"]


class Trip(StrictModel):
    trip_id: TripID
    traveler_id: TravelerID
    owner_id: str
    destination: str | None
    start_date: str | None
    end_date: str | None
    purpose: str | None
    status: Literal["planned", "in_progress", "completed", "cancelled"]


class Profile(StrictModel):
    traveler_id: TravelerID
    owner_id: str
    department: str
    preference: dict[str, str]


class Itinerary(StrictModel):
    trip_id: TripID
    flight: str
    hotel: str
    event: str
    disruption: Literal["none", "delayed", "cancelled"]
    delay_minutes: Annotated[int, Field(ge=0)]


class Approval(StrictModel):
    trip_id: TripID
    status: Literal["not_requested", "pending", "approved", "rejected"]
    approval_id: str
    action_summary: str
    mock: Literal[True] = True


class ExpenseItem(StrictModel):
    item_id: str
    category: Literal["meal", "hotel", "transport"]
    date: str | None
    amount_minor: Annotated[int, Field(ge=0)] | None
    currency: str
    receipt: bool


class ExpenseReport(StrictModel):
    report_id: ReportID
    trip_id: TripID
    owner_id: str
    status: Literal["draft"]
    currency: str
    items: list[ExpenseItem]


class Citation(StrictModel):
    chunk_id: str
    doc_id: str
    source: str
    section: str
    version: str
    category: Category


class PolicyChunk(Citation):
    text: str
    destinations: list[str]
    workflows: list[str]
    access_roles: list[Role]
    active: bool
    rule: dict[str, Any]


class SearchResult(StrictModel):
    chunks: list[PolicyChunk]
    scores: list[float]
    rejected_chunks: list[str]


class Claim(StrictModel):
    text: str
    quote: str
    citation: Citation


class Calculation(StrictModel):
    report_id: ReportID
    currency: str
    total_minor: int
    totals_by_category: dict[str, int]
    totals_by_day: dict[str, dict[str, int]]
    missing_fields: list[str]
    missing_receipts: list[str]
    currency_errors: list[str]
    arithmetic: Literal["integer_minor_units"] = "integer_minor_units"


class Validation(StrictModel):
    source_id: str
    missing_fields: list[str]
    reviewer_flags: list[dict[str, Any]]
    checklist: list[str]
    claims: list[Claim]


class Draft(StrictModel):
    draft_id: str
    kind: Literal["travel_checklist", "disruption_escalation", "expense_review"]
    source_ids: list[str]
    status: Literal["draft_created"] = "draft_created"
    delivery_status: Literal["not_sent"] = "not_sent"
    facts: dict[str, Any]
    policy_claims: list[Claim]
    items_for_review: list[Any]
    mock: Literal[True] = True


class RunState(StrictModel):
    run_id: str
    case_id: str | None
    user_id: str
    session_id: str
    role: Role
    request_id: str
    workflow: Workflow
    phase: str = "input"
    requested_ids: dict[str, str] = Field(default_factory=dict)
    step_count: int = 0
    max_steps: int
    model_calls: int = 0
    retrieval_calls: int = 0
    query_rewrites: int = 0
    retry_count: int = 0
    safe_tool_results: list[dict[str, Any]] = Field(default_factory=list)
    trace: list[dict[str, Any]] = Field(default_factory=list)
    outcome: Outcome | None = None
    artifacts: list[Draft] = Field(default_factory=list)

    def latest(self, tool):
        for item in reversed(self.safe_tool_results):
            if item["tool"] == tool and item["result"]["ok"]:
                return item["result"]["data"]
        return None

    def chunks(self):
        return [c for item in self.safe_tool_results if item["tool"] == "search_travel_policy"
                and item["result"]["ok"] for c in item["result"]["data"]["chunks"]]
