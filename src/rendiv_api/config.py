"""Typed application configuration with an explicit environment allowlist."""

from __future__ import annotations

import json
import hashlib
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)


class Settings(BaseModel):
    """Typed API settings; service tokens are accepted only from the environment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    app_env: Literal["development", "test", "production"] = "development"
    database_path: Path = Path("/var/lib/rendiv/rendiv.sqlite3")
    sqlite_busy_timeout_ms: int = Field(default=5_000, ge=0, le=60_000)
    max_payload_bytes: int = Field(default=262_144, ge=1, le=16_777_216)
    max_request_bytes: int = Field(default=278_528, ge=1, le=16_793_600)
    service_tokens: dict[str, SecretStr] = Field(default_factory=dict, repr=False)
    rate_limit_requests: int = Field(default=10, ge=1, le=100_000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=86_400)
    backlog_limit: int = Field(default=1_000, ge=1, le=10_000_000)

    @field_validator("service_tokens")
    @classmethod
    def validate_service_tokens(cls, tokens: dict[str, SecretStr]) -> dict[str, SecretStr]:
        principal_pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
        token_pattern = re.compile(r"^[A-Za-z0-9._~-]{32,512}$")
        digests: set[bytes] = set()
        for principal, secret in tokens.items():
            token = secret.get_secret_value()
            digest = hashlib.sha256(token.encode("ascii", errors="ignore")).digest()
            if not principal_pattern.fullmatch(principal) or not token_pattern.fullmatch(token):
                raise ValueError("service token configuration is invalid")
            if digest in digests:
                raise ValueError("service token configuration is invalid")
            digests.add(digest)
        return tokens

    @model_validator(mode="after")
    def validate_limits_and_production_configuration(self) -> "Settings":
        if self.max_request_bytes < self.max_payload_bytes:
            raise ValueError("request byte limit must cover the payload byte limit")
        if self.app_env == "production":
            required = {
                "service_tokens", "max_payload_bytes", "max_request_bytes",
                "rate_limit_requests", "rate_limit_window_seconds", "backlog_limit",
            }
            if not self.service_tokens or not required.issubset(self.model_fields_set):
                raise ValueError("production API credentials and limits must be explicit")
        return self

    @classmethod
    def from_environment(cls) -> "Settings":
        """Read an explicit allowlist; never dump environment values or secrets."""

        raw: dict[str, str] = {}
        names = {
            "RENDIV_APP_ENV": "app_env",
            "RENDIV_DATABASE_PATH": "database_path",
            "RENDIV_SQLITE_BUSY_TIMEOUT_MS": "sqlite_busy_timeout_ms",
            "RENDIV_MAX_PAYLOAD_BYTES": "max_payload_bytes",
            "RENDIV_MAX_REQUEST_BYTES": "max_request_bytes",
            "RENDIV_RATE_LIMIT_REQUESTS": "rate_limit_requests",
            "RENDIV_RATE_LIMIT_WINDOW_SECONDS": "rate_limit_window_seconds",
            "RENDIV_BACKLOG_LIMIT": "backlog_limit",
        }
        for env_name, field_name in names.items():
            if env_name in os.environ:
                raw[field_name] = os.environ[env_name]

        if "RENDIV_API_TOKENS_JSON" in os.environ:
            try:
                tokens = json.loads(os.environ["RENDIV_API_TOKENS_JSON"])
                if not isinstance(tokens, dict) or not all(
                    isinstance(key, str) and isinstance(value, str)
                    for key, value in tokens.items()
                ):
                    raise ValueError
                raw["service_tokens"] = tokens
            except (ValueError, TypeError):
                raise ValueError("invalid Rendiv application configuration") from None

        try:
            return cls.model_validate(raw)
        except ValidationError:
            # Validation details may contain values from the secret token map.
            raise ValueError("invalid Rendiv application configuration") from None
