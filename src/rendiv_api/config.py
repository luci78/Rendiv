"""Typed application configuration with an explicit environment allowlist."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Settings(BaseModel):
    """Non-secret settings needed to start the API scaffold."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    app_env: Literal["development", "test", "production"] = "development"
    database_path: Path = Path("/var/lib/rendiv/rendiv.sqlite3")
    sqlite_busy_timeout_ms: int = Field(default=5_000, ge=0, le=60_000)
    max_payload_bytes: int = Field(default=262_144, ge=1, le=16_777_216)

    @classmethod
    def from_environment(cls) -> "Settings":
        """Read only named, non-secret settings; never dump the process environment."""

        raw: dict[str, str] = {}
        names = {
            "RENDIV_APP_ENV": "app_env",
            "RENDIV_DATABASE_PATH": "database_path",
            "RENDIV_SQLITE_BUSY_TIMEOUT_MS": "sqlite_busy_timeout_ms",
            "RENDIV_MAX_PAYLOAD_BYTES": "max_payload_bytes",
        }
        for env_name, field_name in names.items():
            if env_name in os.environ:
                raw[field_name] = os.environ[env_name]

        try:
            return cls.model_validate(raw)
        except ValidationError as exc:
            # Validation errors include only the allowlisted non-secret fields.
            raise ValueError("invalid Rendiv application configuration") from exc
