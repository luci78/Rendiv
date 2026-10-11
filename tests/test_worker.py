from __future__ import annotations

import asyncio
import secrets
import socket
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from rendiv_api.app import create_app
from rendiv_api.backup import create_backup, restore_backup, verify_database
from rendiv_api.config import Settings
from rendiv_api.migrations import apply_migrations
from rendiv_api.persistence import EnqueueRepository
from rendiv_api.worker import (
    ExecutionResult,
    LocalWorker,
    WorkerBusy,
    WorkerDatabaseError,
    WorkerOutcome,
    WorkerRun,
)


def _seed(database: Path, count: int = 1) -> list[str]:
    apply_migrations(database)
    repository = EnqueueRepository(database)
    ids = []
    for index in range(count):
        ids.append(
            repository.enqueue(
                source_principal="worker-test",
                operation="memory_add",
                idempotency_key=f"worker-{index}",
                payload={"index": index},
            ).job_id
        )
    return ids


def _rows(database: Path) -> tuple[list[tuple], list[tuple]]:
    with sqlite3.connect(database) as connection:
        return (
            connection.execute(
                "SELECT job_id, state, effect_certainty, queue_seq, finished_at_ms "
                "FROM jobs ORDER BY queue_seq"
            ).fetchall(),
            connection.execute(
                "SELECT event_type, from_state, to_state, actor_type "
                "FROM job_events ORDER BY event_seq"
            ).fetchall(),
        )


class FakeExecutor:
    def __init__(self, outcomes: list[WorkerOutcome] | None = None):
        self.outcomes = list(outcomes or [])
        self.calls: list[tuple[str, dict]] = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()
        self.on_call = None

    def __call__(self, operation: str, payload: dict) -> ExecutionResult:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls.append((operation, payload))
        try:
            if self.on_call is not None:
                self.on_call()
            outcome = self.outcomes.pop(0) if self.outcomes else WorkerOutcome.SUCCEEDED
            return ExecutionResult(outcome)
        finally:
            with self.lock:
                self.active -= 1


class SimulatedProcessCrash(BaseException):
    """Test-only abrupt termination that leaves a durable running claim."""


def test_fifo_serial_execution_and_unproven_failure_blocks_queue(tmp_path: Path):
    database = tmp_path / "worker.sqlite3"
    job_ids = _seed(database, 3)
    executor = FakeExecutor(
        [
            WorkerOutcome.SUCCEEDED,
            WorkerOutcome.FAILED_NO_EFFECT,
            WorkerOutcome.SUCCEEDED,
        ]
    )

    result = LocalWorker(database, executor=executor).run_until_idle()

    assert result == WorkerRun(processed=2, stop_reason="unknown_blocks_queue")
    assert executor.calls == [
        ("memory_add", {"index": 0}),
        ("memory_add", {"index": 1}),
    ]
    assert executor.max_active == 1
    jobs, events = _rows(database)
    assert [row[0] for row in jobs] == job_ids
    assert [(row[1], row[2]) for row in jobs] == [
        ("succeeded", "complete"),
        ("unknown", "unknown"),
        ("queued", "none"),
    ]
    assert [row[0] for row in events] == [
        "enqueued", "enqueued", "enqueued",
        "worker_claimed", "worker_succeeded",
        "worker_claimed", "worker_uncertain",
    ]
    assert all(event[3] in {"caller", "system"} for event in events)


def test_timeout_and_uncertain_result_mark_unknown_and_block_queue(tmp_path: Path):
    database = tmp_path / "worker.sqlite3"
    _seed(database, 2)
    executor = FakeExecutor([WorkerOutcome.TIMEOUT, WorkerOutcome.SUCCEEDED])

    result = LocalWorker(database, executor=executor).run_until_idle()

    assert result == WorkerRun(processed=1, stop_reason="unknown_blocks_queue")
    jobs, events = _rows(database)
    assert [row[1:3] for row in jobs] == [("unknown", "unknown"), ("queued", "none")]
    assert events[-1][0] == "worker_uncertain"
    assert LocalWorker(database, executor=executor).run_until_idle() == WorkerRun(
        processed=0, stop_reason="unknown_blocks_queue"
    )
    assert len(executor.calls) == 1


def test_two_concurrent_workers_cannot_execute_at_the_same_time(tmp_path: Path):
    database = tmp_path / "worker.sqlite3"
    _seed(database, 2)
    entered = threading.Event()
    release = threading.Event()
    executor = FakeExecutor()
    executor.on_call = lambda: (entered.set(), release.wait(timeout=5))
    first = LocalWorker(database, executor=executor)
    second = LocalWorker(database, executor=executor)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(first.run_until_idle, max_jobs=1)
        assert entered.wait(timeout=5)
        with pytest.raises(WorkerBusy):
            second.run_until_idle(max_jobs=1)
        release.set()
        assert first_future.result(timeout=5) == WorkerRun(1, "job_limit")

    assert executor.max_active == 1
    jobs, _ = _rows(database)
    assert [row[1] for row in jobs] == ["succeeded", "queued"]


def test_crash_before_claim_leaves_queued_job_and_next_worker_can_process(tmp_path: Path):
    database = tmp_path / "worker.sqlite3"
    _seed(database)
    worker = LocalWorker(database, executor=FakeExecutor())

    def crash_before_claim():
        raise SimulatedProcessCrash()

    worker._claim_next = crash_before_claim  # type: ignore[method-assign]
    with pytest.raises(SimulatedProcessCrash):
        worker.run_until_idle()
    assert _rows(database)[0][0][1:3] == ("queued", "none")

    executor = FakeExecutor()
    assert LocalWorker(database, executor=executor).run_until_idle().processed == 1
    assert len(executor.calls) == 1


