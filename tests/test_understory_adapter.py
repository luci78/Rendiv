from __future__ import annotations

import json
import socket
import sqlite3
from pathlib import Path

import pytest

from rendiv_api.migrations import apply_migrations
from rendiv_api.persistence import EnqueueRepository
from rendiv_api.understory_adapter import (
    AdapterInputError,
    EffectClassification,
    Operation,
    UnderstoryExecutorAdapter,
    classify_effect,
    decode_tool_result,
    serialize_tool_call,
    validate_job,
)
from rendiv_api.worker import LocalWorker, WorkerOutcome, WorkerRun


class FakeMcpTransport:
    """In-memory MCP peer; accepts/returns serialized JSON only."""

    def __init__(self, *, response_text: str | None = None, is_error: bool = False,
                 mode: str = "reply"):
        self.response_text = response_text or "Completed\n\nFiles changed:\n- /fake/concept.md"
        self.is_error = is_error
        self.mode = mode
        self.requests: list[dict] = []
        self.exchange_count = 0
        self.simulated_effects = 0

    def exchange(self, request_text: str) -> str:
        self.exchange_count += 1
        request = json.loads(request_text)
        self.requests.append(request)
        if self.mode == "timeout_before_effect":
            raise TimeoutError("fake timeout")
        if self.mode == "timeout_after_effect":
            self.simulated_effects += 1
            raise TimeoutError("fake timeout")
        if self.mode == "disconnect":
            raise ConnectionError("fake disconnect")
        if self.mode == "disconnect_after_effect":
            self.simulated_effects += 1
            raise ConnectionError("fake disconnect")
        if self.mode == "partial":
            self.simulated_effects += 1
            text = "⚠ Partial mutation: one file changed before failure.\nFiles: /fake/a.md\nError: fake"
            return json.dumps(self._result(request["id"], text, False))
        text = self.response_text
        return json.dumps(self._result(request["id"], text, self.is_error))

    @staticmethod
    def _result(request_id: int, text: str, is_error: bool) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": text}],
                "isError": is_error,
            },
        }


@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        ("memory_add", {"content": "Remember this", "suggested_path": "/notes/item.md"}),
        ("memory_add", {"content": "Remember this"}),
        ("memory_update", {"instruction": "Correct the description"}),
        ("memory_maintain", {}),
    ],
)
def test_documented_operation_arguments_serialize_as_mcp_tools_call(operation: str, arguments: dict):
    job = validate_job(operation, arguments)
    decoded = json.loads(serialize_tool_call(17, job))
    assert decoded == {
        "jsonrpc": "2.0",
        "id": 17,
        "method": "tools/call",
        "params": {"name": operation, "arguments": arguments},
    }


@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        ("memory_add", {}),
        ("memory_add", {"content": 3}),
        ("memory_add", {"content": "x", "suggested_path": None}),
        ("memory_add", {"content": "x", "undocumented": "field"}),
        ("memory_update", {}),
        ("memory_update", {"instruction": []}),
        ("memory_update", {"instruction": "x", "extra": "field"}),
        ("memory_maintain", {"content": "not allowed"}),
        ("memory_maintain", {"unexpected": True}),
        ("memory_add", {"content": float("nan")}),
    ],
)
def test_invalid_arguments_are_rejected_before_transport(operation: str, arguments: dict):
    fake = FakeMcpTransport()
    adapter = UnderstoryExecutorAdapter(transport=fake)
    with pytest.raises(AdapterInputError):
        adapter(operation, arguments)
    assert fake.exchange_count == 0


@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        ("memory_add", {"content": "Remember this"}),
        ("memory_add", {"content": "Remember this", "suggested_path": "/fake/a.md"}),
        ("memory_update", {"instruction": "Update this"}),
        ("memory_maintain", {}),
    ],
)
def test_fake_mcp_round_trip_confirms_only_nonempty_reported_file_paths(operation: str, arguments: dict):
    fake = FakeMcpTransport()
    adapter = UnderstoryExecutorAdapter(transport=fake)
    result = adapter(operation, arguments)
    assert result.outcome is WorkerOutcome.SUCCEEDED
    assert fake.exchange_count == 1
    request = fake.requests[0]
    assert request["method"] == "tools/call"
    assert request["params"]["name"] == operation
    assert request["params"]["arguments"] == arguments


def test_decoder_rejects_wrong_id_error_envelope_and_invalid_content():
    cases = [
        json.dumps({"jsonrpc": "2.0", "id": 99, "result": {"content": []}}),
        json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "failed"}}),
        json.dumps({"jsonrpc": "1.0", "id": 1, "result": {"content": []}}),
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "image"}]}}),
        "{broken",
    ]
    for response in cases:
        with pytest.raises(ValueError):
            decode_tool_result(response, 1)


