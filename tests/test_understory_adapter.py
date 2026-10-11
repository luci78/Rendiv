from __future__ import annotations

import sqlite3
import socket
from pathlib import Path

import pytest

from rendiv_api.migrations import apply_migrations
from rendiv_api.persistence import EnqueueRepository
from rendiv_api.understory_adapter import (
    AdapterInputError,
    Operation,
    ResultClass,
    TransportFailure,
    TransportRequest,
    TransportResponse,
    UnderstoryExecutorAdapter,
)
from rendiv_api.worker import LocalWorker, WorkerOutcome, WorkerRun


class FakeTransport:
    def __init__(self, result: object | BaseException):
        self.result = result
        self.requests: list[TransportRequest] = []
        self.simulated_effects = 0
        self.calls = 0

    def execute(self, request: TransportRequest) -> object:
        self.calls += 1
        self.requests.append(request)
        if isinstance(self.result, BaseException):
            raise self.result
        if self.result == "apply_then_timeout":
            self.simulated_effects += 1
            raise TimeoutError("simulated timeout")
        if self.result == "timeout_before_apply":
            raise TimeoutError("simulated timeout")
        if self.result == "apply_then_disconnect":
            self.simulated_effects += 1
            raise TransportFailure("simulated connection interruption")
        if self.result == "apply_then_ambiguous":
            self.simulated_effects += 1
            return TransportResponse(ResultClass.UNCERTAIN)
        return self.result


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("memory_add", Operation.MEMORY_ADD),
        ("memory_update", Operation.MEMORY_UPDATE),
        ("memory_maintain", Operation.MEMORY_MAINTAIN),
    ],
)
def test_each_confirmed_operation_passes_generic_payload(operation: str, expected: Operation):
    transport = FakeTransport(TransportResponse(ResultClass.CONFIRMED_SUCCESS))

    result = UnderstoryExecutorAdapter(transport=transport)(operation, {"opaque": [1]})

    assert result.outcome is WorkerOutcome.SUCCEEDED
    assert transport.requests == [TransportRequest(expected, {"opaque": [1]})]
    assert transport.calls == 1


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (ResultClass.CONFIRMED_SUCCESS, WorkerOutcome.SUCCEEDED),
        (ResultClass.CONFIRMED_NO_EFFECT, WorkerOutcome.FAILED_NO_EFFECT),
        (ResultClass.UNCERTAIN, WorkerOutcome.UNKNOWN),
        (ResultClass.TIMEOUT, WorkerOutcome.TIMEOUT),
        (ResultClass.TRANSPORT_ERROR, WorkerOutcome.UNKNOWN),
        (ResultClass.INVALID_RESPONSE, WorkerOutcome.UNKNOWN),
    ],
)
def test_explicit_result_classification(response: ResultClass, expected: WorkerOutcome):
    adapter = UnderstoryExecutorAdapter(
        transport=FakeTransport(TransportResponse(response))
    )
    assert adapter("memory_update", {}).outcome is expected


@pytest.mark.parametrize(
    ("operation", "payload"),
    [
        ("unknown_operation", {}),
        ("memory_add", []),
        ("memory_add", {"not-json": object()}),
        ("memory_add", {"nan": float("nan")}),
    ],
)
def test_invalid_jobs_are_rejected_before_transport(operation: str, payload: object):
    transport = FakeTransport(TransportResponse(ResultClass.CONFIRMED_SUCCESS))
    with pytest.raises(AdapterInputError):
        UnderstoryExecutorAdapter(transport=transport)(operation, payload)  # type: ignore[arg-type]
    assert transport.calls == 0


@pytest.mark.parametrize(
    ("fake_result", "expected_effect_count"),
    [("timeout_before_apply", 0), ("apply_then_timeout", 1)],
)
def test_timeout_before_or_after_fake_effect_is_uncertain(
    fake_result: str, expected_effect_count: int
):
    transport = FakeTransport(fake_result)
    result = UnderstoryExecutorAdapter(transport=transport)("memory_add", {})
    assert result.outcome is WorkerOutcome.TIMEOUT
    assert transport.simulated_effects == expected_effect_count
    assert transport.calls == 1


