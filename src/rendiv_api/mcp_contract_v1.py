"""Strict offline validator for the proposed Understory MCP result contract V1.

This module is intentionally independent of the production adapter and worker.
It parses and validates protocol data only; it never performs transport or state
transitions. Its Rendiv disposition is fail-closed for every currently proposed
outcome until the corresponding architecture decisions are approved.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


class ContractValidationError(ValueError):
    """Safe, static validation error that never includes the rejected value."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"MCP V1 validation failed: {code}")


@dataclass(frozen=True)
class ContractEvidence:
    execution: str
    execution_path: str
    effect: str
    effect_scope: str
    read_back: str
    atomicity: str
    durability: str


@dataclass(frozen=True)
class ContractResult:
    contract_version: str
    request_id: str | int
    operation_id: str
    operation: str
    outcome: str
    no_op: bool
    changed_paths: tuple[str, ...]
    evidence: ContractEvidence
    reason_code: str | None
    is_error: bool


@dataclass(frozen=True)
class RendivDisposition:
    """Conservative policy result; this is not a DB/API state transition."""

    job_state: str
    effect_certainty: str
    reason_code: str
    blocks_fifo: bool
    automatic_retry: bool


_ROOT_REQUIRED = frozenset(
    {
        "contract_version",
        "request_id",
        "operation_id",
        "operation",
        "outcome",
        "no_op",
        "changed_paths",
        "evidence",
    }
)
_EVIDENCE_KEYS = frozenset(
    {
        "execution",
        "execution_path",
        "effect",
        "effect_scope",
        "read_back",
        "atomicity",
        "durability",
    }
)
_OPERATIONS = frozenset({"memory_add", "memory_update", "memory_maintain"})
_OUTCOMES = frozenset(
    {"applied", "no_op", "partial", "rejected_before_write", "unknown"}
)
_REASON_CODES = frozenset(
    {
        "invalid_arguments",
        "policy_rejected",
        "operation_failed",
        "partial_effect",
        "response_lost",
        "upstream_timeout",
        "transport_lost",
        "invalid_upstream_result",
        "unknown_internal",
    }
)
_OPERATION_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SAFE_JSON_INT = (1 << 53) - 1


def _fail(code: str) -> None:
    raise ContractValidationError(code)


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_json_key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    _fail("invalid_json_number")


def _parse_json(raw_json: str) -> Any:
    if type(raw_json) is not str:
        _fail("invalid_json_input")
    try:
        return json.loads(
            raw_json,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except ContractValidationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError):
        _fail("invalid_json")


def _validate_request_id(value: Any, *, field: str) -> str | int:
    if type(value) is str:
        if not value:
            _fail(f"invalid_{field}")
        return value
    if type(value) is int and -_SAFE_JSON_INT <= value <= _SAFE_JSON_INT:
        return value
    _fail(f"invalid_{field}")


def _validate_path(path: Any) -> str:
    if type(path) is not str or not path:
        _fail("invalid_changed_path")
    if (
        path.startswith("/")
        or re.match(r"^[A-Za-z]:", path)
        or "\\" in path
        or "\x00" in path
        or "\n" in path
        or "\r" in path
    ):
        _fail("invalid_changed_path")
    components = path.split("/")
    if any(component in {"", ".", ".."} for component in components):
        _fail("invalid_changed_path")
    return path


