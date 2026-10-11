"""Verified SQLite online backup, verification, and isolated restore tools."""

from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from rendiv_api.migrations import MigrationError, verify_migration_state


JOB_STATES = ("queued", "running", "succeeded", "failed", "unknown")
_EXPECTED_COLUMNS = {
    "schema_migrations": {
        "version", "name", "checksum", "applied_at_utc",
    },
    "jobs": {
        "job_id", "source_principal", "operation", "idempotency_key",
        "payload_format", "payload_json", "payload_sha256", "state",
        "effect_certainty", "queue_seq", "created_at_ms", "updated_at_ms",
        "finished_at_ms", "error_code",
    },
    "job_events": {
        "event_seq", "event_id", "job_id", "event_type", "from_state",
        "to_state", "actor_type", "actor_id", "occurred_at_ms",
        "reason_code", "metadata_json",
    },
}


class BackupError(RuntimeError):
    """A backup or restore operation could not complete safely."""


@dataclass(frozen=True)
class DatabaseVerification:
    schema_version: int
    job_counts: dict[str, int]


@dataclass(frozen=True)
class BackupResult:
    path: Path
    sha256: str
    size_bytes: int
    schema_version: int
    job_counts: dict[str, int]


def _readonly_uri(path: Path) -> str:
    return f"file:{quote(path.resolve().as_posix(), safe='/')}?mode=ro"


def _connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise BackupError("SQLite file does not exist or is not a regular file")
    try:
        connection = sqlite3.connect(_readonly_uri(path), uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        if connection.execute("PRAGMA query_only").fetchone()[0] != 1:
            connection.close()
            raise BackupError("SQLite read-only mode could not be enabled")
        return connection
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise BackupError("unable to open SQLite file read-only") from exc


def _job_counts(connection: sqlite3.Connection) -> dict[str, int]:
    rows = connection.execute(
        "SELECT state, COUNT(*) AS jobs_count FROM jobs GROUP BY state"
    ).fetchall()
    counts = {state: 0 for state in JOB_STATES}
    for row in rows:
        state = str(row["state"])
        if state not in counts:
            raise BackupError("database contains an unsupported job state")
        counts[state] = int(row["jobs_count"])
    return counts


def verify_database(path: Path) -> DatabaseVerification:
    """Check integrity, foreign keys, expected columns, and migration checksums."""

    connection = _connect_readonly(Path(path))
    try:
        integrity = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
        if integrity != ["ok"]:
            raise BackupError("SQLite integrity_check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise BackupError("SQLite foreign_key_check failed")

        try:
            schema_version = verify_migration_state(connection)
        except MigrationError as exc:
            raise BackupError("SQLite migration schema/checksum validation failed") from exc

        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }
        if tables != set(_EXPECTED_COLUMNS):
            raise BackupError("SQLite table structure does not match the expected schema")
        for table, expected_columns in _EXPECTED_COLUMNS.items():
            actual_columns = {
                str(row["name"])
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            }
            if actual_columns != expected_columns:
                raise BackupError("SQLite column structure does not match the expected schema")

        return DatabaseVerification(
            schema_version=schema_version,
            job_counts=_job_counts(connection),
        )
    except BackupError:
        raise
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise BackupError("SQLite verification failed") from exc
    finally:
        connection.close()


def _sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise BackupError("unable to read SQLite file for checksum") from exc
    return digest.hexdigest(), size


def _sync_file(path: Path) -> None:
    try:
        with path.open("rb") as file_handle:
            os.fsync(file_handle.fileno())
    except OSError as exc:
        raise BackupError("unable to make SQLite file durable") from exc


def _sync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise BackupError("unable to make SQLite publication durable") from exc


def _check_new_destination(destination: Path) -> None:
    if not destination.is_absolute():
        raise BackupError("destination path must be explicit and absolute")
    if not destination.parent.is_dir():
        raise BackupError("destination parent directory does not exist")
    if os.path.lexists(destination):
        raise BackupError("destination already exists; refusing to overwrite")


def _copy_online(source_path: Path, temporary_path: Path) -> None:
    source = _connect_readonly(source_path)
    target: sqlite3.Connection | None = None
    try:
        target = sqlite3.connect(temporary_path, timeout=5, isolation_level=None)
        target.execute("PRAGMA synchronous = FULL")
        source.backup(target, pages=256, sleep=0.05)
    except (OSError, sqlite3.Error) as exc:
        raise BackupError("SQLite online backup failed") from exc
    finally:
        if target is not None:
            target.close()
        source.close()


def _temporary_database(parent: Path, destination_name: str) -> Path:
    descriptor: int | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{destination_name}.", suffix=".tmp", dir=parent
        )
        os.fchmod(descriptor, 0o600)
        os.close(descriptor)
        descriptor = None
        return Path(name)
    except OSError as exc:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise BackupError("unable to create a private temporary SQLite file") from exc