def test_crash_during_execution_recovers_running_as_unknown_without_retry(tmp_path: Path):
    database = tmp_path / "worker.sqlite3"
    _seed(database)

    def crash_executor(_operation: str, _payload: dict) -> ExecutionResult:
        raise SimulatedProcessCrash()

    with pytest.raises(SimulatedProcessCrash):
        LocalWorker(database, executor=crash_executor).run_until_idle()
    assert _rows(database)[0][0][1:3] == ("running", "unknown")

    retry_executor = FakeExecutor()
    result = LocalWorker(database, executor=retry_executor).run_until_idle()
    assert result == WorkerRun(0, "unknown_blocks_queue")
    assert _rows(database)[0][0][1:3] == ("unknown", "unknown")
    assert _rows(database)[1][-1] == (
        "recovered_running_as_unknown", "running", "unknown", "recovery"
    )
    assert retry_executor.calls == []


def test_failed_claim_audit_rolls_back_job_transition(tmp_path: Path):
    database = tmp_path / "worker.sqlite3"
    _seed(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TRIGGER reject_worker_claim BEFORE INSERT ON job_events "
            "WHEN NEW.event_type='worker_claimed' BEGIN SELECT RAISE(ABORT, 'test'); END"
        )

    with pytest.raises(WorkerDatabaseError):
        LocalWorker(database, executor=FakeExecutor()).run_until_idle()

    jobs, events = _rows(database)
    assert jobs[0][1:3] == ("queued", "none")
    assert [event[0] for event in events] == ["enqueued"]


def test_failed_result_audit_rolls_back_and_restart_marks_unknown(tmp_path: Path):
    database = tmp_path / "worker.sqlite3"
    _seed(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TRIGGER reject_worker_success BEFORE INSERT ON job_events "
            "WHEN NEW.event_type='worker_succeeded' BEGIN SELECT RAISE(ABORT, 'test'); END"
        )

    with pytest.raises(WorkerDatabaseError):
        LocalWorker(database, executor=FakeExecutor()).run_until_idle()
    jobs, events = _rows(database)
    assert jobs[0][1:3] == ("running", "unknown")
    assert [event[0] for event in events] == ["enqueued", "worker_claimed"]

    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER reject_worker_success")
    assert LocalWorker(database, executor=FakeExecutor()).run_until_idle().stop_reason == (
        "unknown_blocks_queue"
    )
    assert _rows(database)[0][0][1:3] == ("unknown", "unknown")


def test_executor_timeout_exception_and_invalid_result_are_uncertain(tmp_path: Path):
    database = tmp_path / "worker.sqlite3"
    _seed(database, 3)
    calls = 0

    def executor(_operation: str, _payload: dict) -> ExecutionResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("simulated timeout")
        return "not-an-outcome"  # type: ignore[return-value]

    first = LocalWorker(database, executor=executor).run_until_idle()
    assert first.stop_reason == "unknown_blocks_queue"
    assert _rows(database)[0][0][1:3] == ("unknown", "unknown")
    assert calls == 1


def test_executor_unknown_result_and_unexpected_exception_do_not_retry(tmp_path: Path):
    for suffix, executor in (
        ("result", FakeExecutor([WorkerOutcome.UNKNOWN])),
        ("exception", lambda _operation, _payload: (_ for _ in ()).throw(RuntimeError())),
    ):
        database = tmp_path / f"{suffix}.sqlite3"
        _seed(database)
        result = LocalWorker(database, executor=executor).run_until_idle()
        assert result == WorkerRun(1, "unknown_blocks_queue")
        assert _rows(database)[0][0][1:3] == ("unknown", "unknown")


def test_unavailable_or_corrupt_database_fails_closed(tmp_path: Path):
    executor = FakeExecutor()
    with pytest.raises(WorkerDatabaseError):
        LocalWorker(tmp_path / "missing" / "db.sqlite3", executor=executor).run_until_idle()

    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"corrupt sqlite")
    with pytest.raises(WorkerDatabaseError):
        LocalWorker(corrupt, executor=executor).run_until_idle()
    assert executor.calls == []


def test_worker_has_no_network_access(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database = tmp_path / "worker.sqlite3"
    _seed(database)
    executor = FakeExecutor()

    def reject_connect(*_args, **_kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", reject_connect)
    monkeypatch.setattr(socket, "create_connection", reject_connect)
    assert LocalWorker(database, executor=executor).run_until_idle().processed == 1


def test_api_status_and_backup_restore_remain_compatible(tmp_path: Path):
    database = tmp_path / "worker.sqlite3"
    job_id = _seed(database)[0]
    assert LocalWorker(database, executor=FakeExecutor()).run_until_idle().processed == 1
    backup = tmp_path / "backup.sqlite3"
    restored = tmp_path / "restored.sqlite3"
    create_backup(database, backup)
    restore_backup(backup, restored)
    assert verify_database(restored).job_counts["succeeded"] == 1

    token = secrets.token_urlsafe(32)
    app = create_app(
        Settings(
            app_env="test",
            database_path=restored,
            service_tokens={"worker-test": SecretStr(token)},
        )
    )

    async def fetch_status():
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://rendiv.test"
            ) as client:
                response = await client.get(
                    f"/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"}
                )
                assert response.status_code == 200
                assert response.json()["state"] == "succeeded"
                assert "payload" not in response.json()

    asyncio.run(fetch_status())
