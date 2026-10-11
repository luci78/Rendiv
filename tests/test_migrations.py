import sqlite3
from pathlib import Path

import pytest

from rendiv_api.migrations import (
    MigrationError,
    apply_migrations,
    configure_write_connection,
    database_is_ready,
)


def test_initial_migration_is_idempotent_and_wal_backed(tmp_path: Path):
    database = tmp_path / "rendiv.sqlite3"

    assert apply_migrations(database) == 2
    assert apply_migrations(database) == 2
    assert database_is_ready(database)

    connection = sqlite3.connect(database)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute(
            "SELECT version, name, length(checksum) FROM schema_migrations ORDER BY version"
        ).fetchall() == [(1, "bootstrap", 64), (2, "jobs_and_events", 64)]
        assert connection.execute(
            "SELECT count(*) FROM jobs"
        ).fetchone() == (0,)
    finally:
        connection.close()


def test_checksum_mismatch_fails_closed_without_partial_migration(tmp_path: Path):
    database = tmp_path / "rendiv.sqlite3"
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    migration = migration_dir / "0001_bootstrap.sql"
    migration.write_text(
        "CREATE TABLE schema_migrations ("
        "version INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, "
        "checksum TEXT NOT NULL, applied_at_utc TEXT NOT NULL);\n",
        encoding="utf-8",
    )
    assert apply_migrations(database, migration_directory=migration_dir) == 1

    migration.write_text(migration.read_text(encoding="utf-8") + "-- changed\n", encoding="utf-8")
    with pytest.raises(MigrationError, match="checksum or name mismatch"):
        apply_migrations(database, migration_directory=migration_dir)

    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 1
    finally:
        connection.close()


def test_unmanaged_database_is_not_modified(tmp_path: Path):
    database = tmp_path / "existing.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE unrelated (value TEXT)")
    connection.commit()
    connection.close()

    with pytest.raises(MigrationError, match="unmanaged tables"):
        apply_migrations(database)

    connection = sqlite3.connect(database)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables == {"unrelated"}
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        connection.close()


def test_missing_database_parent_is_not_created(tmp_path: Path):
    database = tmp_path / "missing" / "rendiv.sqlite3"

    with pytest.raises(MigrationError, match="parent directory does not exist"):
        apply_migrations(database)

    assert not database.parent.exists()


def test_write_connection_pragmas_are_applied_and_verified(tmp_path: Path):
    database = tmp_path / "pragma-test.sqlite3"
    connection = sqlite3.connect(database, isolation_level=None)
    try:
        configure_write_connection(connection, busy_timeout_ms=1_234)
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 1_234
    finally:
        connection.close()


def test_failed_new_migration_rolls_back_ddl_and_ledger(tmp_path: Path):
    database = tmp_path / "rendiv.sqlite3"
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    (migration_dir / "0001_bootstrap.sql").write_text(
        "CREATE TABLE schema_migrations ("
        "version INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, "
        "checksum TEXT NOT NULL, applied_at_utc TEXT NOT NULL);\n",
        encoding="utf-8",
    )
    assert apply_migrations(database, migration_directory=migration_dir) == 1
    (migration_dir / "0002_broken.sql").write_text(
        "CREATE TABLE should_rollback (value TEXT);\nINVALID SQL;\n",
        encoding="utf-8",
    )

    with pytest.raises(MigrationError, match="migration failed"):
        apply_migrations(database, migration_directory=migration_dir)

    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall() == [(1,)]
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='should_rollback'"
        ).fetchone() is None
    finally:
        connection.close()
