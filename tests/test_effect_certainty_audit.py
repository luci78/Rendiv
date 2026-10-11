from __future__ import annotations

import json
import socket
import sqlite3
from pathlib import Path

import pytest

from rendiv_api.migrations import apply_migrations
from rendiv_api.persistence import EnqueueRepository
from rendiv_api.understory_adapter import UnderstoryExecutorAdapter
from rendiv_api.worker import ExecutionResult, LocalWorker, WorkerOutcome, WorkerRun


OPERATIONS = [
    ("memory_add", {"content": "audit canary"}),
    ("memory_update", {"instruction": "audit canary"}),
    ("memory_maintain", {}),
]


class MatrixTransport:
    def __init__(self, mode: str):
        self.mode = mode
        self.calls = 0
        self.effect_count = 0
        self.previous_response: str | None = None

    def exchange(self, request_text: str) -> str:
        self.calls += 1
        request = json.loads(request_text)
        if self.mode == "timeout_before":
            raise TimeoutError("fake timeout")
        if self.mode == "timeout_after":
            self.effect_count += 1
            raise TimeoutError("fake timeout")
        if self.mode == "disconnect_before":
            raise ConnectionError("fake disconnect")
        if self.mode == "disconnect_after":
            self.effect_count += 1
            raise ConnectionError("fake disconnect")
        if self.mode == "invalid":
            return "not JSON"
        if self.mode == "duplicate" and self.previous_response is not None:
            return self.previous_response

        text, is_error = {
            "success": ("Done\n\nFiles changed:\n- /reported.md", False),
            "success_without_paths": ("Done\n\nFiles changed:\n- none", False),
            "failed": ("Mutation failed", True),
            "partial": ("⚠ Partial mutation: file changed before failure", False),
            "noop": ("Memory is healthy; nothing to repair.", False),
        }.get(self.mode, ("Done\n\nFiles changed:\n- /reported.md", False))
        response = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {
                    "content": [{"type": "text", "text": text}],
                    "isError": is_error,
                },
            }
        )
        if self.mode == "contradictory":
            decoded = json.loads(response)
            decoded["error"] = {"code": -1, "message": "contradictory"}
            response = json.dumps(decoded)
        self.previous_response = response
        return response


@pytest.mark.parametrize("operation,payload", OPERATIONS)
@pytest.mark.parametrize(
    "mode,expected",
    [
        ("success", WorkerOutcome.UNKNOWN),
        ("success_without_paths", WorkerOutcome.UNKNOWN),
        ("failed", WorkerOutcome.UNKNOWN),
        ("partial", WorkerOutcome.UNKNOWN),
        ("timeout_before", WorkerOutcome.TIMEOUT),
        ("timeout_after", WorkerOutcome.TIMEOUT),
        ("disconnect_before", WorkerOutcome.UNKNOWN),
        ("disconnect_after", WorkerOutcome.UNKNOWN),
        ("invalid", WorkerOutcome.UNKNOWN),
        ("contradictory", WorkerOutcome.UNKNOWN),
    ],
)
def test_effect_matrix_for_each_operation(operation: str, payload: dict, mode: str, expected: WorkerOutcome):
    transport = MatrixTransport(mode)
    result = UnderstoryExecutorAdapter(transport=transport)(operation, payload)
    assert result.outcome is expected
    assert transport.calls == 1
    assert transport.effect_count == (1 if mode.endswith("_after") else 0)


def test_maintain_noop_is_unknown_and_blocks_queue(tmp_path: Path):
    database = tmp_path / "maintain-noop.sqlite3"
    apply_migrations(database)
    EnqueueRepository(database).enqueue(
        source_principal="audit-test",
        operation="memory_maintain",
        idempotency_key="noop",
        payload={},
    )
    EnqueueRepository(database).enqueue(
        source_principal="audit-test",
        operation="memory_add",
        idempotency_key="behind-noop",
        payload={"content": "later"},
    )
    transport = MatrixTransport("noop")
    result = LocalWorker(
        database, executor=UnderstoryExecutorAdapter(transport=transport)
    ).run_until_idle()
    assert result == WorkerRun(1, "unknown_blocks_queue")
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT state, effect_certainty FROM jobs ORDER BY queue_seq"
        ).fetchall() == [("unknown", "unknown"), ("queued", "none")]
        assert connection.execute(
            "SELECT reason_code FROM job_events WHERE event_type='worker_uncertain'"
        ).fetchone() == ("maintain_response_unverified",)
    assert transport.calls == 1