@pytest.mark.parametrize(
    ("text", "is_error", "expected"),
    [
        ("Done\n\nFiles changed:\n- /a.md", False, EffectClassification.CONFIRMED_SUCCESS),
        ("⚠ Partial mutation: 1 file written.\nFiles: /a.md\nError: stop", False, EffectClassification.UNKNOWN),
        ("Mutation failed: denied", True, EffectClassification.UNKNOWN),
        ("Mutation failed: uncertain", False, EffectClassification.UNKNOWN),
        ("Completed\n\nFiles changed:\n- none", False, EffectClassification.UNKNOWN),
        ("Memory is healthy; nothing to repair.", False, EffectClassification.UNKNOWN),
        ("Done\n\nFiles changed:\n", False, EffectClassification.UNKNOWN),
        ("Done\n\nFiles changed:\n/a.md", False, EffectClassification.UNKNOWN),
    ],
)
def test_result_classification_is_conservative(text: str, is_error: bool, expected: EffectClassification):
    decoded = decode_tool_result(json.dumps(FakeMcpTransport._result(3, text, is_error)), 3)
    assert classify_effect(decoded) is expected


@pytest.mark.parametrize(
    ("mode", "expected_effects"),
    [("timeout_before_effect", 0), ("timeout_after_effect", 1)],
)
def test_timeout_before_and_after_fake_effect_always_unknown(mode: str, expected_effects: int):
    fake = FakeMcpTransport(mode=mode)
    result = UnderstoryExecutorAdapter(transport=fake)("memory_add", {"content": "x"})
    assert result.outcome is WorkerOutcome.TIMEOUT
    assert fake.simulated_effects == expected_effects
    assert fake.exchange_count == 1


@pytest.mark.parametrize(
    ("mode", "expected_effects"),
    [("disconnect", 0), ("disconnect_after_effect", 1)],
)
def test_disconnect_always_unknown_without_retry(mode: str, expected_effects: int):
    fake = FakeMcpTransport(mode=mode)
    result = UnderstoryExecutorAdapter(transport=fake)("memory_update", {"instruction": "x"})
    assert result.outcome is WorkerOutcome.UNKNOWN
    assert fake.simulated_effects == expected_effects
    assert fake.exchange_count == 1


def test_partial_response_and_error_without_no_effect_proof_are_unknown():
    partial = FakeMcpTransport(mode="partial")
    failed = FakeMcpTransport(response_text="Mutation failed", is_error=True)
    assert UnderstoryExecutorAdapter(transport=partial)("memory_add", {"content": "x"}).outcome is WorkerOutcome.UNKNOWN
    assert UnderstoryExecutorAdapter(transport=failed)("memory_update", {"instruction": "x"}).outcome is WorkerOutcome.UNKNOWN
    assert partial.simulated_effects == 1
    assert partial.exchange_count == failed.exchange_count == 1


def test_mcp_protocol_adapter_uses_no_socket(monkeypatch: pytest.MonkeyPatch):
    def forbidden_socket(*args: object, **kwargs: object) -> None:
        raise AssertionError("socket creation forbidden")

    monkeypatch.setattr(socket, "socket", forbidden_socket)
    fake = FakeMcpTransport()
    result = UnderstoryExecutorAdapter(transport=fake)("memory_maintain", {})
    assert result.outcome is WorkerOutcome.SUCCEEDED
    assert fake.exchange_count == 1


def _enqueue(database: Path, operation: str, key: str, payload: dict) -> str:
    return EnqueueRepository(database).enqueue(
        source_principal="mcp-test",
        operation=operation,
        idempotency_key=key,
        payload=payload,
    ).job_id


def test_worker_unknown_blocks_queue_and_restart_never_reexecutes(tmp_path: Path):
    database = tmp_path / "worker.sqlite3"
    apply_migrations(database)
    first = _enqueue(database, "memory_add", "one", {"content": "one"})
    second = _enqueue(database, "memory_maintain", "two", {})
    fake = FakeMcpTransport(mode="timeout_after_effect")
    adapter = UnderstoryExecutorAdapter(transport=fake)

    assert LocalWorker(database, executor=adapter).run_until_idle() == WorkerRun(
        processed=1, stop_reason="unknown_blocks_queue"
    )
    assert fake.exchange_count == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT job_id, state, effect_certainty FROM jobs ORDER BY queue_seq"
        ).fetchall() == [
            (first, "unknown", "unknown"),
            (second, "queued", "none"),
        ]
        assert connection.execute(
            "SELECT event_type, from_state, to_state FROM job_events ORDER BY event_seq"
        ).fetchall()[-2:] == [
            ("worker_claimed", "queued", "running"),
            ("worker_uncertain", "running", "unknown"),
        ]

    assert LocalWorker(database, executor=adapter).run_until_idle() == WorkerRun(
        processed=0, stop_reason="unknown_blocks_queue"
    )
    assert fake.exchange_count == 1


def test_worker_audits_demonstrable_success(tmp_path: Path):
    database = tmp_path / "worker.sqlite3"
    apply_migrations(database)
    job_id = _enqueue(database, "memory_update", "success", {"instruction": "update"})
    fake = FakeMcpTransport(response_text="Updated\n\nFiles changed:\n- /fake/updated.md")

    assert LocalWorker(
        database, executor=UnderstoryExecutorAdapter(transport=fake)
    ).run_until_idle() == WorkerRun(processed=1, stop_reason="idle")
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT state, effect_certainty FROM jobs WHERE job_id=?", (job_id,)
        ).fetchone() == ("succeeded", "complete")
        assert connection.execute(
            "SELECT event_type FROM job_events ORDER BY event_seq"
        ).fetchall()[-1] == ("worker_succeeded",)
