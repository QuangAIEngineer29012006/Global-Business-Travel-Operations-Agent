from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.dev_systems import MockSystems

from .config import Settings
from .llm_client import make_client
from .models import AgentRequest
from .service import LLMService


def create_app(settings=None, dispatcher=None, client=None):
    settings = settings or Settings.from_env()
    dispatcher = dispatcher if dispatcher is not None else MockSystems()
    client = client if client is not None else make_client(settings)
    service = LLMService(client, dispatcher)
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

    return app
