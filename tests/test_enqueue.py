import hashlib
import multiprocessing
import os
import shutil
import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID

import pytest
import rfc8785

from rendiv_api.migrations import apply_migrations, database_is_ready
from rendiv_api.persistence import (
    DatabaseNotReady,
    EnqueuePersistenceError,
    EnqueueRepository,
    IdempotencyConflict,
    InvalidEnqueue,
)


def _repository(database: Path, **kwargs) -> EnqueueRepository:
    return EnqueueRepository(database, **kwargs)


def _crash_child(database: str, phase: str) -> None:
    class CrashingRepository(EnqueueRepository):
        def _commit_transaction(self, connection: sqlite3.Connection) -> None:
            if phase == "before":
                os._exit(71)
            connection.commit()
            if phase == "after":
                os._exit(72)

    CrashingRepository(Path(database)).enqueue(
        source_principal="crash-test",
        operation="memory_add",
        idempotency_key="crash-boundary",
        payload={"value": "temporary"},
    )
    os._exit(99)


def test_enqueue_persists_canonical_payload_uuid7_state_and_audit(tmp_path: Path):
    assert rfc8785.dumps(
        {"numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 1e-27]}
    ) == b'{"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27]}'

    database = tmp_path / "rendiv.sqlite3"
    apply_migrations(database)
    repository = _repository(database)

    result = repository.enqueue(
        source_principal="pithagoras-test",
        operation="memory_add",
        idempotency_key="event:01",
        payload={"z": 1, "a": "é"},
    )

    parsed_id = UUID(result.job_id)
    assert parsed_id.version == 7
    assert parsed_id.variant == "specified in RFC 4122"
    assert result.state == "queued"
    assert result.queue_seq == 1
    assert not result.replay

    connection = sqlite3.connect(database)
    try:
        job = connection.execute(
            "SELECT payload_json, payload_sha256, state, effect_certainty, "
            "payload_format FROM jobs WHERE job_id = ?",
            (result.job_id,),
        ).fetchone()
        canonical_payload = rfc8785.dumps({"a": "é", "z": 1})
        canonical_envelope = rfc8785.dumps(
            {
                "operation": "memory_add",
                "payload_format": "json-v1",
                "payload": {"a": "é", "z": 1},
            }
        )
        assert job == (
            canonical_payload.decode("utf-8"),
            hashlib.sha256(canonical_envelope).digest(),
            "queued",
            "none",
            "json-v1",
        )
        event = connection.execute(
            "SELECT event_type, from_state, to_state, actor_type, actor_id, metadata_json "
            "FROM job_events WHERE job_id = ?",
            (result.job_id,),
        ).fetchone()
        assert event == (
            "enqueued",
            None,
            "queued",
            "caller",
            "pithagoras-test",
            "{}",
        )
    finally:
        connection.close()


def test_enqueue_fifo_sequences_are_monotonic_and_atomic(tmp_path: Path):
    database = tmp_path / "rendiv.sqlite3"
    apply_migrations(database)
    repository = _repository(database)

    results = [
        repository.enqueue(
            source_principal="ha-test",
            operation="memory_add",
            idempotency_key=f"batch-{index}",
            payload={"index": index},
        )
        for index in range(5)
    ]

    assert [result.queue_seq for result in results] == [1, 2, 3, 4, 5]


def test_identical_idempotency_replay_has_no_second_audit_or_job(tmp_path: Path):
    database = tmp_path / "rendiv.sqlite3"
    apply_migrations(database)
    repository = _repository(database)
    kwargs = {
        "source_principal": "client-a",
        "operation": "memory_update",
        "idempotency_key": "stable-key-1",
        "payload": {"b": 2, "a": 1},
    }

    first = repository.enqueue(**kwargs)
    replay = repository.enqueue(**{**kwargs, "payload": {"a": 1, "b": 2}})

    assert first.job_id == replay.job_id
    assert first.queue_seq == replay.queue_seq
    assert replay.replay
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM job_events").fetchone()[0] == 1
    finally:
        connection.close()


def test_idempotency_conflict_does_not_modify_any_rows(tmp_path: Path):
    database = tmp_path / "rendiv.sqlite3"
    apply_migrations(database)
    repository = _repository(database)
    original = repository.enqueue(
        source_principal="client-a",
        operation="memory_add",
        idempotency_key="same-key",
        payload={"value": 1},
    )

    with pytest.raises(IdempotencyConflict):
        repository.enqueue(
            source_principal="client-a",
            operation="memory_add",
            idempotency_key="same-key",
            payload={"value": 2},
        )

    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT job_id, payload_json, queue_seq FROM jobs"
        ).fetchall() == [(original.job_id, '{"value":1}', 1)]
        assert connection.execute("SELECT count(*) FROM job_events").fetchone()[0] == 1
    finally:
        connection.close()


