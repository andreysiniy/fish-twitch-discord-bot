import logging
import uuid

import uvicorn
from api.routes import (
    actions,
    admin,
    auth,
    discord_admin,
    discord_integrations,
    discord_streamelements,
    economy,
    fishing,
    inventory,
)
from api.dependencies import _SE_CLIENT
from core.api_errors import ApiProblem
from core.config import settings
from core import metrics as metrics_module
from core.logging_config import configure_logging, reset_request_id, set_request_id
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from infrastructure.database import SessionLocal
from infrastructure.migration_status import get_schema_revisions
from infrastructure.redis_client import RedisClient
from sqlalchemy import text

configure_logging(settings.LOG_LEVEL)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Fisher Bot Game Engine",
    description="Microservice for fishing mechanics, RNG, and RPG progression.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-API-Key"],
)

app.include_router(auth.router, prefix="/v1/auth", tags=["Auth"])
app.include_router(fishing.router, prefix="/v1", tags=["Fishing"])
app.include_router(admin.router, prefix="/v1/admin", tags=["Admin Panel"])
app.include_router(inventory.router, prefix="/v1/inventory", tags=["Inventory"])
app.include_router(economy.router, prefix="/v1", tags=["Economy"])
app.include_router(actions.router, prefix="/v1/actions", tags=["External Actions"])
app.include_router(
    discord_integrations.router,
    prefix="/v1",
    tags=["Discord Integration"],
)
app.include_router(discord_admin.router, prefix="/v1/admin", tags=["Discord Admin"])
app.include_router(
    discord_streamelements.router,
    prefix="/v1/integrations/discord",
    tags=["Discord StreamElements"],
)


@app.on_event("shutdown")
async def close_provider_client() -> None:
    await _SE_CLIENT.close()


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    token = set_request_id(request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        reset_request_id(token)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, error: Exception) -> JSONResponse:
    logger.exception(
        "Unhandled request error",
        extra={"method": request.method, "path": request.url.path},
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


@app.exception_handler(ApiProblem)
async def api_problem_handler(request: Request, error: ApiProblem) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"detail": error.detail()})


@app.exception_handler(RequestValidationError)
async def request_validation_handler(
    request: Request,
    error: RequestValidationError,
) -> JSONResponse:
    fields = {".".join(str(part) for part in item["loc"]): item["msg"] for item in error.errors()}
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "fields": fields,
                "request_id": request.headers.get("X-Request-ID"),
            }
        },
    )


@app.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "healthy", "service": "game_engine"}


@app.get("/health/ready")
def readiness() -> dict[str, str]:
    diagnostics = {"database": "unavailable", "redis": "unavailable", "schema": "unknown"}
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        diagnostics["database"] = "connected"
        current_revision, expected_revision = get_schema_revisions()
        if current_revision != expected_revision:
            diagnostics["schema"] = f"outdated:{current_revision or 'none'}"
            raise RuntimeError("Database schema revision is not current")
        diagnostics["schema"] = current_revision or "unknown"
        RedisClient.get_client().ping()
        diagnostics["redis"] = "connected"
    except Exception as error:
        logger.warning("Readiness check failed: %s", type(error).__name__)
        raise HTTPException(status_code=503, detail=diagnostics) from error
    finally:
        db.close()

    return {"status": "ready", "service": "game_engine", **diagnostics}


@app.get("/health")
def health_check() -> dict[str, str]:
    return readiness()


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> PlainTextResponse:
    """Expose the process counters to a Prometheus-compatible scrape."""
    return PlainTextResponse(metrics_module.prometheus_text())


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
