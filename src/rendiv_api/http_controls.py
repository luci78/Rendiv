"""Fail-closed HTTP authentication and bounded request body handling."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any

from pydantic import SecretStr
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from rendiv_api.rate_limit import SlidingWindowRateLimiter


_TOKEN = re.compile(rb"^[A-Za-z0-9._~-]{32,512}$")


def _error_body(code: str, message: str) -> bytes:
    return json.dumps({"error": code, "message": message}, separators=(",", ":")).encode()


async def _send_error(send: Send, status_code: int, code: str, message: str, headers: list[tuple[bytes, bytes]] | None = None) -> None:
    response_headers = [(b"content-type", b"application/json"), (b"content-length", str(len(_error_body(code, message))).encode())]
    if headers:
        response_headers.extend(headers)
    body = _error_body(code, message)
    # Rebuild content length from the exact body bytes.
    response_headers[1] = (b"content-length", str(len(body)).encode())
    await send({"type": "http.response.start", "status": status_code, "headers": response_headers})
    await send({"type": "http.response.body", "body": body})


class BearerAuthenticationMiddleware:
    """Derive an API principal from a configured bearer token before body parsing."""

    def __init__(self, app: ASGIApp, *, service_tokens: dict[str, SecretStr]) -> None:
        self.app = app
        self._tokens = tuple(
            (principal, token.get_secret_value().encode("ascii"))
            for principal, token in service_tokens.items()
        )

    def _principal(self, scope: Scope) -> str | None:
        values = [value for key, value in scope.get("headers", []) if key.lower() == b"authorization"]
        candidate = b""
        well_formed = len(values) == 1
        if well_formed:
            scheme, separator, candidate = values[0].partition(b" ")
            well_formed = (
                separator == b" "
                and scheme.lower() == b"bearer"
                and _TOKEN.fullmatch(candidate) is not None
            )
        # Hashing makes every comparison fixed-length; all configured entries are checked.
        candidate_digest = hashlib.sha256(candidate if well_formed else b"").digest()
        matched: str | None = None
        for principal, token in self._tokens:
            if hmac.compare_digest(candidate_digest, hashlib.sha256(token).digest()):
                matched = principal
        return matched if well_formed else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path != "/v1/jobs" and not path.startswith("/v1/jobs/"):
            await self.app(scope, receive, send)
            return
        principal = self._principal(scope)
        if principal is None:
            await _send_error(
                send,
                401,
                "unauthorized",
                "A valid bearer credential is required.",
                [(b"www-authenticate", b"Bearer")],
            )
            return
        scope.setdefault("state", {})["source_principal"] = principal
        await self.app(scope, receive, send)


class RequestRateLimitMiddleware:
    """Apply the per-principal API budget before parsing any request body."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: SlidingWindowRateLimiter,
        retry_after_seconds: int,
    ) -> None:
        self.app = app
        self.limiter = limiter
        self.retry_after_seconds = retry_after_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] == "http" and (
            path == "/v1/jobs" or path.startswith("/v1/jobs/")
        ):
            principal = scope.get("state", {}).get("source_principal")
            if isinstance(principal, str) and not self.limiter.allow(principal):
                await _send_error(
                    send,
                    429,
                    "rate_limited",
                    "The request rate limit has been reached.",
                    [(b"retry-after", str(self.retry_after_seconds).encode())],
                )
                return
        await self.app(scope, receive, send)


class RequestBodyLimitMiddleware:
    """Bound enqueue bodies before buffering and reject ambiguous JSON."""

    def __init__(self, app: ASGIApp, *, max_request_bytes: int) -> None:
        self.app = app
        self.max_request_bytes = max_request_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != "/v1/jobs" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return

        headers = scope.get("headers", [])
        lengths = [value for key, value in headers if key.lower() == b"content-length"]
        if len(lengths) > 1:
            await _send_error(send, 400, "invalid_request", "Request headers are invalid.")
            return
        if lengths:
            try:
                declared_length = int(lengths[0])
            except ValueError:
                await _send_error(send, 400, "invalid_request", "Request headers are invalid.")
                return
            if declared_length < 0:
                await _send_error(send, 400, "invalid_request", "Request headers are invalid.")
                return
            if declared_length > self.max_request_bytes:
                await _send_error(send, 413, "payload_too_large", "Request body exceeds the configured limit.")
                return

        media_types = [value.split(b";", 1)[0].strip().lower() for key, value in headers if key.lower() == b"content-type"]
        encodings = [value.strip().lower() for key, value in headers if key.lower() == b"content-encoding"]
        if len(media_types) != 1 or media_types[0] != b"application/json" or any(
            encoding not in (b"", b"identity") for encoding in encodings
        ):
            await _send_error(send, 400, "invalid_request", "A JSON request body is required.")
            return

        idem_headers = [value for key, value in headers if key.lower() == b"idempotency-key"]
        if len(idem_headers) > 1:
            await _send_error(send, 400, "invalid_request", "Request headers are invalid.")
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_request_bytes:
                await _send_error(send, 413, "payload_too_large", "Request body exceeds the configured limit.")
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        try:
            json.loads(bytes(body), object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_non_json_number)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            await _send_error(send, 400, "invalid_json", "Request body is not valid unambiguous JSON.")
            return

        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_non_json_number(value: str) -> None:
    raise ValueError("non-JSON numeric constant")
