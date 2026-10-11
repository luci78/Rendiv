"""FastAPI health, authenticated enqueue and caller-scoped status endpoints."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import FastAPI, Header, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from typing import Any, Literal

from rendiv_api.config import Settings
from rendiv_api.http_controls import (
    BearerAuthenticationMiddleware,
    RequestBodyLimitMiddleware,
    RequestRateLimitMiddleware,
)
from rendiv_api.migrations import MigrationError, apply_migrations, database_is_ready
from rendiv_api.persistence import (
    BacklogFull,
    DatabaseNotReady,
    EnqueuePersistenceError,
    EnqueueRepository,
    IdempotencyConflict,
    InvalidEnqueue,
    PayloadTooLarge,
)
from rendiv_api.rate_limit import SlidingWindowRateLimiter


class EnqueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    operation: Literal["memory_add", "memory_update", "memory_maintain"]
    payload: dict[str, Any]


class EnqueueResponse(BaseModel):
    job_id: str
    state: Literal["queued"]
    queue_seq: int
    created_at: str
    replayed: bool
    status_url: str


class JobStatusResponse(BaseModel):
    job_id: str
    operation: Literal["memory_add", "memory_update", "memory_maintain"]
    state: Literal["queued", "running", "succeeded", "failed", "unknown"]
    effect_certainty: Literal["none", "partial", "complete", "unknown"]
    queue_seq: int
    created_at: str
    updated_at: str
    finished_at: str | None


def _utc_timestamp(timestamp_ms: int | None) -> str | None:
    if timestamp_ms is None:
        return None
    return datetime.fromtimestamp(timestamp_ms / 1_000, tz=timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def _error(status_code: int, code: str, message: str, *, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": code, "message": message},
        headers=headers,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings or Settings.from_environment()
    repository = EnqueueRepository(
        configured.database_path,
        busy_timeout_ms=configured.sqlite_busy_timeout_ms,
        max_payload_bytes=configured.max_payload_bytes,
        backlog_limit=configured.backlog_limit,
    )
    rate_limiter = SlidingWindowRateLimiter(
        limit=configured.rate_limit_requests,
        window_seconds=configured.rate_limit_window_seconds,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.database_ready = False
        try:
            apply_migrations(
                configured.database_path,
                busy_timeout_ms=configured.sqlite_busy_timeout_ms,
            )
            application.state.database_ready = True
        except MigrationError:
            # Fail closed: liveness remains available, readiness stays false.
            application.state.database_ready = False
        yield

    application = FastAPI(
        title="Rendiv API",
        version="0.1.0",
        docs_url=None if configured.app_env == "production" else "/docs",
        redoc_url=None,
        lifespan=lifespan,
        debug=False,
    )

    # Authentication and request limits wrap body processing; unauthenticated or
    # over-limit requests are rejected before JSON parsing.
    application.add_middleware(
        RequestBodyLimitMiddleware,
        max_request_bytes=configured.max_request_bytes,
    )
    application.add_middleware(
        RequestRateLimitMiddleware,
        limiter=rate_limiter,
        retry_after_seconds=configured.rate_limit_window_seconds,
    )
    application.add_middleware(
        BearerAuthenticationMiddleware,
        service_tokens=configured.service_tokens,
    )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        malformed_json = any(error.get("type") == "json_invalid" for error in exc.errors())
        if malformed_json:
            return _error(400, "invalid_json", "Request body is not valid JSON.")
        return _error(422, "validation_error", "Request body or headers are invalid.")

    @application.exception_handler(Exception)
    async def internal_error_handler(_request: Request, _exc: Exception) -> JSONResponse:
        return _error(500, "internal_error", "The request could not be completed.")

    @application.get("/healthz", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/readyz", tags=["health"])
    def readiness(response: Response) -> dict[str, str]:
        ready = bool(getattr(application.state, "database_ready", False))
        if ready:
            ready = database_is_ready(configured.database_path)
        if not ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "not_ready"}
        return {"status": "ready"}

    @application.post("/v1/jobs", status_code=202, response_model=EnqueueResponse)
    def enqueue_job(
        body: EnqueueRequest,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> EnqueueResponse | JSONResponse:
        principal = request.scope.get("state", {}).get("source_principal")
        # This identity is supplied only by bearer authentication middleware.
        if not isinstance(principal, str):
            return _error(401, "unauthorized", "A valid bearer credential is required.")
        if idempotency_key is None:
            return _error(422, "validation_error", "Idempotency-Key is required.")
        try:
            result = repository.enqueue(
                source_principal=principal,
                operation=body.operation,
                idempotency_key=idempotency_key,
                payload=body.payload,
            )
        except PayloadTooLarge:
            return _error(413, "payload_too_large", "Payload exceeds the configured limit.")
        except IdempotencyConflict:
            return _error(409, "idempotency_conflict", "Idempotency-Key is bound to another request.")
        except BacklogFull:
            return _error(429, "backlog_full", "The queued-job backlog limit has been reached.")
        except InvalidEnqueue:
            return _error(422, "validation_error", "Request body or headers are invalid.")
        except (DatabaseNotReady, EnqueuePersistenceError):
            return _error(503, "database_unavailable", "Rendiv storage is not available.")
        return EnqueueResponse(
            job_id=result.job_id,
            state="queued",
            queue_seq=result.queue_seq,
            created_at=_utc_timestamp(result.created_at_ms) or "",
            replayed=result.replay,
            status_url=f"/v1/jobs/{result.job_id}",
        )

    @application.get("/v1/jobs/{job_id}", response_model=JobStatusResponse)
    def get_job_status(job_id: str, request: Request) -> JobStatusResponse | JSONResponse:
        principal = request.scope.get("state", {}).get("source_principal")
        if not isinstance(principal, str):
            return _error(401, "unauthorized", "A valid bearer credential is required.")
        try:
            result = repository.get_status(job_id=job_id, source_principal=principal)
        except DatabaseNotReady:
            return _error(503, "database_unavailable", "Rendiv storage is not available.")
        if result is None:
            # Conceal whether a job exists under another principal.
            return _error(404, "not_found", "Job was not found.")
        return JobStatusResponse(
            job_id=result.job_id,
            operation=result.operation,  # type: ignore[arg-type]
            state=result.state,  # type: ignore[arg-type]
            effect_certainty=result.effect_certainty,  # type: ignore[arg-type]
            queue_seq=result.queue_seq,
            created_at=_utc_timestamp(result.created_at_ms) or "",
            updated_at=_utc_timestamp(result.updated_at_ms) or "",
            finished_at=_utc_timestamp(result.finished_at_ms),
        )

    return application