def test_idempotency_scope_includes_principal_and_operation(tmp_path: Path):
    database = tmp_path / "rendiv.sqlite3"
    apply_migrations(database)
    repository = _repository(database)

    first = repository.enqueue(
        source_principal="client-a",
        operation="memory_add",
        idempotency_key="same-key",
        payload={"value": 1},
    )
    second = repository.enqueue(
        source_principal="client-b",
        operation="memory_add",
        idempotency_key="same-key",
        payload={"value": 1},
    )
    third = repository.enqueue(
        source_principal="client-a",
        operation="memory_update",
        idempotency_key="same-key",
        payload={"value": 1},
    )

    assert len({first.job_id, second.job_id, third.job_id}) == 3
    assert [first.queue_seq, second.queue_seq, third.queue_seq] == [1, 2, 3]


def test_input_validation_and_payload_byte_limit(tmp_path: Path):
    database = tmp_path / "rendiv.sqlite3"
    apply_migrations(database)
    repository = _repository(database, max_payload_bytes=12)

    cases = [
        {"operation": "memory_delete", "payload": {"a": 1}},
        {"operation": "memory_add", "payload": [1, 2]},
        {"operation": "memory_add", "payload": {"value": float("nan")}},
        {"operation": "memory_add", "payload": {"text": "this is too long"}},
    ]
    for index, case in enumerate(cases):
        with pytest.raises(InvalidEnqueue):
            repository.enqueue(
                source_principal="client-a",
                operation=case["operation"],
                idempotency_key=f"key-{index}",
                payload=case["payload"],
            )
    with pytest.raises(InvalidEnqueue):
        repository.enqueue(
            source_principal="client-a",
            operation="memory_add",
            idempotency_key="bad key",
            payload={"a": 1},
        )


def test_database_constraints_and_append_only_audit(tmp_path: Path):
    database = tmp_path / "rendiv.sqlite3"
    apply_migrations(database)
    result = _repository(database).enqueue(
        source_principal="client-a",
        operation="memory_add",
        idempotency_key="key-1",
        payload={"value": 1},
    )
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        for statement, params in [
            (
                "UPDATE jobs SET operation='bad' WHERE job_id=?",
                (result.job_id,),
            ),
            (
                "UPDATE jobs SET state='bad' WHERE job_id=?",
                (result.job_id,),
            ),
            (
                "UPDATE jobs SET effect_certainty='bad' WHERE job_id=?",
                (result.job_id,),
            ),
            (
                "UPDATE jobs SET source_principal='bad principal' WHERE job_id=?",
                (result.job_id,),
            ),
            (
                "UPDATE jobs SET idempotency_key='bad key' WHERE job_id=?",
                (result.job_id,),
            ),
            (
                "DELETE FROM job_events WHERE job_id=?",
                (result.job_id,),
            ),
            (
                "DELETE FROM jobs WHERE job_id=?",
                (result.job_id,),
            ),
        ]:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(statement, params)
            connection.rollback()

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE job_events SET event_type='changed' WHERE job_id=?",
                (result.job_id,),
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO job_events (event_id, job_id, event_type, actor_type, "
                "occurred_at_ms) VALUES (?, ?, 'orphan', 'caller', 1)",
                ("00000000-0000-4000-8000-000000000000", "missing-job"),
            )
        connection.rollback()
    finally:
        connection.close()


