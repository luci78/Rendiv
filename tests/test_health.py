import asyncio
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from rendiv_api.app import create_app
from rendiv_api.config import Settings


def test_health_and_readiness_use_temporary_sqlite_only(tmp_path: Path):
    database = tmp_path / "rendiv-test.sqlite3"
    app = create_app(
        Settings(
            app_env="test",
            database_path=database,
            sqlite_busy_timeout_ms=1_000,
        )
    )

    async def check_health() -> None:
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                assert (await client.get("/healthz")).status_code == 200
                assert (await client.get("/healthz")).json() == {"status": "ok"}
                assert (await client.get("/readyz")).status_code == 200
                assert (await client.get("/readyz")).json() == {"status": "ready"}

    asyncio.run(check_health())

    assert database.is_file()


def test_readiness_fails_closed_for_unmanaged_database(tmp_path: Path):
    import sqlite3

    database = tmp_path / "unmanaged.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE unrelated (value TEXT)")
    connection.commit()
    connection.close()
    app = create_app(Settings(app_env="test", database_path=database))

    async def check_unready() -> None:
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                assert (await client.get("/healthz")).status_code == 200
                response = await client.get("/readyz")
                assert response.status_code == 503
                assert response.json() == {"status": "not_ready"}

    asyncio.run(check_unready())