@pytest.mark.parametrize(
    ("fake_result", "expected_effect_count"),
    [
        (TransportFailure("disconnect"), 0),
        ("apply_then_disconnect", 1),
        ("apply_then_ambiguous", 1),
    ],
)
def test_disconnect_and_ambiguous_result_fail_closed(
    fake_result: object, expected_effect_count: int
):
    transport = FakeTransport(fake_result)
    adapter = UnderstoryExecutorAdapter(transport=transport)
    result = adapter("memory_add", {})
    assert result.outcome is WorkerOutcome.UNKNOWN
    assert transport.simulated_effects == expected_effect_count
    assert transport.calls == 1


def test_invalid_transport_response_is_unknown():
    transport = FakeTransport({"status": "success"})
    assert (
        UnderstoryExecutorAdapter(transport=transport)("memory_add", {}).outcome
        is WorkerOutcome.UNKNOWN
    )
    assert transport.calls == 1


def test_adapter_uses_no_socket_or_network(monkeypatch: pytest.MonkeyPatch):
    def forbidden_socket(*args: object, **kwargs: object) -> None:
        raise AssertionError("adapter attempted to create a socket")

    monkeypatch.setattr(socket, "socket", forbidden_socket)
    transport = FakeTransport(TransportResponse(ResultClass.CONFIRMED_SUCCESS))
    result = UnderstoryExecutorAdapter(transport=transport)("memory_add", {})
    assert result.outcome is WorkerOutcome.SUCCEEDED
    assert transport.calls == 1


def test_adapter_blocks_queue_audits_unknown_and_never_retries(tmp_path: Path):
    database = tmp_path / "queue.sqlite3"
    apply_migrations(database)
    repository = EnqueueRepository(database)
    first = repository.enqueue(
        source_principal="adapter-test", operation="memory_add",
        idempotency_key="one", payload={"opaque": "one"},
    ).job_id
    second = repository.enqueue(
        source_principal="adapter-test", operation="memory_maintain",
        idempotency_key="two", payload={"opaque": "two"},
    ).job_id
    transport = FakeTransport("apply_then_timeout")
    adapter = UnderstoryExecutorAdapter(transport=transport)

    result = LocalWorker(database, executor=adapter).run_until_idle()
    assert result == WorkerRun(processed=1, stop_reason="unknown_blocks_queue")
    assert transport.calls == 1
    with sqlite3.connect(database) as connection:
        jobs = connection.execute(
            "SELECT job_id, state, effect_certainty FROM jobs ORDER BY queue_seq"
        ).fetchall()
        events = connection.execute(
            "SELECT event_type, from_state, to_state FROM job_events ORDER BY event_seq"
        ).fetchall()
    assert jobs == [(first, "unknown", "unknown"), (second, "queued", "none")]
    assert events[-2:] == [
        ("worker_claimed", "queued", "running"),
        ("worker_uncertain", "running", "unknown"),
    ]

    restarted = LocalWorker(database, executor=adapter).run_until_idle()
    assert restarted == WorkerRun(processed=0, stop_reason="unknown_blocks_queue")
    assert transport.calls == 1


def test_confirmed_no_effect_integrates_with_worker_audit(tmp_path: Path):
    database = tmp_path / "queue.sqlite3"
    apply_migrations(database)
    EnqueueRepository(database).enqueue(
        source_principal="adapter-test", operation="memory_update",
        idempotency_key="no-effect", payload={},
    )
    transport = FakeTransport(TransportResponse(ResultClass.CONFIRMED_NO_EFFECT))
    result = LocalWorker(
        database, executor=UnderstoryExecutorAdapter(transport=transport)
    ).run_until_idle()
    assert result == WorkerRun(processed=1, stop_reason="idle")
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT state, effect_certainty FROM jobs"
        ).fetchone() == ("failed", "none")
        assert connection.execute(
            "SELECT event_type FROM job_events ORDER BY event_seq"
        ).fetchall()[-1] == ("worker_failed_no_effect",)
