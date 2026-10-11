"""Internal, SQLite-only enqueue persistence (no transport or external calls)."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import rfc8785

from rendiv_api.migrations import (
    MigrationError,
    configure_write_connection,
    database_is_ready,
    load_migrations,
    verify_migration_state,
)


OPERATIONS = frozenset({"memory_add", "memory_update", "memory_maintain"})
PAYLOAD_FORMAT = "json-v1"
_PRINCIPAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class EnqueueError(RuntimeError):
    """Base class for safe, internal enqueue failures."""


class InvalidEnqueue(EnqueueError, ValueError):
    """Raised when an internal enqueue request violates the data contract."""


class IdempotencyConflict(EnqueueError):
    """The idempotency identity was previously used for a different payload."""


class DatabaseNotReady(EnqueueError):
    """The database is not fully migrated and ready for writes."""


class EnqueuePersistenceError(EnqueueError):
    """SQLite rejected the transaction; no partial enqueue was committed."""


@dataclass(frozen=True)
class EnqueueResult:
    job_id: str
    state: str
    queue_seq: int
    created_at_ms: int
    replay: bool


def _uuid7() -> str:
    """Generate an RFC 9562 UUIDv7 on Python versions without uuid.uuid7."""

    timestamp_ms = time.time_ns() // 1_000_000
    if timestamp_ms >= 1 << 48:
        raise EnqueueError("current time is outside the UUIDv7 range")
    random_bits = secrets.randbits(74)
    rand_a = random_bits >> 62
    rand_b = random_bits & ((1 << 62) - 1)
    value = (
        (timestamp_ms << 80)
        | (0x7 << 76)
        | (rand_a << 64)
        | (0b10 << 62)
        | rand_b
    )
    return str(uuid.UUID(int=value))


def _canonical_payload(payload: Any, *, max_payload_bytes: int) -> str:
    if not isinstance(payload, dict):
        raise InvalidEnqueue("payload must be a JSON object")
    try:
        payload_bytes = rfc8785.dumps(payload)
    except (rfc8785.CanonicalizationError, TypeError, ValueError, OverflowError) as exc:
        raise InvalidEnqueue("payload is not valid RFC 8785 JSON") from exc
    if len(payload_bytes) > max_payload_bytes:
        raise InvalidEnqueue("payload exceeds configured byte limit")
    return payload_bytes.decode("utf-8")


class EnqueueRepository:
    """Persist queued requests in SQLite without making any network calls."""

    def __init__(
        self,
        database_path: Path,
        *,
        busy_timeout_ms: int = 5_000,
        max_payload_bytes: int = 262_144,
        migration_directory: Path | None = None,
    ) -> None:
        if not 0 <= busy_timeout_ms <= 60_000:
            raise ValueError("busy_timeout_ms must be between 0 and 60000")
        if not 1 <= max_payload_bytes <= 16_777_216:
            raise ValueError("max_payload_bytes is outside the supported range")
        self._database_path = Path(database_path)
        self._busy_timeout_ms = busy_timeout_ms
        self._max_payload_bytes = max_payload_bytes
        self._migration_directory = migration_directory

    def enqueue(
        self,
        *,
        source_principal: str,
        operation: str,
        idempotency_key: str,
        payload: Any,
    ) -> EnqueueResult:
        """Atomically insert job and audit event, or return an exact replay."""

        if not isinstance(source_principal, str) or not _PRINCIPAL.fullmatch(source_principal):
            raise InvalidEnqueue("source principal is invalid")
        if not isinstance(operation, str) or operation not in OPERATIONS:
            raise InvalidEnqueue("operation is not allowed")
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_KEY.fullmatch(
            idempotency_key
        ):
            raise InvalidEnqueue("idempotency key is invalid")

        payload_json = _canonical_payload(
            payload,
            max_payload_bytes=self._max_payload_bytes,
        )
        canonical_payload = json.loads(payload_json)
        payload_envelope = rfc8785.dumps(
            {
                "operation": operation,
                "payload_format": PAYLOAD_FORMAT,
                "payload": canonical_payload,
            }
        )
        digest = hashlib.sha256(payload_envelope).digest()

        # Startup readiness can fail while the HTTP process remains alive.
        # Recheck before opening any writer, then verify again under the write lock.
        if not database_is_ready(
            self._database_path,
            migration_directory=self._migration_directory,
        ):
            raise DatabaseNotReady("SQLite is not ready for enqueue")

        try:
            connection = sqlite3.connect(
                self._database_path,
                timeout=self._busy_timeout_ms / 1_000,
                isolation_level=None,
            )
        except sqlite3.Error as exc:
            raise DatabaseNotReady("SQLite is not ready for enqueue") from exc

        try:
            configure_write_connection(
                connection,
                busy_timeout_ms=self._busy_timeout_ms,
                enable_wal=True,
            )
            connection.execute("BEGIN IMMEDIATE")
            verify_migration_state(
                connection,
                migration_directory=self._migration_directory,
            )

            existing = connection.execute(
                "SELECT job_id, state, queue_seq, created_at_ms, payload_sha256 "
                "FROM jobs WHERE source_principal = ? AND operation = ? "
                "AND idempotency_key = ?",
                (source_principal, operation, idempotency_key),
            ).fetchone()
            if existing is not None:
                job_id, state, queue_seq, created_at_ms, stored_digest = existing
                if not hmac.compare_digest(bytes(stored_digest), digest):
                    raise IdempotencyConflict(
                        "idempotency key is already bound to a different payload"
                    )
                connection.commit()
                return EnqueueResult(
                    job_id=str(job_id),
                    state=str(state),
                    queue_seq=int(queue_seq),
                    created_at_ms=int(created_at_ms),
                    replay=True,
                )

            queue_seq = int(
                connection.execute(
                    "SELECT COALESCE(MAX(queue_seq), 0) + 1 FROM jobs"
                ).fetchone()[0]
            )
            now_ms = time.time_ns() // 1_000_000
            job_id = _uuid7()
            connection.execute(
                "INSERT INTO jobs (job_id, source_principal, operation, "
                "idempotency_key, payload_format, payload_json, payload_sha256, "
                "state, effect_certainty, queue_seq, created_at_ms, updated_at_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 'none', ?, ?, ?)",
                (
                    job_id,
                    source_principal,
                    operation,
                    idempotency_key,
                    PAYLOAD_FORMAT,
                    payload_json,
                    digest,
                    queue_seq,
                    now_ms,
                    now_ms,
                ),
            )
            connection.execute(
                "INSERT INTO job_events (event_id, job_id, event_type, from_state, "
                "to_state, actor_type, actor_id, occurred_at_ms, metadata_json) "
                "VALUES (?, ?, 'enqueued', NULL, 'queued', 'caller', ?, ?, '{}')",
                (str(uuid.uuid4()), job_id, source_principal, now_ms),
            )
            self._commit_transaction(connection)
            return EnqueueResult(
                job_id=job_id,
                state="queued",
                queue_seq=queue_seq,
                created_at_ms=now_ms,
                replay=False,
            )
        except IdempotencyConflict:
            if connection.in_transaction:
                connection.rollback()
            raise
        except (MigrationError, sqlite3.Error) as exc:
            if connection.in_transaction:
                connection.rollback()
            raise EnqueuePersistenceError(
                "enqueue transaction failed; no partial job was committed"
            ) from exc
        finally:
            connection.close()

    def _commit_transaction(self, connection: sqlite3.Connection) -> None:
        """Commit seam kept overridable for subprocess crash-boundary tests."""

        connection.commit()