def _validate_evidence(value: Any, outcome: str, changed_paths: tuple[str, ...]) -> ContractEvidence:
    if type(value) is not dict or set(value) != _EVIDENCE_KEYS:
        _fail("invalid_evidence_fields")

    enums = {
        "execution": {"completed", "not_completed", "unknown"},
        "execution_path": {"mutating", "healthy_no_op", "rejected_pre_write", "unknown"},
        "effect": {"reported_applied", "reported_none", "reported_partial", "unknown"},
        "effect_scope": {"reported_paths_only", "operation_scope", "unknown"},
        "read_back": {"not_performed", "observed_match", "observed_mismatch", "unknown"},
        "atomicity": {"not_asserted"},
        "durability": {"not_asserted"},
    }
    for field, allowed in enums.items():
        item = value[field]
        if type(item) is not str or item not in allowed:
            _fail(f"invalid_evidence_{field}")

    execution = value["execution"]
    execution_path = value["execution_path"]
    effect = value["effect"]
    effect_scope = value["effect_scope"]
    read_back = value["read_back"]

    if outcome == "applied":
        if (execution, execution_path, effect) != ("completed", "mutating", "reported_applied"):
            _fail("contradictory_applied_evidence")
        if effect_scope not in {"reported_paths_only", "operation_scope"}:
            _fail("contradictory_applied_scope")
        if read_back == "observed_mismatch":
            _fail("contradictory_applied_read_back")
    elif outcome == "no_op":
        if (execution, execution_path, effect, effect_scope) != (
            "completed", "healthy_no_op", "reported_none", "operation_scope"
        ):
            _fail("contradictory_no_op_evidence")
        if changed_paths or read_back not in {"not_performed", "unknown"}:
            _fail("contradictory_no_op_observation")
    elif outcome == "partial":
        if effect != "reported_partial" or execution_path not in {"mutating", "unknown"}:
            _fail("contradictory_partial_evidence")
        if effect_scope not in {"reported_paths_only", "operation_scope", "unknown"}:
            _fail("contradictory_partial_scope")
    elif outcome == "rejected_before_write":
        if (execution, execution_path, effect, effect_scope) != (
            "not_completed", "rejected_pre_write", "reported_none", "operation_scope"
        ):
            _fail("contradictory_rejection_evidence")
        if changed_paths or read_back not in {"not_performed", "unknown"}:
            _fail("contradictory_rejection_observation")
    elif outcome == "unknown":
        if execution_path not in {"mutating", "unknown"}:
            _fail("contradictory_unknown_path")

    if effect == "reported_applied" and (execution, execution_path) != ("completed", "mutating"):
        _fail("contradictory_reported_applied")
    if effect == "reported_partial" and execution_path not in {"mutating", "unknown"}:
        _fail("contradictory_reported_partial")
    if execution_path == "healthy_no_op" and outcome != "no_op":
        _fail("contradictory_healthy_no_op")
    if execution_path == "rejected_pre_write" and outcome != "rejected_before_write":
        _fail("contradictory_rejected_path")
    if effect == "reported_none" and effect_scope == "operation_scope" and outcome not in {
        "no_op", "rejected_before_write"
    }:
        _fail("contradictory_no_effect_scope")

    return ContractEvidence(
        execution=execution,
        execution_path=execution_path,
        effect=effect,
        effect_scope=effect_scope,
        read_back=read_back,
        atomicity=value["atomicity"],
        durability=value["durability"],
    )


def validate_structured_content(
    value: dict[str, Any] | str,
    *,
    expected_request_id: str | int,
    expected_operation: str,
    jsonrpc_id: str | int,
    is_error: bool = False,
) -> ContractResult:
    """Validate a V1 object or raw structuredContent JSON string.

    Raw JSON is parsed with duplicate-key detection at all nesting levels. When
    `value` is already a Python dict, duplicate source keys cannot be detected;
    callers needing that guarantee must pass the original JSON text. This
    function validates protocol data only and does not infer effect or policy.
    """

    if type(value) is str:
        value = _parse_json(value)
    if type(value) is not dict:
        _fail("structured_content_not_object")
    if set(value) - (_ROOT_REQUIRED | {"reason_code"}):
        _fail("unknown_contract_field")
    if not _ROOT_REQUIRED.issubset(value):
        _fail("missing_contract_field")

    expected_id = _validate_request_id(expected_request_id, field="expected_request_id")
    request_id = _validate_request_id(value["request_id"], field="request_id")
    if type(request_id) is not type(expected_id) or request_id != expected_id:
        _fail("request_id_mismatch")
    rpc_id = _validate_request_id(jsonrpc_id, field="jsonrpc_id")
    if type(rpc_id) is not type(expected_id) or rpc_id != expected_id or rpc_id != request_id:
        _fail("jsonrpc_id_mismatch")

    if type(expected_operation) is not str or expected_operation not in _OPERATIONS:
        _fail("invalid_expected_operation")
    if type(value["contract_version"]) is not str or value["contract_version"] != "understory-mcp-result/1":
        _fail("unsupported_contract_version")
    operation = value["operation"]
    if type(operation) is not str or operation not in _OPERATIONS or operation != expected_operation:
        _fail("operation_mismatch")

    operation_id = value["operation_id"]
    if type(operation_id) is not str or not _OPERATION_ID_PATTERN.fullmatch(operation_id):
        _fail("invalid_operation_id")
    outcome = value["outcome"]
    if type(outcome) is not str or outcome not in _OUTCOMES:
        _fail("invalid_outcome")
    if outcome == "no_op" and operation != "memory_maintain":
        _fail("unsupported_operation_no_op")
    no_op = value["no_op"]
    if type(no_op) is not bool or no_op != (outcome == "no_op"):
        _fail("contradictory_no_op")

    paths_value = value["changed_paths"]
    if type(paths_value) is not list:
        _fail("invalid_changed_paths")
    paths = tuple(_validate_path(path) for path in paths_value)
    if paths != tuple(sorted(set(paths))):
        _fail("noncanonical_changed_paths")

    evidence = _validate_evidence(value["evidence"], outcome, paths)
    reason_code = value.get("reason_code")
    if outcome in {"partial", "rejected_before_write", "unknown"}:
        if type(reason_code) is not str or reason_code not in _REASON_CODES:
            _fail("invalid_reason_code")
    elif "reason_code" in value:
        _fail("unexpected_reason_code")

    if type(is_error) is not bool:
        _fail("invalid_mcp_is_error")
    if is_error and outcome != "rejected_before_write":
        _fail("contradictory_mcp_is_error")

    return ContractResult(
        contract_version="understory-mcp-result/1",
        request_id=request_id,
        operation_id=operation_id,
        operation=operation,
        outcome=outcome,
        no_op=no_op,
        changed_paths=paths,
        evidence=evidence,
        reason_code=reason_code,
        is_error=is_error,
    )


