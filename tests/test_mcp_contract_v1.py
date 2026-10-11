from __future__ import annotations

import ast
import json
import re
import socket
from pathlib import Path
from typing import Any

import pytest

from rendiv_api.mcp_contract_v1 import (
    ContractResult,
    ContractValidationError,
    classify_for_rendiv,
    unknown_disposition,
    validate_mcp_response,
    validate_structured_content,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_DOC = PROJECT_ROOT / "docs/design/06-UNDERSTORY-MCP-CONTRACT-V1.md"


def _contract_examples() -> list[dict[str, Any]]:
    text = CONTRACT_DOC.read_text()
    blocks = re.findall(r"```json\n(.*?)\n```", text, re.DOTALL)
    return [json.loads(block) for block in blocks]


def _evidence(
    *,
    execution: str = "completed",
    execution_path: str = "mutating",
    effect: str = "reported_applied",
    effect_scope: str = "reported_paths_only",
    read_back: str = "not_performed",
) -> dict[str, str]:
    return {
        "execution": execution,
        "execution_path": execution_path,
        "effect": effect,
        "effect_scope": effect_scope,
        "read_back": read_back,
        "atomicity": "not_asserted",
        "durability": "not_asserted",
    }


def _result(
    operation: str,
    *,
    outcome: str = "applied",
    request_id: str | int = "req-1",
    operation_id: str = "0199c0a4-6b3a-7f20-a019-fc6f1d2a8b11",
    changed_paths: list[str] | None = None,
    evidence: dict[str, str] | None = None,
    reason_code: str | None = None,
) -> dict[str, Any]:
    if evidence is None:
        if outcome == "applied":
            evidence = _evidence()
        elif outcome == "no_op":
            evidence = _evidence(
                execution_path="healthy_no_op",
                effect="reported_none",
                effect_scope="operation_scope",
            )
        elif outcome == "partial":
            evidence = _evidence(effect="reported_partial")
        elif outcome == "rejected_before_write":
            evidence = _evidence(
                execution="not_completed",
                execution_path="rejected_pre_write",
                effect="reported_none",
                effect_scope="operation_scope",
            )
        else:
            evidence = _evidence(
                execution="unknown",
                execution_path="unknown",
                effect="unknown",
                effect_scope="unknown",
                read_back="unknown",
            )
    result: dict[str, Any] = {
        "contract_version": "understory-mcp-result/1",
        "request_id": request_id,
        "operation_id": operation_id,
        "operation": operation,
        "outcome": outcome,
        "no_op": outcome == "no_op",
        "changed_paths": changed_paths if changed_paths is not None else ["concepts/a.md"],
        "evidence": evidence,
    }
    if outcome in {"partial", "rejected_before_write", "unknown"}:
        result["reason_code"] = reason_code or {
            "partial": "partial_effect",
            "rejected_before_write": "invalid_arguments",
            "unknown": "upstream_timeout",
        }[outcome]
    return result


def _mcp_response(
    structured: dict[str, Any],
    *,
    jsonrpc_id: str | int | None = None,
    is_error: bool = False,
    include_text: bool = True,
) -> str:
    result: dict[str, Any] = {"structuredContent": structured, "isError": is_error}
    if include_text:
        result["content"] = [{"type": "text", "text": "legacy display text is ignored"}]
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": structured["request_id"] if jsonrpc_id is None else jsonrpc_id,
            "result": result,
        }
    )


def _validate(value: dict[str, Any], *, request_id: str | int = "req-1", operation: str | None = None, is_error: bool = False) -> ContractResult:
    return validate_structured_content(
        value,
        expected_request_id=request_id,
        expected_operation=operation or value["operation"],
        jsonrpc_id=request_id,
        is_error=is_error,
    )


@pytest.mark.parametrize("example", _contract_examples())
def test_all_five_documented_json_examples_validate_and_stay_unknown(example: dict[str, Any]):
    response = _mcp_response(example)
    parsed = validate_mcp_response(
        response,
        expected_request_id=example["request_id"],
        expected_operation=example["operation"],
    )
    disposition = classify_for_rendiv(parsed)
    assert (disposition.job_state, disposition.effect_certainty) == ("unknown", "unknown")
    assert disposition.blocks_fifo is True
    assert disposition.automatic_retry is False


