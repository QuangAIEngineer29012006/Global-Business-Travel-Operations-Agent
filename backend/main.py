import threading
import time
import uuid
from collections import deque

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from travel_agent.agent import TravelAgent
from travel_agent.config import Settings
from travel_agent.models import PreferenceRequest, ResolveApproval, RunRequest, SessionRequest, TripID
from travel_agent.storage import Store, StoreError


class RateLimiter:
    def __init__(self):
        self.entries = {}
        self.lock = threading.Lock()

    def check(self, bucket, identity, limit):
        now = time.monotonic()
        with self.lock:
            self.entries = {k: q for k, q in self.entries.items() if q and q[-1] > now - 60}
            queue = self.entries.setdefault((bucket, identity), deque())
            while queue and queue[0] <= now - 60:
                queue.popleft()
            if len(queue) >= limit:
                raise StoreError("rate_limit", 429)
            queue.append(now)


def create_app(settings=None, store=None, model=None):
    settings = settings or Settings.from_env()
    store = store or Store(settings.workspace)
    agent = TravelAgent(settings, store=store, model=model)
    app = FastAPI(title="Global Business Travel Operations Agent (training)", version="1.0.0")
    app.state.agent = agent
    app.state.store = store
    limiter = RateLimiter()

    def error(request, status, code):
        return JSONResponse(status_code=status, content={"error": {"code": code, "message": code},
                              "request_id": getattr(request.state, "request_id", None)},
                            headers={"Retry-After": "60"} if status == 429 else {})

    @app.middleware("http")
    async def context(request, call_next):
        request.state.request_id = uuid.uuid4().hex
        try:
            ip = request.client.host if request.client else "local"
            limiter.check("http", ip, 120)
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 16384:
                    raise StoreError("request_too_large", 413)
            request._body = bytes(body)
            response = await call_next(request)
        except StoreError as err:
            response = error(request, err.status, err.code)
        except Exception:
            response = error(request, 500, "server_error")
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(StoreError)
    async def store_error(request, exc):
        return error(request, exc.status, exc.code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error(request, 422, "invalid_request")

    def session(request):
        return store.authenticate(request.headers.get("Authorization"))

    @app.get("/api/health")
    def health():
        return {"status": "ok", "training_only": True, "provider": settings.provider,
                "model_id": agent.model.model_id, "tools": len(agent.dispatcher.registry)}

    @app.get("/api/training-users")
    def users():
        return {"users": store.dataset["users"], "notice": "Public synthetic identities; not production authentication."}

    @app.post("/api/sessions", status_code=201)
    def new_session(body: SessionRequest, request: Request):
        limiter.check("session", request.client.host if request.client else "local", 20)
        return store.create_session(body.user_id)

    @app.delete("/api/sessions/current")
    def revoke(request: Request):
        store.revoke(session(request)["session_id"])
        return {"revoked": True}

    @app.post("/api/runs")
    def run(body: RunRequest, request: Request):
        caller = session(request)
        limiter.check("run", caller["session_id"], 10)
        return agent.run(caller, body)

    @app.get("/api/runs/{run_id}")
    def inspect_run(run_id: str, request: Request):
        return store.get_run(session(request), run_id)

    @app.get("/api/drafts/{draft_id}")
    def inspect_draft(draft_id: str, request: Request):
        return store.get_draft(session(request), draft_id)

    @app.get("/api/preferences")
    def preferences(request: Request):
        return store.preferences(session(request)["user_id"])

    @app.put("/api/preferences")
    def remember(body: PreferenceRequest, request: Request):
        return store.save_preferences(session(request)["user_id"], body.model_dump(exclude={"remember"}, exclude_none=True))

    @app.delete("/api/preferences")
    def forget(request: Request):
        store.delete_preferences(session(request)["user_id"])
        return {"deleted": True}

    @app.post("/api/mock-approvals/{trip_id}")
    def resolve_approval(trip_id: TripID, body: ResolveApproval, request: Request):
        return store.resolve_mock_approval(session(request), trip_id, body.status)

    @app.get("/api/tools")
    def tools():
        return {"tools": [{**spec.declaration(), "workflows": sorted(spec.workflows),
                           "roles": sorted(spec.roles), "write": spec.write}
                          for spec in agent.dispatcher.registry.values()]}

    return app
