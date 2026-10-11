"""Typed seam for a future Understory executor; this module has no transport.

The request shape below is Rendiv's internal job envelope, not an Understory
wire protocol. Only the operation allowlist is known; payload semantics remain
opaque until the real Understory contract is confirmed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from rendiv_api.persistence import OPERATIONS
from rendiv_api.worker import ExecutionResult, WorkerOutcome


class AdapterInputError(ValueError):
    """The worker job is outside Rendiv's confirmed generic contract."""


class TransportFailure(Exception):
    """A transport interruption whose remote effect cannot be established."""


class Operation(StrEnum):
    MEMORY_ADD = "memory_add"
    MEMORY_UPDATE = "memory_update"
    MEMORY_MAINTAIN = "memory_maintain"


class ResultClass(StrEnum):
    CONFIRMED_SUCCESS = "confirmed_success"
    CONFIRMED_NO_EFFECT = "confirmed_no_effect"
    UNCERTAIN = "uncertain"
    TIMEOUT = "timeout"
    TRANSPORT_ERROR = "transport_error"
    INVALID_RESPONSE = "invalid_response"


@dataclass(frozen=True)
class JobPayload:
    """Generic operation and JSON object stored by Rendiv, without semantics."""

    operation: Operation
    payload: dict[str, Any]


@dataclass(frozen=True)
class TransportRequest:
    """Internal injectable request. It does not specify network encoding."""

    operation: Operation
    payload: dict[str, Any]


@dataclass(frozen=True)
class TransportResponse:
    """Internal transport classification, not a presumed Understory response."""

    classification: ResultClass


class InjectedTransport(Protocol):
    """A caller supplied transport boundary; no concrete transport is provided."""

    def execute(self, request: TransportRequest) -> TransportResponse: ...


def validate_job(operation: str, payload: dict[str, Any]) -> JobPayload:
    """Validate allowlisted operation and generic JSON-object payload only."""

    if not isinstance(operation, str) or operation not in OPERATIONS:
        raise AdapterInputError("operation is not in Rendiv's confirmed allowlist")
    if not isinstance(payload, dict):
        raise AdapterInputError("payload must be a JSON object")
    try:
        json.dumps(payload, allow_nan=False, ensure_ascii=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise AdapterInputError("payload is not JSON-compatible") from exc
    return JobPayload(Operation(operation), payload)


class UnderstoryExecutorAdapter:
    """Adapt injected transport classifications to the Stage 6A worker API."""

    def __init__(self, *, transport: InjectedTransport) -> None:
        if not callable(getattr(transport, "execute", None)):
            raise TypeError("an injected transport with execute() is required")
        self._transport = transport

    def __call__(self, operation: str, payload: dict[str, Any]) -> ExecutionResult:
        job = validate_job(operation, payload)
        request = TransportRequest(job.operation, job.payload)
        try:
            response = self._transport.execute(request)
        except TimeoutError:
            # A timeout says nothing about whether the remote effect occurred.
            return ExecutionResult(WorkerOutcome.TIMEOUT)
        except TransportFailure:
            return ExecutionResult(WorkerOutcome.UNKNOWN)

        if not isinstance(response, TransportResponse) or not isinstance(
            response.classification, ResultClass
        ):
            return ExecutionResult(WorkerOutcome.UNKNOWN)
        if response.classification is ResultClass.CONFIRMED_SUCCESS:
            return ExecutionResult(WorkerOutcome.SUCCEEDED)
        if response.classification is ResultClass.CONFIRMED_NO_EFFECT:
            return ExecutionResult(WorkerOutcome.FAILED_NO_EFFECT)
        if response.classification is ResultClass.TIMEOUT:
            return ExecutionResult(WorkerOutcome.TIMEOUT)
        # Uncertain, interrupted, ambiguous, and invalid responses all fail closed.
        return ExecutionResult(WorkerOutcome.UNKNOWN)
