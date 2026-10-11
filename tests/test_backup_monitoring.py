import hashlib
import socket
import sqlite3
import uuid
from pathlib import Path

import pytest

import rendiv_api.backup as backup_module
from rendiv_api.backup import (
    BackupError,
    create_backup,
    restore_backup,
    verify_database,
)
from rendiv_api.migrations import apply_migrations
from rendiv_api.monitoring import MonitoringError, read_monitoring_snapshot
from rendiv_api.persistence import EnqueueRepository


def _seed_database(path: Path) -> tuple[Path, EnqueueRepository]:
    apply_migrations(path)
    repository = EnqueueRepository(path)
    repository.enqueue(
        source_principal="test-source",
        operation="memory_add",
        idempotency_key="backup-test-1",
        payload={"value": "temporary"},
    )
    return path, repository


def _counts(path: Path) -> tuple[int, int, list[tuple[str, int]]]:
    connection = sqlite3.connect(path)
    try:
        return (
            int(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]),
            int(connection.execute("SELECT COUNT(*) FROM job_events").fetchone()[0]),
            connection.execute(
                "SELECT state, COUNT(*) FROM jobs GROUP BY state ORDER BY state"
            ).fetchall(),
        )
    finally:
        connection.close()


def _database_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _logical_snapshot(path: Path) -> tuple[list[tuple], list[tuple], list[tuple]]:
    connection = sqlite3.connect(path)
    try:
        return (
            connection.execute("SELECT * FROM schema_migrations ORDER BY version").fetchall(),
            connection.execute("SELECT * FROM jobs ORDER BY queue_seq").fetchall(),
            connection.execute("SELECT * FROM job_events ORDER BY event_seq").fetchall(),
        )
    finally:
        connection.close()


def test_online_backup_is_consistent_during_uncommitted_wal_transaction_and_restores(
    tmp_path: Path,
):
    source, _ = _seed_database(tmp_path / "source.sqlite3")
    mode_connection = sqlite3.connect(source)
    try:
        assert mode_connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        mode_connection.close()

    writer = sqlite3.connect(source, isolation_level=None)
    writer.execute("PRAGMA foreign_keys = ON")
    writer.execute("BEGIN IMMEDIATE")
    job_id = writer.execute("SELECT job_id FROM jobs LIMIT 1").fetchone()[0]
    now_ms = 1_800_000_000_000
    writer.execute(
        "UPDATE jobs SET state='running', effect_certainty='unknown', "
        "updated_at_ms=? WHERE job_id=?",
        (now_ms, job_id),
    )
    writer.execute(
        "INSERT INTO job_events(event_id, job_id, event_type, from_state, to_state, "
        "actor_type, occurred_at_ms, metadata_json) "
        "VALUES (?, ?, 'test_claim', 'queued', 'running', 'system', ?, '{}')",
        (str(uuid.uuid4()), job_id, now_ms),
    )

    backup_path = tmp_path / "backup.sqlite3"
    try:
        result = create_backup(source, backup_path)
    finally:
        writer.commit()
        writer.close()

    assert result.schema_version == 2
    assert result.job_counts["queued"] == 1
    assert result.job_counts["running"] == 0
    assert verify_database(backup_path).job_counts["queued"] == 1
    assert verify_database(source).job_counts["running"] == 1
    assert _counts(backup_path) == (1, 1, [("queued", 1)])

    restored_path = tmp_path / "restored-new.sqlite3"
    restored = restore_backup(backup_path, restored_path)
    assert restored_path.is_file()
    assert restored.sha256 == _database_digest(restored_path)
    assert verify_database(restored_path) == verify_database(backup_path)
    assert _counts(restored_path) == _counts(backup_path)


def test_backup_is_atomically_published_and_never_overwrites_existing_file(
    tmp_path: Path,
):
    source, _ = _seed_database(tmp_path / "source.sqlite3")
    destination = tmp_path / "backup.sqlite3"
    create_backup(source, destination)
    original_digest = _database_digest(destination)

    with pytest.raises(BackupError, match="already exists"):
        create_backup(source, destination)

    assert _database_digest(destination) == original_digest
    assert not list(tmp_path.glob(".backup.sqlite3.*.tmp"))


def test_corrupt_backup_is_rejected_before_restore_and_destination_stays_absent(
    tmp_path: Path,
):
    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"not a SQLite database")
    destination = tmp_path / "must-not-exist.sqlite3"

    with pytest.raises(BackupError):
        verify_database(corrupt)
    with pytest.raises(BackupError):
        restore_backup(corrupt, destination)
    assert not destination.exists()


def test_invalid_migration_checksum_blocks_backup_without_publication(tmp_path: Path):
    source, _ = _seed_database(tmp_path / "source.sqlite3")
    connection = sqlite3.connect(source)
    try:
        connection.execute(
            "UPDATE schema_migrations SET checksum=? WHERE version=2", ("0" * 64,)
        )
        connection.commit()
    finally:
        connection.close()
    destination = tmp_path / "backup.sqlite3"

    with pytest.raises(BackupError, match="migration schema/checksum"):
        create_backup(source, destination)
    assert not destination.exists()


