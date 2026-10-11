import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_dockerfile_is_multi_stage_pinned_and_non_root():
    dockerfile = _read("Dockerfile")
    lock = _read("requirements.lock")
    package_lines = [
        line.strip()
        for line in lock.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert dockerfile.count("\nFROM ") == 2
    assert "ARG PYTHON_IMAGE=python:3.12.15-slim-bookworm" in dockerfile
    assert "COPY requirements.lock ./requirements.lock" in dockerfile
    assert "pip install --no-cache-dir --no-deps -r requirements.lock" in dockerfile
    assert "pip check" in dockerfile
    assert "useradd --uid 10001 --gid 10001" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert '"--workers", "1"' in dockerfile
    assert package_lines
    assert all(re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+-]+", line) for line in package_lines)


def test_dockerignore_excludes_local_data_secrets_and_caches():
    ignored = _read(".dockerignore")
    required_patterns = (
        ".env",
        ".env.*",
        "*.secret",
        "*.secrets",
        "*.pem",
        "*.key",
        "*.db",
        "*.sqlite",
        "*.sqlite3",
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        "tests",
        "docs",
    )
    assert all(pattern in ignored.splitlines() for pattern in required_patterns)
    assert "requirements.lock" not in ignored.splitlines()
    assert "src" not in ignored.splitlines()


def test_compose_is_private_non_root_and_has_no_host_port_or_external_mounts():
    compose = _read("compose.yaml")
    forbidden = (
        "ports:",
        "/var/run/docker.sock",
        "network_mode: host",
        "privileged: true",
        "ai-stack",
        "pithagoras",
        "understory",
        "llama.cpp",
        "/bundle",
        "/workspaces",
        "host.docker.internal",
    )
    assert all(value not in compose.lower() for value in forbidden)
    assert compose.count("\n  rendiv-api:") == 1
    assert "user: \"10001:10001\"" in compose
    assert "read_only: true" in compose
    assert "cap_drop:" in compose and "      - ALL" in compose
    assert "no-new-privileges:true" in compose
    assert "internal: true" in compose
    assert "source: rendiv-data" in compose
    assert "target: /var/lib/rendiv" in compose
    assert "expose:" in compose and '      - "8080"' in compose
    assert "--workers" in compose and '      - "1"' in compose
    assert "healthcheck:" in compose and "/readyz" in compose
    assert "RENDIV_DATABASE_PATH: /var/lib/rendiv/rendiv.sqlite3" in compose


def test_production_configuration_requires_external_values_and_contains_no_credentials():
    compose = _read("compose.yaml")
    required = (
        "RENDIV_API_TOKENS_JSON",
        "RENDIV_SQLITE_BUSY_TIMEOUT_MS",
        "RENDIV_MAX_PAYLOAD_BYTES",
        "RENDIV_MAX_REQUEST_BYTES",
        "RENDIV_RATE_LIMIT_REQUESTS",
        "RENDIV_RATE_LIMIT_WINDOW_SECONDS",
        "RENDIV_BACKLOG_LIMIT",
        "RENDIV_DATA_VOLUME",
    )
    assert "RENDIV_APP_ENV: production" in compose
    for variable in required:
        assert f"${{{variable}:?" in compose
    assert "${RENDIV_API_TOKENS_JSON:?" in compose
    assert "${RENDIV_DATA_VOLUME:?" in compose
    assert re.search(r"Bearer\s+[A-Za-z0-9._~-]{32,}", compose) is None


def test_operational_documentation_marks_container_commands_as_instructions_only():
    development = _read("docs/DEVELOPMENT.md").lower()
    assert "etapa 4" in development
    assert "docker compose" in development
    assert "nu a fost executată" in development
    assert "rollback" in development