@pytest.mark.parametrize("operation", ["memory_add", "memory_update", "memory_maintain"])
def test_applied_report_for_each_operation_never_becomes_succeeded(operation: str):
    value = _result(operation)
    parsed = _validate(value)
    disposition = classify_for_rendiv(parsed)
    assert disposition.job_state != "succeeded"
    assert disposition.effect_certainty != "complete"
    assert disposition.blocks_fifo and not disposition.automatic_retry


@pytest.mark.parametrize("operation", ["memory_add", "memory_update"])
def test_no_op_for_add_or_update_is_rejected(operation: str):
    with pytest.raises(ContractValidationError):
        _validate(_result(operation, outcome="no_op", changed_paths=[]))


def test_maintain_no_op_is_valid_but_remains_unknown_until_all_gates_are_approved():
    parsed = _validate(_result("memory_maintain", outcome="no_op", changed_paths=[]))
    disposition = classify_for_rendiv(parsed)
    assert disposition.job_state == "unknown"
    assert disposition.effect_certainty == "unknown"
    assert disposition.blocks_fifo and not disposition.automatic_retry


@pytest.mark.parametrize("operation", ["memory_add", "memory_update", "memory_maintain"])
def test_rejected_before_write_does_not_become_failed_without_upstream_guarantee(operation: str):
    parsed = _validate(
        _result(operation, outcome="rejected_before_write", changed_paths=[])
    )
    disposition = classify_for_rendiv(parsed)
    assert disposition.job_state != "failed"
    assert disposition.effect_certainty != "none"
    assert disposition.blocks_fifo and not disposition.automatic_retry


@pytest.mark.parametrize("operation", ["memory_add", "memory_update", "memory_maintain"])
@pytest.mark.parametrize("outcome", ["partial", "unknown"])
def test_partial_and_unknown_for_every_operation_are_blocking(operation: str, outcome: str):
    parsed = _validate(_result(operation, outcome=outcome, changed_paths=[]))
    disposition = classify_for_rendiv(parsed)
    assert disposition.job_state == "unknown"
    assert disposition.effect_certainty == "unknown"
    assert disposition.blocks_fifo and not disposition.automatic_retry


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contract_version", "understory-mcp-result/2"),
        ("request_id", "different-request"),
        ("operation_id", "0199c0a4-6b3a-1f20-a019-fc6f1d2a8b11"),
        ("operation", "memory_update"),
        ("outcome", "success"),
        ("no_op", 1),
        ("changed_paths", "concepts/a.md"),
    ],
)
def test_root_field_mismatches_are_rejected(field: str, value: Any):
    item = _result("memory_add")
    item[field] = value
    with pytest.raises(ContractValidationError):
        _validate(item, operation="memory_add")


@pytest.mark.parametrize("field", ["contract_version", "request_id", "operation_id", "operation", "outcome", "no_op", "changed_paths", "evidence"])
def test_missing_required_root_field_is_rejected(field: str):
    item = _result("memory_add")
    del item[field]
    with pytest.raises(ContractValidationError):
        _validate(item, operation="memory_add")


def test_unknown_root_and_evidence_fields_are_rejected():
    item = _result("memory_add")
    item["extra"] = "ignored by nobody"
    with pytest.raises(ContractValidationError):
        _validate(item)
    item = _result("memory_add")
    item["evidence"]["extra"] = "unexpected"
    with pytest.raises(ContractValidationError):
        _validate(item)


@pytest.mark.parametrize(
    ("outcome", "reason_code"),
    [
        ("applied", "invalid_arguments"),
        ("no_op", "invalid_arguments"),
        ("unknown", None),
        ("unknown", "free-form secret-bearing detail"),
    ],
)
def test_reason_code_presence_and_allowlist_are_strict(outcome: str, reason_code: str | None):
    item = _result("memory_add", outcome=outcome, changed_paths=[])
    if reason_code is None:
        item.pop("reason_code", None)
    else:
        item["reason_code"] = reason_code
    with pytest.raises(ContractValidationError):
        _validate(item, operation="memory_add")


