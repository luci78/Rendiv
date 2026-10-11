"""FastAPI application factory for health and readiness only."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Response, status

from rendiv_api.config import Settings
from rendiv_api.migrations import MigrationError, apply_migrations, database_is_ready


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings or Settings.from_environment()

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
    )

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

    return application
