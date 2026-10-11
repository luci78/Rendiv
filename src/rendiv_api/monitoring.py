"""Internal read-only queue monitoring queries; no public HTTP route."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from rendiv_api.backup import JOB_STATES
from rendiv_api.migrations import MigrationError, verify_migration_state


class MonitoringError(RuntimeError):
    """Monitoring data is unavailable or the database schema is invalid."""


@dataclass(frozen=True)
class MonitoringSnapshot:
    captured_at_ms: int
    job_counts: dict[str, int]
    backlog_count: int
    oldest_queued_at_ms: int | None
    unknown_count: int
    last_activity_at_ms: int | None


def read_monitoring_snapshot(database_path: Path) -> MonitoringSnapshot:
    """Read aggregate queue health from SQLite without exposing job contents."""

    path = Path(database_path)
    if not path.is_file():
        raise MonitoringError("Rendiv database is unavailable")
    uri = f"file:{quote(path.resolve().as_posix(), safe='/')}?mode=ro"
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        if connection.execute("PRAGMA query_only").fetchone()[0] != 1:
            raise MonitoringError("SQLite query-only mode could not be enabled")
        verify_migration_state(connection)
        rows = connection.execute(
            "SELECT state, COUNT(*) AS jobs_count FROM jobs GROUP BY state"
        ).fetchall()
        counts = {state: 0 for state in JOB_STATES}
        for row in rows:
            state = str(row["state"])
            if state not in counts:
                raise MonitoringError("database contains an unsupported job state")
            counts[state] = int(row["jobs_count"])
        oldest = connection.execute(
            "SELECT MIN(created_at_ms) FROM jobs WHERE state = 'queued'"
        ).fetchone()[0]
        last_activity = connection.execute(
            "SELECT MAX(occurred_at_ms) FROM job_events"
        ).fetchone()[0]
    except MonitoringError:
        raise
    except (MigrationError, OSError, sqlite3.Error) as exc:
        raise MonitoringError("Rendiv database monitoring read failed") from exc
    finally:
        if connection is not None:
            connection.close()

    return MonitoringSnapshot(
        captured_at_ms=time.time_ns() // 1_000_000,
        job_counts=counts,
        backlog_count=counts["queued"],
        oldest_queued_at_ms=None if oldest is None else int(oldest),
        unknown_count=counts["unknown"],
        last_activity_at_ms=None if last_activity is None else int(last_activity),
    )