@pytest.mark.parametrize("request_id", [True, None, 1.0, 2**53, ""])
def test_request_id_requires_exact_supported_type_and_form(request_id: Any):
    item = _result("memory_add", request_id=request_id)
    with pytest.raises(ContractValidationError):
        validate_structured_content(
            item,
            expected_request_id=request_id,
            expected_operation="memory_add",
            jsonrpc_id=request_id,
        )


@pytest.mark.parametrize("request_id", [1, "1"])
def test_request_id_type_and_value_must_match_jsonrpc_id(request_id: str | int):
    item = _result("memory_add", request_id=request_id)
    wrong_type: str | int = 1 if isinstance(request_id, str) else "1"
    with pytest.raises(ContractValidationError):
        validate_structured_content(
            item,
            expected_request_id=request_id,
            expected_operation="memory_add",
            jsonrpc_id=wrong_type,
        )


@pytest.mark.parametrize(
    "path",
    ["/absolute.md", "C:/absolute.md", "../escape.md", "concepts/../escape.md", "concepts//a.md", "concepts/./a.md", "a\\b.md", "a\x00b.md", "a\nb.md", ""],
)
def test_unsafe_or_noncanonical_paths_are_rejected(path: str):
    item = _result("memory_add", changed_paths=[path])
    with pytest.raises(ContractValidationError):
        _validate(item)


def test_duplicate_or_unsorted_paths_are_rejected():
    for paths in (["concepts/a.md", "concepts/a.md"], ["concepts/z.md", "concepts/a.md"]):
        with pytest.raises(ContractValidationError):
            _validate(_result("memory_add", changed_paths=list(paths)))


@pytest.mark.parametrize(
    "bad_evidence",
    [
        _evidence(execution="not_completed"),
        _evidence(execution_path="healthy_no_op"),
        _evidence(effect="reported_partial"),
        _evidence(effect_scope="unknown"),
        _evidence(read_back="observed_mismatch"),
        {**_evidence(), "atomicity": "atomic"},
    ],
)
def test_applied_evidence_contradictions_are_rejected(bad_evidence: dict[str, str]):
    with pytest.raises(ContractValidationError):
        _validate(_result("memory_add", evidence=bad_evidence))


def test_rejected_example_requires_not_completed_and_prewrite_path():
    valid = _result("memory_add", outcome="rejected_before_write", changed_paths=[])
    assert _validate(valid).evidence.execution == "not_completed"
    invalid = _result(
        "memory_add",
        outcome="rejected_before_write",
        changed_paths=[],
        evidence=_evidence(
            execution="unknown",
            execution_path="rejected_pre_write",
            effect="reported_none",
            effect_scope="operation_scope",
        ),
    )
    with pytest.raises(ContractValidationError):
        _validate(invalid)


def test_duplicate_json_keys_are_rejected_at_root_and_nested_levels():
    duplicate_root = '{"contract_version":"understory-mcp-result/1","contract_version":"understory-mcp-result/1"}'
    duplicate_evidence = json.dumps(_result("memory_add"))[:-1] + ',"evidence":{"execution":"completed","execution":"unknown"}}'
    for raw in (duplicate_root, duplicate_evidence):
        with pytest.raises(ContractValidationError) as exc:
            validate_mcp_response(
                raw,
                expected_request_id="req-1",
                expected_operation="memory_add",
            )
        assert "duplicate_json_key" in str(exc.value)


def test_validator_errors_do_not_echo_payload_or_secret_like_content():
    secret_like = "SENTINEL-PRIVATE-CONTENT-DO-NOT-LOG"
    item = _result("memory_add")
    item["unexpected"] = secret_like
    with pytest.raises(ContractValidationError) as exc:
        _validate(item)
    assert secret_like not in str(exc.value)


def test_is_error_never_promotes_applied_and_rejected_remains_unknown():
    applied = _result("memory_add")
    with pytest.raises(ContractValidationError):
        validate_mcp_response(
            _mcp_response(applied, is_error=True),
            expected_request_id="req-1",
            expected_operation="memory_add",
        )
    rejected = _result("memory_add", outcome="rejected_before_write", changed_paths=[])
    parsed = validate_mcp_response(
        _mcp_response(rejected, is_error=True),
        expected_request_id="req-1",
        expected_operation="memory_add",
    )
    disposition = classify_for_rendiv(parsed)
    assert disposition.job_state == "unknown" and disposition.effect_certainty == "unknown"
    assert disposition.blocks_fifo and not disposition.automatic_retry