def validate_mcp_response(
    raw_json: str,
    *,
    expected_request_id: str | int,
    expected_operation: str,
) -> ContractResult:
    """Validate one raw JSON-RPC MCP response containing V1 structuredContent.

    Legacy text-only results, JSON-RPC errors, batches and duplicate response
    messages are rejected. Text `content` is intentionally ignored for effect
    classification. Unknown outer MCP metadata is ignored; V1 structuredContent
    itself is validated with an exact field allowlist.
    """

    response = _parse_json(raw_json)
    if type(response) is not dict or response.get("jsonrpc") != "2.0":
        _fail("invalid_jsonrpc_envelope")
    if "result" in response and "error" in response:
        _fail("contradictory_jsonrpc_response")
    if "error" in response:
        _fail("jsonrpc_error_without_v1_result")
    if "result" not in response or "id" not in response:
        _fail("incomplete_jsonrpc_response")
    rpc_id = _validate_request_id(response["id"], field="jsonrpc_id")
    expected_id = _validate_request_id(expected_request_id, field="expected_request_id")
    if type(rpc_id) is not type(expected_id) or rpc_id != expected_id:
        _fail("jsonrpc_id_mismatch")
    result = response["result"]
    if type(result) is not dict:
        _fail("invalid_mcp_tool_result")
    if "structuredContent" not in result:
        _fail("legacy_or_missing_structured_content")
    is_error = result.get("isError", False)
    if type(is_error) is not bool:
        _fail("invalid_mcp_is_error")
    return validate_structured_content(
        result["structuredContent"],
        expected_request_id=expected_id,
        expected_operation=expected_operation,
        jsonrpc_id=rpc_id,
        is_error=is_error,
    )


def unknown_disposition(reason_code: str = "invalid_upstream_result") -> RendivDisposition:
    """Return the only terminal policy currently allowed: uncertain and blocked."""

    allowed = {
        "reported_success_unverified",
        "partial_effect",
        "upstream_unknown",
        "no_op_unapproved",
        "no_effect_unproven",
        "invalid_upstream_result",
        "timeout_or_disconnect",
    }
    if reason_code not in allowed:
        reason_code = "invalid_upstream_result"
    return RendivDisposition(
        job_state="unknown",
        effect_certainty="unknown",
        reason_code=reason_code,
        blocks_fifo=True,
        automatic_retry=False,
    )


def classify_for_rendiv(result: ContractResult) -> RendivDisposition:
    """Apply present-day policy: every V1 outcome stays unknown and blocks."""

    reasons = {
        "applied": "reported_success_unverified",
        "partial": "partial_effect",
        "unknown": "upstream_unknown",
        "no_op": "no_op_unapproved",
        "rejected_before_write": "no_effect_unproven",
    }
    return unknown_disposition(reasons[result.outcome])
