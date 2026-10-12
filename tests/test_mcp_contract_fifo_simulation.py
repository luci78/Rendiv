"""Offline end-to-end policy harness: fake MCP response to simulated FIFO gate.

This deliberately models the current fail-closed policy in a tiny temporary
SQLite table. It does not instantiate the production worker or adapter.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from rendiv_api.mcp_contract_v1 import (
    ContractValidationError,
    classify_for_rendiv,
    unknown_disposition,
    validate_mcp_response,
)


OPERATIONS = ("memory_add", "memory_update", "memory_maintain")
REQUEST_ID = "rendiv-offline-call-1"


def _structured(operation: str, outcome: str) -> dict[str, Any]:
    if outcome == "applied":
        execution, path, effect, scope, paths = (
            "completed", "mutating", "reported_applied", "reported_paths_only", ["concepts/a.md"]
        )
    elif outcome == "no_op":
        execution, path, effect, scope, paths = (
            "completed", "healthy_no_op", "reported_none", "operation_scope", []
        )
    elif outcome == "rejected_before_write":
        execution, path, effect, scope, paths = (
            "not_completed", "rejected_pre_write", "reported_none", "operation_scope", []
        )
    elif outcome == "partial":
        execution, path, effect, scope, paths = (
            "completed", "mutating", "reported_partial", "reported_paths_only", ["concepts/a.md"]
        )
    else:
        execution, path, effect, scope, paths = "unknown", "unknown", "unknown", "unknown", []

    result: dict[str, Any] = {
        "contract_version": "understory-mcp-result/1",
        "request_id": REQUEST_ID,
        "operation_id": "0199c0a4-6b3a-7f20-a019-fc6f1d2a8b11",
        "operation": operation,
        "outcome": outcome,
        "no_op": outcome == "no_op",
        "changed_paths": paths,
        "evidence": {
            "execution": execution,
            "execution_path": path,
            "effect": effect,
            "effect_scope": scope,
            "read_back": "not_performed",
            "atomicity": "not_asserted",
            "durability": "not_asserted",
        },
    }
    if outcome in {"partial", "rejected_before_write", "unknown"}:
        result["reason_code"] = {
            "partial": "partial_effect",
            "rejected_before_write": "invalid_arguments",
            "unknown": "upstream_timeout",
        }[outcome]
    return result


def _response(operation: str, outcome: str) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": REQUEST_ID,
            "result": {
                "structuredContent": _structured(operation, outcome),
                "content": [{"type": "text", "text": "simulated legacy-compatible text"}],
                "isError": False,
            },
        }
    )


class FakeMcpTransport:
    def __init__(self, response: str | Exception) -> None:
        self.response = response
        self.calls = 0

    def exchange(self) -> str:
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class SqliteFifoHarness:
    """Test-only queue gate; schema exists only in a tmp_path database."""

    def __init__(self, database: Path) -> None:
        self.database = database
        with sqlite3.connect(database) as db:
            db.execute(
                "CREATE TABLE jobs (queue_seq INTEGER PRIMARY KEY, state TEXT NOT NULL, "
                "effect_certainty TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0)"
            )
            db.executemany(
                "INSERT INTO jobs(queue_seq, state, effect_certainty) VALUES (?, 'queued', 'none')",
                [(1,), (2,)],
            )

    def process_one(self, operation: str, transport: FakeMcpTransport) -> None:
        with sqlite3.connect(self.database) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM jobs WHERE state='unknown' LIMIT 1").fetchone():
                db.rollback()
                return
            first = db.execute(
                "SELECT queue_seq FROM jobs WHERE state='queued' ORDER BY queue_seq LIMIT 1"
            ).fetchone()
            if first is None:
                db.commit()
                return
            queue_seq = first[0]
            db.execute("UPDATE jobs SET state='running' WHERE queue_seq=?", (queue_seq,))
            db.execute("UPDATE jobs SET attempts=attempts+1 WHERE queue_seq=?", (queue_seq,))
            db.commit()

        try:
            raw = transport.exchange()
            parsed = validate_mcp_response(
                raw,
                expected_request_id=REQUEST_ID,
                expected_operation=operation,
            )
            disposition = classify_for_rendiv(parsed)
        except (ContractValidationError, TimeoutError, ConnectionError, ValueError):
            disposition = unknown_disposition("timeout_or_disconnect")

        with sqlite3.connect(self.database) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE jobs SET state=?, effect_certainty=? WHERE queue_seq=?",
                (disposition.job_state, disposition.effect_certainty, queue_seq),
            )
            db.commit()

    def rows(self) -> list[tuple[int, str, str, int]]:
        with sqlite3.connect(self.database) as db:
            return db.execute(
                "SELECT queue_seq, state, effect_certainty, attempts FROM jobs ORDER BY queue_seq"
            ).fetchall()


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("outcome", ("applied", "rejected_before_write", "partial", "unknown"))
def test_full_fake_mcp_to_sqlite_fifo_path_blocks_for_each_operation_and_outcome(
    tmp_path: Path, operation: str, outcome: str
) -> None:
    queue = SqliteFifoHarness(tmp_path / "queue.sqlite3")
    transport = FakeMcpTransport(_response(operation, outcome))

    queue.process_one(operation, transport)
    queue.process_one(operation, transport)  # blocked gate must not retry or claim next

    assert queue.rows() == [
        (1, "unknown", "unknown", 1),
        (2, "queued", "none", 0),
    ]
    assert transport.calls == 1


def test_maintain_no_op_stays_unknown_and_blocks_fifo(tmp_path: Path) -> None:
    queue = SqliteFifoHarness(tmp_path / "queue.sqlite3")
    transport = FakeMcpTransport(_response("memory_maintain", "no_op"))

    queue.process_one("memory_maintain", transport)
    queue.process_one("memory_maintain", transport)

    assert queue.rows() == [(1, "unknown", "unknown", 1), (2, "queued", "none", 0)]
    assert transport.calls == 1


@pytest.mark.parametrize("operation", OPERATIONS)
def test_mcp_failures_and_legacy_responses_block_fifo_without_retry(
    tmp_path: Path, operation: str
) -> None:
    cases: tuple[str | Exception, ...] = (
        '{"jsonrpc":"2.0","id":"wrong","result":{}}',
        '{"jsonrpc":"2.0","id":"rendiv-offline-call-1","result":{"content":[{"type":"text","text":"success"}]}}',
        '{"jsonrpc":"2.0","id":"rendiv-offline-call-1","result":{"structuredContent":null}}',
        TimeoutError("fake timeout"),
        ConnectionError("fake disconnect"),
        "not-json",
    )
    for index, response in enumerate(cases):
        queue = SqliteFifoHarness(tmp_path / f"failure-{index}.sqlite3")
        transport = FakeMcpTransport(response)

        queue.process_one(operation, transport)
        queue.process_one(operation, transport)

        assert queue.rows() == [(1, "unknown", "unknown", 1), (2, "queued", "none", 0)]
        assert transport.calls == 1


@pytest.mark.parametrize("operation", ("memory_add", "memory_update"))
def test_no_op_for_add_and_update_is_invalid_and_still_blocks(
    tmp_path: Path, operation: str
) -> None:
    queue = SqliteFifoHarness(tmp_path / f"invalid-noop-{operation}.sqlite3")
    transport = FakeMcpTransport(_response(operation, "no_op"))

    queue.process_one(operation, transport)
    queue.process_one(operation, transport)

    assert queue.rows() == [(1, "unknown", "unknown", 1), (2, "queued", "none", 0)]
    assert transport.calls == 1