@pytest.mark.parametrize(
    "response",
    [
        '{"jsonrpc":"2.0","id":"req-1","result":{"content":[{"type":"text","text":"Files changed: - a.md"}]}}',
        '{"jsonrpc":"2.0","id":"req-1","error":{"code":-1,"message":"failed"}}',
        "",
        "not-json",
        "[{\"jsonrpc\":\"2.0\",\"id\":\"req-1\",\"result\":{}}]",
        '{"jsonrpc":"2.0","id":"req-1","error":{},"result":{}}',
        '{"jsonrpc":"2.0","id":"req-1","result":{}} {"jsonrpc":"2.0","id":"req-1","result":{}}',
    ],
)
def test_legacy_missing_invalid_and_ambiguous_responses_fail_closed(response: str):
    with pytest.raises(ContractValidationError):
        validate_mcp_response(
            response,
            expected_request_id="req-1",
            expected_operation="memory_add",
        )
    disposition = unknown_disposition()
    assert disposition.job_state == "unknown"
    assert disposition.effect_certainty == "unknown"
    assert disposition.blocks_fifo and not disposition.automatic_retry


def test_jsonrpc_id_and_expected_operation_must_match():
    item = _result("memory_add")
    with pytest.raises(ContractValidationError):
        validate_mcp_response(
            _mcp_response(item, jsonrpc_id="wrong"),
            expected_request_id="req-1",
            expected_operation="memory_add",
        )
    with pytest.raises(ContractValidationError):
        validate_mcp_response(
            _mcp_response(item),
            expected_request_id="req-1",
            expected_operation="memory_update",
        )


class FakeMcpTransport:
    def __init__(self, response: str | Exception):
        self.response = response
        self.calls = 0

    def exchange(self, _request: str) -> str:
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_fake_transport_timeout_disconnect_and_absence_never_retry_or_succeed():
    for error, reason in (
        (TimeoutError("simulated"), "timeout_or_disconnect"),
        (ConnectionError("simulated"), "timeout_or_disconnect"),
    ):
        transport = FakeMcpTransport(error)
        disposition = unknown_disposition(reason)
        assert transport.calls == 0
        assert disposition.job_state == "unknown"
        assert disposition.blocks_fifo and not disposition.automatic_retry
        # A caller makes one attempt; this validator layer has no retry loop.
        with pytest.raises(type(error)):
            transport.exchange("fake request")
        assert transport.calls == 1


def test_fake_fifo_policy_keeps_later_jobs_queued_after_unknown():
    first = _result("memory_add")
    parsed = _validate(first)
    disposition = classify_for_rendiv(parsed)
    fake_queue = ["first", "second"]
    executor_calls = 0
    attempted = fake_queue.pop(0)
    executor_calls += 1
    if disposition.blocks_fifo:
        # The policy leaves the rest queued and never invokes the same attempt again.
        blocked_queue = [attempted, *fake_queue]
    else:  # pragma: no cover - contract requires this branch to remain unreachable
        blocked_queue = fake_queue
    assert blocked_queue == ["first", "second"]
    assert executor_calls == 1
    assert disposition.automatic_retry is False


def test_validator_module_has_no_adapter_worker_or_network_imports():
    module_path = PROJECT_ROOT / "src/rendiv_api/mcp_contract_v1.py"
    tree = ast.parse(module_path.read_text())
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert not imported.intersection({"worker", "understory_adapter", "socket", "httpx", "requests"})


def test_validator_with_fake_response_does_not_open_sockets(monkeypatch: pytest.MonkeyPatch):
    def forbidden_socket(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("network access is forbidden in validator tests")

    monkeypatch.setattr(socket, "socket", forbidden_socket)
    example = _result("memory_maintain", outcome="no_op", changed_paths=[])
    transport = FakeMcpTransport(_mcp_response(example))
    parsed = validate_mcp_response(
        transport.exchange("in-memory request"),
        expected_request_id="req-1",
        expected_operation="memory_maintain",
    )
    assert classify_for_rendiv(parsed).job_state == "unknown"
    assert transport.calls == 1