def _publish_noreplace(temporary_path: Path, destination: Path) -> tuple[int, int]:
    """Atomically publish a verified file without replacing any existing path."""

    try:
        os.link(temporary_path, destination, follow_symlinks=False)
        stat_result = destination.stat(follow_symlinks=False)
        identity = (stat_result.st_dev, stat_result.st_ino)
        try:
            _sync_directory(destination.parent)
        except BackupError:
            _remove_published_if_same(destination, identity)
            raise
        return identity
    except FileExistsError as exc:
        raise BackupError("destination already exists; refusing to overwrite") from exc
    except OSError as exc:
        raise BackupError("unable to atomically publish SQLite file") from exc


def _remove_published_if_same(path: Path, identity: tuple[int, int] | None) -> None:
    if identity is None:
        return
    try:
        current = path.stat(follow_symlinks=False)
        if (current.st_dev, current.st_ino) == identity:
            path.unlink()
            _sync_directory(path.parent)
    except OSError:
        pass


def _cleanup_temporary(path: Path | None) -> None:
    if path is None:
        return
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass


def _create_verified_copy(source_path: Path, destination_path: Path) -> BackupResult:
    source = Path(source_path)
    destination = Path(destination_path)
    if source.resolve() == destination.resolve(strict=False):
        raise BackupError("source and destination must be different paths")
    _check_new_destination(destination)
    source_verification = verify_database(source)

    temporary_path: Path | None = None
    published_identity: tuple[int, int] | None = None
    try:
        temporary_path = _temporary_database(destination.parent, destination.name)
        _copy_online(source, temporary_path)
        temporary_verification = verify_database(temporary_path)
        # Job counts can change during a live backup. The Online Backup API
        # snapshot is validated independently; the migration schema must match.
        if temporary_verification.schema_version != source_verification.schema_version:
            raise BackupError("copied database schema changed during backup")
        _sync_file(temporary_path)
        digest, size = _sha256_and_size(temporary_path)
        published_identity = _publish_noreplace(temporary_path, destination)
        final_verification = verify_database(destination)
        final_digest, final_size = _sha256_and_size(destination)
        if (digest, size) != (final_digest, final_size):
            raise BackupError("published SQLite checksum does not match verified temporary file")
        return BackupResult(
            path=destination,
            sha256=digest,
            size_bytes=size,
            schema_version=final_verification.schema_version,
            job_counts=final_verification.job_counts,
        )
    except Exception:
        _remove_published_if_same(destination, published_identity)
        raise
    finally:
        _cleanup_temporary(temporary_path)


def create_backup(source_path: Path, destination_path: Path) -> BackupResult:
    """Create a consistent SQLite Online Backup at a new, absolute path."""

    return _create_verified_copy(source_path, destination_path)


def restore_backup(backup_path: Path, new_database_path: Path) -> BackupResult:
    """Restore a verified backup into a new, explicit, non-existent path only."""

    backup = Path(backup_path)
    verify_database(backup)
    return _create_verified_copy(backup, new_database_path)


def _print_result(action: str, result: BackupResult) -> None:
    counts = " ".join(f"{state}={result.job_counts[state]}" for state in JOB_STATES)
    attention = (
        f"operator_attention running={result.job_counts['running']} "
        f"unknown={result.job_counts['unknown']}"
    )
    print(
        f"{action} successful path={result.path} schema={result.schema_version} "
        f"size_bytes={result.size_bytes} sha256={result.sha256} jobs[{counts}] {attention}"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verified Rendiv SQLite backup tools")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create", help="create a new verified online backup")
    create.add_argument("source", type=Path)
    create.add_argument("destination", type=Path)
    verify = subparsers.add_parser("verify", help="verify integrity and migration checksums")
    verify.add_argument("backup", type=Path)
    restore = subparsers.add_parser("restore", help="restore to a new database path")
    restore.add_argument("backup", type=Path)
    restore.add_argument("new_database", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            result = create_backup(args.source, args.destination)
            _print_result("backup", result)
        elif args.command == "verify":
            verification = verify_database(args.backup)
            counts = " ".join(
                f"{state}={verification.job_counts[state]}" for state in JOB_STATES
            )
            print(
                f"verification successful path={args.backup} "
                f"schema={verification.schema_version} jobs[{counts}] "
                f"operator_attention running={verification.job_counts['running']} "
                f"unknown={verification.job_counts['unknown']}"
            )
        else:
            result = restore_backup(args.backup, args.new_database)
            _print_result("restore", result)
        return 0
    except BackupError as exc:
        print(f"{args.command} failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
