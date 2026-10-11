"""Checksum-verified, fail-closed SQLite migration runner."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


_MIGRATION_NAME = re.compile(r"^(?P<version>[0-9]{4})_(?P<name>[a-z0-9_]+)\.sql$")
_LEDGER = "schema_migrations"


class MigrationError(RuntimeError):
    """Raised when the database cannot be migrated safely."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum: str


def load_migrations(directory: Path | None = None) -> list[Migration]:
    """Load ordered SQL files and reject gaps or malformed filenames."""

    source = directory or Path(__file__).with_name("migrations")
    migrations: list[Migration] = []
    for path in sorted(source.glob("*.sql")):
        match = _MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            raise MigrationError(f"invalid migration filename: {path.name}")
        content = path.read_bytes()
        migrations.append(
            Migration(
                version=int(match.group("version")),
                name=match.group("name"),
                sql=content.decode("utf-8"),
                checksum=hashlib.sha256(content).hexdigest(),
            )
        )

    versions = [migration.version for migration in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise MigrationError("migration versions must be contiguous from 0001")
    if not migrations:
        raise MigrationError("no migrations are available")
    return migrations


def _iter_statements(script: str) -> Iterable[str]:
    """Split SQLite statements while preserving trigger bodies and comments."""

    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                yield statement
            buffer = ""
    if buffer.strip():
        raise MigrationError("migration ends with an incomplete SQL statement")


def _user_tables(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return [str(row[0]) for row in rows]


def _has_ledger(connection: sqlite3.Connection) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (_LEDGER,),
    ).fetchone() is not None


def _apply_sql(connection: sqlite3.Connection, migration: Migration) -> None:
    for statement in _iter_statements(migration.sql):
        connection.execute(statement)


def apply_migrations(
    database_path: Path,
    *,
    migration_directory: Path | None = None,
    busy_timeout_ms: int = 5_000,
) -> int:
    """Apply migrations transactionally; return the current schema version.

    The parent directory must already exist. This avoids silently creating an
    unapproved persistent production directory as a side effect of startup.
    """

    path = Path(database_path)
    if not path.parent.is_dir():
        raise MigrationError("database parent directory does not exist")

    migrations = load_migrations(migration_directory)
    try:
        connection = sqlite3.connect(
            path,
            timeout=busy_timeout_ms / 1_000,
            isolation_level=None,
        )
    except sqlite3.Error as exc:
        raise MigrationError("unable to open SQLite database") from exc

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")

        # Do not even change journal mode on an unmanaged or checksum-mismatched DB.
        has_ledger = _has_ledger(connection)
        if not has_ledger and _user_tables(connection):
            raise MigrationError("database has unmanaged tables; refusing migration")
        preflight: dict[int, tuple[str, str]] = {}
        if has_ledger:
            rows = connection.execute(
                "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
            ).fetchall()
            preflight = {
                int(version): (str(name), str(checksum))
                for version, name, checksum in rows
            }
        known = {migration.version: migration for migration in migrations}
        if any(version not in known for version in preflight):
            raise MigrationError("database schema is newer than this application")
        for version, record in preflight.items():
            migration = known[version]
            if record != (migration.name, migration.checksum):
                raise MigrationError(
                    f"checksum or name mismatch for migration {version:04d}"
                )

        mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            raise MigrationError("SQLite did not enable WAL mode")
        connection.execute("PRAGMA synchronous = FULL")

        connection.execute("BEGIN IMMEDIATE")
        has_ledger = _has_ledger(connection)
        if not has_ledger and _user_tables(connection):
            raise MigrationError("database has unmanaged tables; refusing migration")

        applied: dict[int, tuple[str, str]] = {}
        if has_ledger:
            rows = connection.execute(
                "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
            ).fetchall()
            applied = {
                int(version): (str(name), str(checksum))
                for version, name, checksum in rows
            }

        known = {migration.version: migration for migration in migrations}
        if any(version not in known for version in applied):
            raise MigrationError("database schema is newer than this application")

        for migration in migrations:
            existing = applied.get(migration.version)
            if existing is not None:
                expected = (migration.name, migration.checksum)
                if existing != expected:
                    raise MigrationError(
                        f"checksum or name mismatch for migration {migration.version:04d}"
                    )
                continue

            if migration.version != len(applied) + 1:
                raise MigrationError("database migration history contains a gap")
            _apply_sql(connection, migration)
            applied_at = datetime.now(timezone.utc).isoformat()
            connection.execute(
                "INSERT INTO schema_migrations(version, name, checksum, applied_at_utc) "
                "VALUES (?, ?, ?, ?)",
                (migration.version, migration.name, migration.checksum, applied_at),
            )
            applied[migration.version] = (migration.name, migration.checksum)

        connection.commit()
        return max(applied, default=0)
    except MigrationError:
        if connection.in_transaction:
            connection.rollback()
        raise
    except sqlite3.Error as exc:
        if connection.in_transaction:
            connection.rollback()
        raise MigrationError("SQLite migration failed; transaction rolled back") from exc
    finally:
        connection.close()


def database_is_ready(
    database_path: Path,
    *,
    migration_directory: Path | None = None,
) -> bool:
    """Read-only readiness probe; it never creates a missing database."""

    try:
        migrations = load_migrations(migration_directory)
    except MigrationError:
        return False
    path = Path(database_path)
    if not path.is_file():
        return False

    from urllib.parse import quote

    uri = f"file:{quote(path.resolve().as_posix(), safe='/')}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=1)
        try:
            rows = connection.execute(
                "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
            ).fetchall()
            applied = {
                int(version): (str(name), str(checksum))
                for version, name, checksum in rows
            }
            expected = {
                migration.version: (migration.name, migration.checksum)
                for migration in migrations
            }
            return applied == expected
        finally:
            connection.close()
    except sqlite3.Error:
        return False
