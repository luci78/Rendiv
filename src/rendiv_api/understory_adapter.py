"""MCP tool protocol seam with an injected, non-network transport only.

Argument names and interpretation follow docs/design/03-UNDERSTORY-CONTRACT.md.
The JSON-RPC envelope is MCP framing; no HTTP or stdio client is implemented.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from rendiv_api.persistence import OPERATIONS
from rendiv_api.worker import ExecutionResult, WorkerOutcome


class AdapterInputError(ValueError):
    """The operation arguments do not match the documented tool schema."""


class Operation(StrEnum):
    MEMORY_ADD = "memory_add"
    MEMORY_UPDATE = "memory_update"
    MEMORY_MAINTAIN = "memory_maintain"


class EffectClassification(StrEnum):
    REPORTED_SUCCESS = "reported_success"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    TRANSPORT_ERROR = "transport_error"
    INVALID_RESPONSE = "invalid_response"


@dataclass(frozen=True)
class JobPayload:
    operation: Operation
    arguments: dict[str, Any]


@dataclass(frozen=True)
class DecodedMcpResponse:
    request_id: str
    text: str
    is_error: bool


class McpTransport(Protocol):
    """Injectable serialized-message exchange; no concrete network transport."""

    def exchange(self, serialized_request: str) -> str: ...


def validate_job(operation: str, payload: dict[str, Any]) -> JobPayload:
    """Validate only the three argument schemas documented for the MCP tools."""

    if not isinstance(operation, str) or operation not in OPERATIONS:
        raise AdapterInputError("operation is not in the documented allowlist")
    if not isinstance(payload, dict):
        raise AdapterInputError("arguments must be a JSON object")
    try:
        json.dumps(payload, allow_nan=False, ensure_ascii=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise AdapterInputError("arguments are not JSON-compatible") from exc

    allowed = {
        Operation.MEMORY_ADD: {"content", "suggested_path"},
        Operation.MEMORY_UPDATE: {"instruction"},
        Operation.MEMORY_MAINTAIN: set(),
    }[Operation(operation)]
    if set(payload) - allowed:
        raise AdapterInputError("arguments contain undocumented fields")
    required = {
        Operation.MEMORY_ADD: {"content"},
        Operation.MEMORY_UPDATE: {"instruction"},
        Operation.MEMORY_MAINTAIN: set(),
    }[Operation(operation)]
    if not required.issubset(payload):
        raise AdapterInputError("required tool arguments are missing")
    if any(not isinstance(payload[name], str) for name in required):
        raise AdapterInputError("required tool arguments must be strings")
    if "suggested_path" in payload and not isinstance(payload["suggested_path"], str):
        raise AdapterInputError("suggested_path must be a string")
    return JobPayload(Operation(operation), dict(payload))


def serialize_tool_call(request_id: str, job: JobPayload) -> str:
    """Serialize a standard MCP tools/call JSON-RPC request deterministically."""

    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": job.operation.value, "arguments": job.arguments},
        },
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def decode_tool_result(serialized_response: str, expected_id: str) -> DecodedMcpResponse:
    """Decode the MCP CallToolResult shape used by the documented handlers."""

    try:
        response = json.loads(serialized_response)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid JSON-RPC response") from exc
    if not isinstance(response, dict) or response.get("jsonrpc") != "2.0":
        raise ValueError("invalid JSON-RPC envelope")
    if not isinstance(response.get("id"), str) or response.get("id") != expected_id:
        raise ValueError("MCP response id does not match request")
    if "error" in response:
        raise ValueError("MCP returned a JSON-RPC error")
    result = response.get("result")
    if not isinstance(result, dict):
        raise ValueError("MCP result is missing")
    is_error = result.get("isError", False)
    content = result.get("content")
    if not isinstance(is_error, bool) or not isinstance(content, list) or len(content) != 1:
        raise ValueError("MCP tool result shape is invalid")
    item = content[0]
    if not isinstance(item, dict) or item.get("type") != "text" or not isinstance(
        item.get("text"), str
    ):
        raise ValueError("MCP tool result content is invalid")
    return DecodedMcpResponse(expected_id, item["text"], is_error)


def classify_effect(response: DecodedMcpResponse) -> EffectClassification:
    """Classify only outcomes supported by the observed response contract."""

    if response.is_error:
        # The source's failed outcome does not prove that no file was changed.
        return EffectClassification.UNKNOWN
    text = response.text
    if text.startswith("⚠ Partial mutation:"):
        return EffectClassification.UNKNOWN
    if "Files changed:\n" not in text:
        # Includes the healthy maintain no-op: worker has no successful no-op state.
        return EffectClassification.UNKNOWN
    changed = text.rsplit("Files changed:\n", 1)[1].strip()
    if not changed or changed == "- none":
        return EffectClassification.UNKNOWN
    if not all(line.startswith("- ") and len(line) > 2 for line in changed.splitlines()):
        return EffectClassification.UNKNOWN
    # This is an Understory report, not independent read-back or durable proof.
    return EffectClassification.REPORTED_SUCCESS


class UnderstoryExecutorAdapter:
    """Serialize a tool call, exchange through injection, and map to worker result."""

    def __init__(self, *, transport: McpTransport) -> None:
        if not callable(getattr(transport, "exchange", None)):
            raise TypeError("an MCP transport with exchange() must be injected")
        self._transport = transport

    def __call__(self, operation: str, payload: dict[str, Any]) -> ExecutionResult:
        job = validate_job(operation, payload)
        # JSON-RPC request correlation only; this is not job idempotency.
        request_id = str(uuid.uuid4())
        request = serialize_tool_call(request_id, job)
        try:
            serialized_response = self._transport.exchange(request)
        except TimeoutError:
            return self._worker_result(EffectClassification.TIMEOUT)
        except Exception:
            return self._worker_result(EffectClassification.TRANSPORT_ERROR)
        try:
            decoded = decode_tool_result(serialized_response, request_id)
        except (ValueError, TypeError):
            return self._worker_result(EffectClassification.INVALID_RESPONSE)
        classification = classify_effect(decoded)
        if (
            classification is EffectClassification.UNKNOWN
            and job.operation is Operation.MEMORY_MAINTAIN
            and not decoded.is_error
            and "Files changed:\n" not in decoded.text
        ):
            return ExecutionResult(
                WorkerOutcome.UNKNOWN,
                audit_reason_code="maintain_response_unverified",
            )
        return self._worker_result(classification)

    @staticmethod
    def _worker_result(classification: EffectClassification) -> ExecutionResult:
        if classification is EffectClassification.REPORTED_SUCCESS:
            return ExecutionResult(
                WorkerOutcome.UNKNOWN,
                audit_reason_code="reported_success_unverified",
            )
        if classification is EffectClassification.TIMEOUT:
            return ExecutionResult(WorkerOutcome.TIMEOUT)
        return ExecutionResult(WorkerOutcome.UNKNOWN)
