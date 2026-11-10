import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.dev_systems import MockSystems

from .config import ROOT, Settings
from .llm_client import make_client
from .models import ApprovalRequest, AgentRequest, Identifier, PreferenceKey, PreferenceUpdate
from .service import LLMService
from .state_store import StateStore


def create_app(settings=None, dispatcher=None, client=None, state_store=None):
    settings = settings or Settings.from_env()
    state_store = state_store or StateStore(
        settings.state_db_path or str(ROOT / "data" / "processed" / "agent_state.sqlite")
    )
    dispatcher = dispatcher if dispatcher is not None else MockSystems(
        draft_store=state_store, approval_store=state_store
    )
    client = client if client is not None else make_client(settings)
    service = LLMService(client, dispatcher, state_store)
    app = FastAPI(title="Travel Agent LLM Backend (training)", version="2.0.0")
    app.state.service = service

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(status_code=422, content={"error": {"code": "INVALID_REQUEST", "message": "Request không đúng contract."}})

    @app.middleware("http")
    async def request_boundary(request: Request, call_next):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 16384:
                return JSONResponse(status_code=413, content={"error": {"code": "REQUEST_TOO_LARGE"}})
        request._body = bytes(body)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    def health():
        return {"status": "ok", "provider": settings.provider, "model_id": client.model_id, "training_only": True}

    @app.post("/api/runs")
    def run(body: AgentRequest):
        # Actor is a synthetic fixture identity as specified by contract 02; this is not production authentication.
        return service.run(body.model_dump(exclude_none=True))

    @app.post("/api/approval-requests")
    def request_approval(body: ApprovalRequest):
        run_id = f"RUN-{uuid.uuid4().hex[:8]}"
        actor = body.actor.model_dump()
        observation = dispatcher("request_approval", {
            "trip_id": body.trip_id, "action_summary": body.action_summary,
            "idempotency_key": body.idempotency_key,
        }, {"workflow": "pre_trip", "actor": actor, "run_id": run_id,
            "request_id": body.request_id, "explicit_approval_request": True})
        result_data = observation.get("data") if isinstance(observation, dict) else None
        result_meta = observation.get("meta") if isinstance(observation, dict) else None
        valid_success = (isinstance(observation, dict) and observation.get("ok") is True
                         and isinstance(result_data, dict) and result_data.get("status") == "pending"
                         and isinstance(result_data.get("approval_id"), str)
                         and result_data.get("trip_id") == body.trip_id
                         and isinstance(result_meta, dict)
                         and isinstance(result_meta.get("source_system"), str)
                         and bool(result_meta.get("source_system", "").strip())
                         and result_meta.get("read_only") is False and "error" not in observation)
        valid_error = (isinstance(observation, dict) and observation.get("ok") is False
                       and isinstance(observation.get("error"), dict)
                       and isinstance(observation["error"].get("code"), str)
                       and isinstance(observation["error"].get("message"), str)
                       and isinstance(observation["error"].get("retryable"), bool))
        if not valid_success and not valid_error:
            observation = {"ok": False, "error": {"code": "INTERNAL_ERROR",
                                                     "message": "Approval simulation returned an invalid tool result."}}
        ok = valid_success
        error = observation.get("error", {})
        status_by_error = {"UNAUTHORIZED": "rejected", "INVALID_ARGUMENT": "failed_validation",
                           "NOT_FOUND": "needs_input", "CONFLICT": "needs_human"}
        status = "awaiting_approval" if ok else status_by_error.get(error.get("code"), "needs_human")
        reason = "APPROVAL_REQUEST_CREATED" if ok else error.get("code", "INTERNAL_ERROR")
        trace = [{"trace_id": f"{run_id}:1", "run_id": run_id, "step": 1,
                  "workflow": "pre_trip", "phase": "approval_simulation", "action": "request_approval",
                  "safe_args": {"trip_id": body.trip_id, "action_summary": "[redacted]",
                                "idempotency_key": "[redacted]"},
                  "observation_status": "ok" if ok else f"error:{reason}",
                  "observation_summary": ({"ok": True, "source_system": observation.get("meta", {}).get("source_system"),
                                           "data_fields": sorted(observation.get("data", {}))}
                                          if ok else {"ok": False, "error_code": reason}),
                  "retry_count": 0, "transition": "awaiting_approval" if ok else "stop",
                  "budget": {"steps": "1/1"}, "outcome": status},
                 {"trace_id": f"{run_id}:2", "run_id": run_id, "step": 1,
                  "workflow": "pre_trip", "phase": "terminal", "action": "terminal",
                  "safe_args": {"reason_code": reason}, "observation_status": "ok",
                  "retry_count": 0, "transition": "end", "budget": {"steps": "1/1"},
                  "outcome": status}]
        result = {"request_id": body.request_id, "run_id": run_id, "workflow": "pre_trip",
                  "status": status, "reason_code": reason,
                  "message": ("Đã tạo yêu cầu approval mô phỏng; trạng thái đang pending, chưa được duyệt."
                              if ok else error.get("message", "Không thể tạo yêu cầu approval mô phỏng.")),
                  "data": observation.get("data", {}), "evidence": [], "artifacts": [],
                  "next_action": "Approver cần xem xét và quyết định trong hệ thống giả lập." if ok else None,
                  "steps": 1, "trace": trace}
        state_store.save_run({"request_id": body.request_id, "session_id": body.session_id,
                              "actor": actor}, result)
        return result

    # These routes use synthetic actor IDs and are only for the local training prototype.
    @app.get("/api/preferences/{actor_id}")
    def read_preferences(actor_id: Identifier):
        return {"actor_id": actor_id, "preferences": state_store.get_preference(actor_id)}

    @app.put("/api/preferences/{actor_id}")
    def write_preference(actor_id: Identifier, body: PreferenceUpdate):
        try:
            state_store.set_preference(actor_id, body.key, body.value)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return {"actor_id": actor_id, "key": body.key, "value": body.value, "saved": True}

    @app.delete("/api/preferences/{actor_id}")
    def remove_preference(actor_id: Identifier, key: PreferenceKey | None = None):
        deleted = state_store.delete_preference(actor_id, key)
        return {"actor_id": actor_id, "deleted": deleted}

    app.state.state_store = state_store

    return app
