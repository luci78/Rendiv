import asyncio
import json
import secrets
import socket
import sqlite3
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from rendiv_api.app import create_app
from rendiv_api.config import Settings


def _new_app(database: Path, **overrides):
    tokens = {
        "caller-a": secrets.token_urlsafe(32),
        "caller-b": secrets.token_urlsafe(32),
    }
    values = {
        "app_env": "test",
        "database_path": database,
        "service_tokens": {name: SecretStr(token) for name, token in tokens.items()},
        "rate_limit_requests": 100,
        **overrides,
    }
    return create_app(Settings(**values)), tokens


def _api_call(app, callback):
    async def run():
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://rendiv.test",
            ) as client:
                return await callback(client)

    return asyncio.run(run())


def _headers(token: str, key: str = "request-1"):
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": key}


def _body(payload=None):
    return {"operation": "memory_add", "payload": {"value": "sample"} if payload is None else payload}


def test_authentication_is_required_before_request_validation(tmp_path: Path):
    app, tokens = _new_app(tmp_path / "api.sqlite3")

    async def call(client):
        missing = await client.post("/v1/jobs", json={"not": "valid"})
        invalid = await client.post(
            "/v1/jobs", json=_body(), headers={"Authorization": "Bearer invalid-token"}
        )
        good = await client.post(
            "/v1/jobs", json=_body(), headers=_headers(tokens["caller-a"])
        )
        return missing, invalid, good

    missing, invalid, good = _api_call(app, call)
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert invalid.status_code == 401
    assert good.status_code == 202


def test_enqueue_replay_and_conflict_are_authenticated_and_atomic(tmp_path: Path):
    app, tokens = _new_app(tmp_path / "api.sqlite3")

    async def call(client):
        first = await client.post("/v1/jobs", json=_body(), headers=_headers(tokens["caller-a"], "same"))
        replay = await client.post("/v1/jobs", json=_body(), headers=_headers(tokens["caller-a"], "same"))
        conflict = await client.post(
            "/v1/jobs", json=_body({"value": "different"}), headers=_headers(tokens["caller-a"], "same")
        )
        return first, replay, conflict

    first, replay, conflict = _api_call(app, call)
    assert first.status_code == replay.status_code == 202
    assert first.json()["job_id"] == replay.json()["job_id"]
    assert first.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert conflict.status_code == 409
    with sqlite3.connect(tmp_path / "api.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM job_events").fetchone()[0] == 1


def test_status_is_scoped_and_never_returns_payload_or_secrets(tmp_path: Path):
    app, tokens = _new_app(tmp_path / "api.sqlite3")

    async def call(client):
        created = await client.post(
            "/v1/jobs", json=_body({"private_content": "do-not-return"}),
            headers=_headers(tokens["caller-a"], "private-key"),
        )
        job_id = created.json()["job_id"]
        own = await client.get(f"/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {tokens['caller-a']}"})
        other = await client.get(f"/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {tokens['caller-b']}"})
        return created, own, other

    created, own, other = _api_call(app, call)
    assert own.status_code == 200
    assert own.json()["state"] == "queued"
    assert own.json()["effect_certainty"] == "none"
    assert other.status_code == 404
    serialized = json.dumps({"create": created.json(), "status": own.json()})
    for sensitive in ("do-not-return", "private-key", "caller-a", tokens["caller-a"], "payload_sha256"):
        assert sensitive not in serialized


def test_missing_idempotency_and_strict_body_validation(tmp_path: Path):
    app, tokens = _new_app(tmp_path / "api.sqlite3")

    async def call(client):
        auth = {"Authorization": f"Bearer {tokens['caller-a']}"}
        missing_key = await client.post("/v1/jobs", json=_body(), headers=auth)
        extra = await client.post(
            "/v1/jobs", json={**_body(), "source_principal": "forged"},
            headers=_headers(tokens["caller-a"]),
        )
        unknown_operation = await client.post(
            "/v1/jobs", json={"operation": "other", "payload": {}},
            headers=_headers(tokens["caller-a"], "invalid-op"),
        )
        malformed = await client.post(
            "/v1/jobs", content=b'{"operation":',
            headers={**_headers(tokens["caller-a"], "bad-json"), "Content-Type": "application/json"},
        )
        return missing_key, extra, unknown_operation, malformed

    missing_key, extra, unknown_operation, malformed = _api_call(app, call)
    assert missing_key.status_code == 422
    assert extra.status_code == unknown_operation.status_code == 422
    assert malformed.status_code == 400
    for response in (missing_key, extra, unknown_operation, malformed):
        assert "forged" not in response.text


def test_payload_and_request_size_limits_return_413(tmp_path: Path):
    app, tokens = _new_app(tmp_path / "api.sqlite3")

    async def call(client):
        payload_too_large = await client.post(
            "/v1/jobs", json=_body({"text": "x" * (262_144 + 1)}),
            headers=_headers(tokens["caller-a"], "large-payload"),
        )
        request_too_large = await client.post(
            "/v1/jobs", content=b" " * (278_528 + 1),
            headers={**_headers(tokens["caller-a"], "large-body"), "Content-Type": "application/json"},
        )
        return payload_too_large, request_too_large

    payload_too_large, request_too_large = _api_call(app, call)
    assert payload_too_large.status_code == 413
    assert request_too_large.status_code == 413