def test_changed_paths_are_reported_evidence_not_independent_readback():
    transport = MatrixTransport("success")
    result = UnderstoryExecutorAdapter(transport=transport)(
        "memory_add", {"content": "audit canary"}
    )
    # The peer reports a changed path while its independent effect counter is zero.
    assert result.outcome is WorkerOutcome.UNKNOWN
    assert result.audit_reason_code == "reported_success_unverified"
    assert transport.effect_count == 0


@pytest.mark.parametrize("operation,payload", OPERATIONS)
def test_duplicate_prior_response_with_different_id_is_unknown(operation: str, payload: dict):
    transport = MatrixTransport("success")
    first_adapter = UnderstoryExecutorAdapter(transport=transport)
    first = first_adapter(operation, payload)
    transport.mode = "duplicate"
    # A newly constructed adapter used to restart integer IDs at 1; the UUID
    # correlation ID must make a stale response from the prior adapter invalid.
    second_adapter = UnderstoryExecutorAdapter(transport=transport)
    second = second_adapter(operation, payload)
    assert first.outcome is WorkerOutcome.UNKNOWN
    assert second.outcome is WorkerOutcome.UNKNOWN
    assert transport.calls == 2


@pytest.mark.parametrize("operation,payload", OPERATIONS)
def test_crash_during_adapter_exchange_recovers_running_as_unknown(
    tmp_path: Path, operation: str, payload: dict
):
    class CrashTransport:
        def exchange(self, _request_text: str) -> str:
            raise SimulatedCrash()

    database = tmp_path / "crash.sqlite3"
    apply_migrations(database)
    EnqueueRepository(database).enqueue(
        source_principal="audit-test",
        operation=operation,
        idempotency_key="crash",
        payload=payload,
    )
    adapter = UnderstoryExecutorAdapter(transport=CrashTransport())
    with pytest.raises(SimulatedCrash):
        LocalWorker(database, executor=adapter).run_until_idle()
    assert LocalWorker(
        database,
        executor=UnderstoryExecutorAdapter(transport=MatrixTransport("success")),
    ).run_until_idle() == WorkerRun(0, "unknown_blocks_queue")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT state, effect_certainty FROM jobs").fetchone() == (
            "unknown",
            "unknown",
        )
        assert connection.execute(
            "SELECT event_type, from_state, to_state FROM job_events ORDER BY event_seq"
        ).fetchall()[-1] == ("recovered_running_as_unknown", "running", "unknown")


class SimulatedCrash(BaseException):
    pass


def test_worker_rejects_no_effect_result_without_verifiable_evidence(tmp_path: Path):
    database = tmp_path / "failed.sqlite3"
    apply_migrations(database)
    EnqueueRepository(database).enqueue(
        source_principal="audit-test",
        operation="memory_update",
        idempotency_key="failed",
        payload={"instruction": "fake"},
    )

    result = LocalWorker(
        database,
        executor=lambda _operation, _payload: ExecutionResult(WorkerOutcome.FAILED_NO_EFFECT),
    ).run_until_idle()

    assert result == WorkerRun(1, "unknown_blocks_queue")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT state, effect_certainty FROM jobs").fetchone() == (
            "unknown",
            "unknown",
        )
        assert connection.execute(
            "SELECT event_type, reason_code FROM job_events ORDER BY event_seq"
        ).fetchall()[-1] == ("worker_uncertain", "no_effect_unproven")


def test_audit_and_logs_do_not_include_payload_or_response_text(tmp_path: Path, caplog):
    database = tmp_path / "redaction.sqlite3"
    apply_migrations(database)
    EnqueueRepository(database).enqueue(
        source_principal="audit-test",
        operation="memory_add",
        idempotency_key="redaction",
        payload={"content": "AUDIT_PRIVATE_CANARY"},
    )
    fake = MatrixTransport("success")
    LocalWorker(database, executor=UnderstoryExecutorAdapter(transport=fake)).run_until_idle()

    with sqlite3.connect(database) as connection:
        audit_rows = connection.execute(
            "SELECT event_type, reason_code, metadata_json FROM job_events"
        ).fetchall()
    assert all("AUDIT_PRIVATE_CANARY" not in repr(row) for row in audit_rows)
    assert all(row[2] == "{}" for row in audit_rows)
    assert "AUDIT_PRIVATE_CANARY" not in caplog.text


def test_fake_protocol_never_creates_socket(monkeypatch: pytest.MonkeyPatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("external socket use")

    monkeypatch.setattr(socket, "socket", forbidden)
    adapter = UnderstoryExecutorAdapter(transport=MatrixTransport("success"))
    maintain_result = adapter("memory_maintain", {})
    assert maintain_result.outcome is WorkerOutcome.UNKNOWN
    assert maintain_result.audit_reason_code == "reported_success_unverified"