def test_job_and_audit_insert_roll_back_together_on_failure(tmp_path: Path):
    database = tmp_path / "rendiv.sqlite3"
    apply_migrations(database)
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TRIGGER reject_enqueued BEFORE INSERT ON job_events "
        "BEGIN SELECT RAISE(ABORT, 'injected test failure'); END"
    )
    connection.commit()
    connection.close()

    with pytest.raises(EnqueuePersistenceError):
        _repository(database).enqueue(
            source_principal="client-a",
            operation="memory_add",
            idempotency_key="rollback-key",
            payload={"value": 1},
        )

    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM job_events").fetchone()[0] == 0
    finally:
        connection.close()


def test_concurrent_identical_enqueues_claim_one_job(tmp_path: Path):
    database = tmp_path / "rendiv.sqlite3"
    apply_migrations(database)

    def enqueue_one(_index: int):
        return _repository(database).enqueue(
            source_principal="client-a",
            operation="memory_add",
            idempotency_key="concurrent-key",
            payload={"same": "request"},
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(enqueue_one, range(8)))

    assert len({result.job_id for result in results}) == 1
    assert sorted(result.replay for result in results) == [False] + [True] * 7
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM job_events").fetchone()[0] == 1
    finally:
        connection.close()


@pytest.mark.parametrize(("phase", "expected_exit"), [("before", 71), ("after", 72)])
def test_process_crash_before_and_after_commit(tmp_path: Path, phase: str, expected_exit: int):
    database = tmp_path / "rendiv.sqlite3"
    apply_migrations(database)
    context = multiprocessing.get_context("fork")
    process = context.Process(target=_crash_child, args=(str(database), phase))
    process.start()
    process.join(timeout=10)
    if process.is_alive():
        process.kill()
        process.join()
        pytest.fail("crash-boundary child process did not exit")
    assert process.exitcode == expected_exit

    recovered = _repository(database).enqueue(
        source_principal="crash-test",
        operation="memory_add",
        idempotency_key="crash-boundary",
        payload={"value": "temporary"},
    )
    if phase == "before":
        assert not recovered.replay
        assert recovered.queue_seq == 1
    else:
        assert recovered.replay
        assert recovered.queue_seq == 1

    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM job_events").fetchone()[0] == 1
    finally:
        connection.close()


def test_migration_or_readiness_failure_blocks_enqueue_while_process_lives(
    tmp_path: Path,
):
    database = tmp_path / "rendiv.sqlite3"
    migration_directory = tmp_path / "migrations"
    shutil.copytree(Path(__file__).parents[1] / "src/rendiv_api/migrations", migration_directory)
    apply_migrations(database, migration_directory=migration_directory)
    migration = migration_directory / "0002_jobs_and_events.sql"
    migration.write_text(
        migration.read_text(encoding="utf-8") + "-- checksum changed after startup\n",
        encoding="utf-8",
    )
    repository = _repository(database, migration_directory=migration_directory)

    assert not database_is_ready(database, migration_directory=migration_directory)
    with pytest.raises(DatabaseNotReady):
        repository.enqueue(
            source_principal="client-a",
            operation="memory_add",
            idempotency_key="not-accepted",
            payload={"value": 1},
        )

    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
    finally:
        connection.close()


def test_missing_jobs_schema_object_blocks_enqueue(tmp_path: Path):
    database = tmp_path / "rendiv.sqlite3"
    apply_migrations(database)
    connection = sqlite3.connect(database)
    connection.execute("DROP INDEX jobs_state_fifo")
    connection.commit()
    connection.close()
    repository = _repository(database)

    assert not database_is_ready(database)
    with pytest.raises(DatabaseNotReady):
        repository.enqueue(
            source_principal="client-a",
            operation="memory_add",
            idempotency_key="missing-index",
            payload={"value": 1},
        )


def test_enqueue_makes_no_external_network_calls(tmp_path: Path, monkeypatch):
    database = tmp_path / "rendiv.sqlite3"
    apply_migrations(database)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("enqueue attempted an external network connection")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)

    result = _repository(database).enqueue(
        source_principal="offline-test",
        operation="memory_add",
        idempotency_key="offline-key",
        payload={"offline": True},
    )

    assert result.state == "queued"