def test_backlog_and_request_rate_limits_fail_closed(tmp_path: Path):
    backlog_app, backlog_tokens = _new_app(tmp_path / "backlog.sqlite3", backlog_limit=1)

    async def backlog_call(client):
        first = await client.post("/v1/jobs", json=_body(), headers=_headers(backlog_tokens["caller-a"], "first"))
        second = await client.post("/v1/jobs", json=_body(), headers=_headers(backlog_tokens["caller-a"], "second"))
        return first, second

    first, second = _api_call(backlog_app, backlog_call)
    assert first.status_code == 202
    assert second.status_code == 429

    rate_app, rate_tokens = _new_app(
        tmp_path / "rate.sqlite3", rate_limit_requests=1, rate_limit_window_seconds=60
    )

    async def rate_call(client):
        first = await client.post("/v1/jobs", json=_body(), headers=_headers(rate_tokens["caller-a"], "first"))
        second = await client.post("/v1/jobs", json=_body(), headers=_headers(rate_tokens["caller-a"], "second"))
        return first, second

    limited, rate_limited = _api_call(rate_app, rate_call)
    assert limited.status_code == 202
    assert rate_limited.status_code == 429
    assert rate_limited.headers["retry-after"] == "60"


def test_database_unavailable_blocks_enqueue_and_status(tmp_path: Path):
    missing_parent_database = tmp_path / "missing" / "rendiv.sqlite3"
    app, tokens = _new_app(missing_parent_database)

    async def call(client):
        enqueue = await client.post("/v1/jobs", json=_body(), headers=_headers(tokens["caller-a"]))
        ready = await client.get("/readyz")
        return enqueue, ready

    enqueue, ready = _api_call(app, call)
    assert enqueue.status_code == ready.status_code == 503
    assert not missing_parent_database.exists()


def test_schema_failure_blocks_authenticated_enqueue(tmp_path: Path):
    database = tmp_path / "unmanaged.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
    app, tokens = _new_app(database)

    async def call(client):
        enqueue = await client.post("/v1/jobs", json=_body(), headers=_headers(tokens["caller-a"]))
        ready = await client.get("/readyz")
        return enqueue, ready

    enqueue, ready = _api_call(app, call)
    assert enqueue.status_code == ready.status_code == 503
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
            ("unrelated",)
        ]


def test_concurrent_identical_requests_create_one_job(tmp_path: Path):
    app, tokens = _new_app(tmp_path / "api.sqlite3", rate_limit_requests=50)

    async def call(client):
        responses = await asyncio.gather(*[
            client.post("/v1/jobs", json=_body(), headers=_headers(tokens["caller-a"], "concurrent"))
            for _ in range(12)
        ])
        return responses

    responses = _api_call(app, call)
    assert all(response.status_code == 202 for response in responses)
    assert len({response.json()["job_id"] for response in responses}) == 1
    with sqlite3.connect(tmp_path / "api.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM job_events").fetchone()[0] == 1


def test_backlog_limit_is_atomic_under_concurrent_enqueue(tmp_path: Path):
    app, tokens = _new_app(tmp_path / "backlog.sqlite3", rate_limit_requests=50, backlog_limit=1)

    async def call(client):
        return await asyncio.gather(*[
            client.post(
                "/v1/jobs", json=_body({"index": index}),
                headers=_headers(tokens["caller-a"], f"concurrent-{index}"),
            )
            for index in range(8)
        ])

    responses = _api_call(app, call)
    assert sum(response.status_code == 202 for response in responses) == 1
    assert sum(response.status_code == 429 for response in responses) == 7
    with sqlite3.connect(tmp_path / "backlog.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM job_events").fetchone()[0] == 1


def test_api_enqueue_makes_no_external_socket_calls(tmp_path: Path, monkeypatch):
    app, tokens = _new_app(tmp_path / "api.sqlite3")

    def forbidden_connect(*_args, **_kwargs):
        raise AssertionError("unexpected external socket connection")

    monkeypatch.setattr(socket.socket, "connect", forbidden_connect)

    async def call(client):
        return await client.post("/v1/jobs", json=_body(), headers=_headers(tokens["caller-a"]))

    response = _api_call(app, call)
    assert response.status_code == 202


def test_unexpected_internal_error_is_redacted(tmp_path: Path, monkeypatch):
    import rendiv_api.app as app_module

    original = app_module.EnqueueRepository.enqueue

    def fail_with_sensitive_detail(*_args, **_kwargs):
        raise RuntimeError("internal-secret-detail")

    monkeypatch.setattr(app_module.EnqueueRepository, "enqueue", fail_with_sensitive_detail)
    app, tokens = _new_app(tmp_path / "api.sqlite3")

    async def call(client):
        return await client.post("/v1/jobs", json=_body(), headers=_headers(tokens["caller-a"]))

    response = _api_call(app, call)
    assert response.status_code == 500
    assert response.json() == {
        "error": "internal_error",
        "message": "The request could not be completed.",
    }
    assert "internal-secret-detail" not in response.text
    monkeypatch.setattr(app_module.EnqueueRepository, "enqueue", original)