def test_backup_and_restore_fail_closed_for_missing_database_and_unwritable_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source, _ = _seed_database(tmp_path / "source.sqlite3")
    with pytest.raises(BackupError, match="does not exist"):
        create_backup(tmp_path / "missing.sqlite3", tmp_path / "missing-backup.sqlite3")

    backup_path = tmp_path / "existing-backup.sqlite3"
    create_backup(source, backup_path)

    def deny_temp_file(*_args, **_kwargs):
        raise PermissionError("test denies write access")

    monkeypatch.setattr(backup_module.tempfile, "mkstemp", deny_temp_file)
    with pytest.raises(BackupError, match="temporary SQLite file"):
        create_backup(source, tmp_path / "unwritable-backup.sqlite3")
    with pytest.raises(BackupError, match="temporary SQLite file"):
        restore_backup(backup_path, tmp_path / "unwritable-restore.sqlite3")
    assert not (tmp_path / "unwritable-backup.sqlite3").exists()
    assert not (tmp_path / "unwritable-restore.sqlite3").exists()


def test_restore_requires_absolute_explicit_new_path_and_never_replaces(tmp_path: Path):
    source, _ = _seed_database(tmp_path / "source.sqlite3")
    backup_path = tmp_path / "backup.sqlite3"
    create_backup(source, backup_path)
    existing = tmp_path / "existing.sqlite3"
    existing.write_bytes(b"preserve")

    with pytest.raises(BackupError, match="absolute"):
        restore_backup(backup_path, Path("relative.sqlite3"))
    with pytest.raises(BackupError, match="already exists"):
        restore_backup(backup_path, existing)
    assert existing.read_bytes() == b"preserve"


def test_monitoring_reports_only_aggregates_and_does_not_mutate_database(tmp_path: Path):
    database, repository = _seed_database(tmp_path / "monitor.sqlite3")
    repository.enqueue(
        source_principal="test-source",
        operation="memory_update",
        idempotency_key="monitor-test-2",
        payload={"value": "private test content"},
    )
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "UPDATE jobs SET state='unknown', effect_certainty='unknown' "
            "WHERE operation='memory_add'"
        )
        connection.execute(
            "INSERT INTO job_events(event_id, job_id, event_type, from_state, to_state, "
            "actor_type, occurred_at_ms, metadata_json) "
            "SELECT ?, job_id, 'test_unknown', 'queued', 'unknown', 'system', "
            "created_at_ms + 1, '{}' FROM jobs WHERE operation='memory_add'",
            (str(uuid.uuid4()),),
        )
        connection.commit()
    finally:
        connection.close()

    before = _logical_snapshot(database)
    snapshot = read_monitoring_snapshot(database)
    after = _logical_snapshot(database)

    assert before == after
    assert snapshot.job_counts == {
        "queued": 1,
        "running": 0,
        "succeeded": 0,
        "failed": 0,
        "unknown": 1,
    }
    assert snapshot.backlog_count == 1
    assert snapshot.oldest_queued_at_ms is not None
    assert snapshot.unknown_count == 1
    assert snapshot.last_activity_at_ms is not None
    assert "private test content" not in repr(snapshot)
    assert not hasattr(snapshot, "job_id")


def test_monitoring_is_read_only_and_rejects_database_unavailable(tmp_path: Path):
    database, _ = _seed_database(tmp_path / "monitor.sqlite3")
    with pytest.raises(MonitoringError, match="unavailable"):
        read_monitoring_snapshot(tmp_path / "not-present.sqlite3")
    assert read_monitoring_snapshot(database).backlog_count == 1


def test_backup_restore_and_monitoring_make_no_external_socket_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source, _ = _seed_database(tmp_path / "source.sqlite3")

    def forbidden_connect(*_args, **_kwargs):
        raise AssertionError("unexpected external socket call")

    monkeypatch.setattr(socket.socket, "connect", forbidden_connect)
    backup_path = tmp_path / "backup.sqlite3"
    restored_path = tmp_path / "restored.sqlite3"
    create_backup(source, backup_path)
    verify_database(backup_path)
    restore_backup(backup_path, restored_path)
    read_monitoring_snapshot(restored_path)


def test_backup_module_commands_create_verify_and_restore(tmp_path: Path, capsys):
    source, _ = _seed_database(tmp_path / "source.sqlite3")
    backup_path = tmp_path / "cli-backup.sqlite3"
    restored_path = tmp_path / "cli-restored.sqlite3"

    assert backup_module.main(["create", str(source), str(backup_path)]) == 0
    assert "backup successful" in capsys.readouterr().out
    assert backup_module.main(["verify", str(backup_path)]) == 0
    assert "verification successful" in capsys.readouterr().out
    assert backup_module.main(
        ["restore", str(backup_path), str(restored_path)]
    ) == 0
    output = capsys.readouterr().out
    assert "restore successful" in output
    assert "operator_attention running=0 unknown=0" in output
