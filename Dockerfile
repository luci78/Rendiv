ARG PYTHON_IMAGE=python:3.12.15-slim-bookworm

FROM ${PYTHON_IMAGE} AS dependencies

ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv "${VIRTUAL_ENV}"
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

WORKDIR /build
COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --no-deps -r requirements.lock \
    && pip check

FROM ${PYTHON_IMAGE} AS runtime

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:/usr/local/bin:/usr/bin:/bin" \
    PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp

RUN groupadd --gid 10001 rendiv \
    && useradd --uid 10001 --gid 10001 --home-dir /home/rendiv \
       --create-home --shell /usr/sbin/nologin rendiv \
    && install -d --owner=10001 --group=10001 /app /var/lib/rendiv

COPY --from=dependencies /opt/venv /opt/venv
COPY --chown=10001:10001 src/ /app/src/

WORKDIR /app
USER 10001:10001
EXPOSE 8080
STOPSIGNAL SIGTERM

CMD ["uvicorn", "rendiv_api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
