"""Explicit local queue worker with an injected executor and no network client."""

from __future__ import annotations

import fcntl
import json
import os
import secrets
import sqlite3
import stat
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from rendiv_api.migrations import (
    MigrationError,
    configure_write_connection,
    database_is_ready,
    verify_migration_state,
)


class WorkerError(RuntimeError):
    """The worker stopped without claiming or retrying an unsafe job."""


class WorkerBusy(WorkerError):
    """Another worker holds the local exclusive execution lock."""


class WorkerDatabaseError(WorkerError):
    """The database is unavailable, corrupt, or cannot persist an audit event."""


class WorkerOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED_NO_EFFECT = "failed_no_effect"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class ExecutionResult:
    outcome: WorkerOutcome


class Executor(Protocol):
    """Injected operation executor. This module provides no external executor."""

    def __call__(self, operation: str, payload: dict[str, Any]) -> ExecutionResult: ...


@dataclass(frozen=True)
class WorkerRun:
    processed: int
    stop_reason: str


@dataclass(frozen=True)
class _Job:
    job_id: str
    operation: str
    payload: dict[str, Any]


_ALLOWED_TRANSITIONS = {
    "queued": frozenset({"running"}),
    "running": frozenset({"succeeded", "failed", "unknown"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "unknown": frozenset(),
}


class LocalWorker:
    """Process queued jobs serially, only with a caller-injected executor.

    The worker is never started by the API or container entrypoint. All worker
    processes for one database must share its local POSIX filesystem and this
    implementation's advisory lock file. If that lock cannot be acquired or
    verified, processing fails closed.
    """

    def __init__(
        self,
        database_path: Path,
        *,
        executor: Executor,
        busy_timeout_ms: int = 5_000,
        migration_directory: Path | None = None,
    ) -> None:
        if not callable(executor):
            raise TypeError("an executor must be explicitly injected")
        if not 0 <= busy_timeout_ms <= 60_000:
            raise ValueError("busy_timeout_ms must be between 0 and 60000")
        self._database_path = Path(database_path)
        self._executor = executor
        self._busy_timeout_ms = busy_timeout_ms
        self._migration_directory = migration_directory
        self._worker_id = secrets.token_hex(16)

    def run_until_idle(self, *, max_jobs: int | None = None) -> WorkerRun:
        """Recover stale running rows, then process FIFO jobs until blocked/idle."""

        if max_jobs is not None and max_jobs < 1:
            raise ValueError("max_jobs must be positive")
        if not database_is_ready(
            self._database_path,
            migration_directory=self._migration_directory,
        ):
            raise WorkerDatabaseError("SQLite is not ready for worker processing")

        lock_descriptor = self._acquire_lock()
        try:
            if self._recover_running_jobs():
                return WorkerRun(processed=0, stop_reason="unknown_blocks_queue")
            processed = 0
            while max_jobs is None or processed < max_jobs:
                job = self._claim_next()
                if job is None:
                    return WorkerRun(processed=processed, stop_reason="idle")
                result = self._execute(job)
                if result.outcome is WorkerOutcome.SUCCEEDED:
                    self._finish(job.job_id, "succeeded", "complete", "worker_succeeded")
                    processed += 1
                    continue
                if result.outcome is WorkerOutcome.FAILED_NO_EFFECT:
                    self._finish(job.job_id, "failed", "none", "worker_failed_no_effect")
                    processed += 1
                    continue
                self._finish(job.job_id, "unknown", "unknown", "worker_uncertain")
                processed += 1
                return WorkerRun(processed=processed, stop_reason="unknown_blocks_queue")
            return WorkerRun(processed=processed, stop_reason="job_limit")
        finally:
            os.close(lock_descriptor)

    def _acquire_lock(self) -> int:
        if not hasattr(os, "O_NOFOLLOW"):
            raise WorkerError("platform cannot safely verify the worker lock file")
        try:
            database_path = self._database_path.resolve(strict=True)
            lock_path = database_path.with_name(database_path.name + ".worker.lock")
            flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
            descriptor = os.open(lock_path, flags, 0o600)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or metadata.st_mode & 0o077
                or metadata.st_nlink != 1
            ):
                os.close(descriptor)
                raise WorkerError("worker lock file is not private and owned by this user")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                os.close(descriptor)
                raise WorkerBusy("another Rendiv worker is active") from exc
            return descriptor
        except WorkerError:
            raise
        except OSError as exc:
            raise WorkerError("unable to establish exclusive worker lock") from exc

    def _connect_writer(self) -> sqlite3.Connection:
        if not database_is_ready(
            self._database_path,
            migration_directory=self._migration_directory,
        ):
            raise WorkerDatabaseError("SQLite readiness or migration checks failed")
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                self._database_path,
                timeout=self._busy_timeout_ms / 1_000,
                isolation_level=None,
            )
            configure_write_connection(
                connection,
                busy_timeout_ms=self._busy_timeout_ms,
                enable_wal=True,
            )
            verify_migration_state(
                connection,
                migration_directory=self._migration_directory,
            )
            return connection
        except (MigrationError, OSError, sqlite3.Error) as exc:
            if connection is not None:
                try:
                    connection.close()
                except sqlite3.Error:
                    pass
            raise WorkerDatabaseError("SQLite writer could not be verified") from exc

    def _recover_running_jobs(self) -> bool:
        connection = self._connect_writer()
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT job_id, updated_at_ms FROM jobs WHERE state = 'running' "
                "ORDER BY queue_seq"
            ).fetchall()
            for job_id, updated_at_ms in rows:
                self._transition(
                    connection,
                    job_id=str(job_id),
                    from_state="running",
                    to_state="unknown",
                    effect_certainty="unknown",
                    event_type="recovered_running_as_unknown",
                    actor_type="recovery",
                    reason_code="worker_restart",
                    finished=True,
                    prior_updated_at_ms=int(updated_at_ms),
                )
            unknown_present = self._has_unknown(connection)
            connection.commit()
            return unknown_present
        except (MigrationError, sqlite3.Error, WorkerError) as exc:
            if connection.in_transaction:
                connection.rollback()
            raise WorkerDatabaseError("worker recovery transaction failed") from exc
        finally:
            connection.close()

    def _claim_next(self) -> _Job | None:
        connection = self._connect_writer()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if self._has_unknown(connection):
                connection.commit()
                return None
            if connection.execute(
                "SELECT 1 FROM jobs WHERE state='running' LIMIT 1"
            ).fetchone():
                raise WorkerError("running job exists outside the worker lock")
            row = connection.execute(
                "SELECT job_id, operation, payload_json, updated_at_ms FROM jobs "
                "WHERE state='queued' ORDER BY queue_seq LIMIT 1"
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            job_id, operation, payload_json, updated_at_ms = row
            payload = json.loads(str(payload_json))
            if not isinstance(payload, dict):
                raise WorkerDatabaseError("stored job payload is not a JSON object")
            self._transition(
                connection,
                job_id=str(job_id),
                from_state="queued",
                to_state="running",
                effect_certainty="unknown",
                event_type="worker_claimed",
                actor_type="system",
                reason_code="fifo_claim",
                finished=False,
                prior_updated_at_ms=int(updated_at_ms),
            )
            connection.commit()
            return _Job(str(job_id), str(operation), payload)
        except (MigrationError, sqlite3.Error, WorkerError, ValueError, TypeError) as exc:
            if connection.in_transaction:
                connection.rollback()
            if isinstance(exc, WorkerError):
                raise
            raise WorkerDatabaseError("worker claim transaction failed") from exc
        finally:
            connection.close()

    def _execute(self, job: _Job) -> ExecutionResult:
        try:
            result = self._executor(job.operation, job.payload)
        except TimeoutError:
            return ExecutionResult(WorkerOutcome.TIMEOUT)
        except Exception:
            # Exceptions from an executor do not prove that it had no effect.
            return ExecutionResult(WorkerOutcome.UNKNOWN)
        except BaseException:
            # A real process crash leaves the durable running claim behind. Do
            # not translate process-control exceptions into a retryable result.
            raise
        if not isinstance(result, ExecutionResult) or not isinstance(result.outcome, WorkerOutcome):
            return ExecutionResult(WorkerOutcome.UNKNOWN)
        return result

    def _finish(
        self,
        job_id: str,
        to_state: str,
        effect_certainty: str,
        event_type: str,
    ) -> None:
        connection = self._connect_writer()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT updated_at_ms FROM jobs WHERE job_id=? AND state='running'",
                (job_id,),
            ).fetchone()
            if row is None:
                raise WorkerError("claimed job is no longer running")
            self._transition(
                connection,
                job_id=job_id,
                from_state="running",
                to_state=to_state,
                effect_certainty=effect_certainty,
                event_type=event_type,
                actor_type="system",
                reason_code=event_type,
                finished=True,
                prior_updated_at_ms=int(row[0]),
            )
            connection.commit()
        except (MigrationError, sqlite3.Error, WorkerError) as exc:
            if connection.in_transaction:
                connection.rollback()
            if isinstance(exc, WorkerError):
                raise
            raise WorkerDatabaseError("worker result transaction failed") from exc
        finally:
            connection.close()

    def _transition(
        self,
        connection: sqlite3.Connection,
        *,
        job_id: str,
        from_state: str,
        to_state: str,
        effect_certainty: str,
        event_type: str,
        actor_type: str,
        reason_code: str,
        finished: bool,
        prior_updated_at_ms: int,
    ) -> None:
        if to_state not in _ALLOWED_TRANSITIONS.get(from_state, frozenset()):
            raise WorkerError("invalid job state transition")
        expected_certainty = {
            ("queued", "running"): "unknown",
            ("running", "succeeded"): "complete",
            ("running", "failed"): "none",
            ("running", "unknown"): "unknown",
        }
        if expected_certainty.get((from_state, to_state)) != effect_certainty:
            raise WorkerError("job state transition has invalid effect certainty")
        now_ms = max(time.time_ns() // 1_000_000, prior_updated_at_ms)
        cursor = connection.execute(
            "UPDATE jobs SET state=?, effect_certainty=?, updated_at_ms=?, "
            "finished_at_ms=? WHERE job_id=? AND state=?",
            (
                to_state,
                effect_certainty,
                now_ms,
                now_ms if finished else None,
                job_id,
                from_state,
            ),
        )
        if cursor.rowcount != 1:
            raise WorkerError("job state changed before transition")
        connection.execute(
            "INSERT INTO job_events(event_id, job_id, event_type, from_state, to_state, "
            "actor_type, actor_id, occurred_at_ms, reason_code, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')",
            (
                str(uuid.uuid4()),
                job_id,
                event_type,
                from_state,
                to_state,
                actor_type,
                self._worker_id,
                now_ms,
                reason_code,
            ),
        )

    @staticmethod
    def _has_unknown(connection: sqlite3.Connection) -> bool:
        return connection.execute(
            "SELECT 1 FROM jobs WHERE state='unknown' LIMIT 1"
        ).fetchone() is not None
