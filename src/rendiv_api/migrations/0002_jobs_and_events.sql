CREATE TABLE jobs (
  job_id            TEXT PRIMARY KEY CHECK (length(job_id) = 36),
  source_principal  TEXT NOT NULL CHECK (
    length(source_principal) BETWEEN 1 AND 128
    AND source_principal NOT GLOB '*[^A-Za-z0-9._:-]*'
  ),
  operation         TEXT NOT NULL CHECK (
    operation IN ('memory_add', 'memory_update', 'memory_maintain')
  ),
  idempotency_key   TEXT NOT NULL CHECK (
    length(idempotency_key) BETWEEN 1 AND 128
    AND idempotency_key NOT GLOB '*[^A-Za-z0-9._:-]*'
  ),
  payload_format    TEXT NOT NULL CHECK (payload_format = 'json-v1'),
  payload_json      TEXT NOT NULL,
  payload_sha256    BLOB NOT NULL CHECK (length(payload_sha256) = 32),
  state             TEXT NOT NULL CHECK (
    state IN ('queued', 'running', 'succeeded', 'failed', 'unknown')
  ),
  effect_certainty  TEXT NOT NULL CHECK (
    effect_certainty IN ('none', 'partial', 'complete', 'unknown')
  ),
  queue_seq         INTEGER NOT NULL UNIQUE CHECK (queue_seq > 0),
  created_at_ms     INTEGER NOT NULL CHECK (created_at_ms > 0),
  updated_at_ms     INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
  finished_at_ms    INTEGER,
  error_code        TEXT,
  UNIQUE (source_principal, operation, idempotency_key)
);

CREATE INDEX jobs_state_fifo ON jobs(state, queue_seq);
CREATE INDEX jobs_source_created ON jobs(source_principal, created_at_ms);

CREATE TABLE job_events (
  event_seq       INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id        TEXT NOT NULL UNIQUE CHECK (length(event_id) = 36),
  job_id          TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE RESTRICT,
  event_type      TEXT NOT NULL CHECK (length(event_type) BETWEEN 1 AND 64),
  from_state      TEXT CHECK (
    from_state IS NULL OR from_state IN ('queued', 'running', 'succeeded', 'failed', 'unknown')
  ),
  to_state        TEXT CHECK (
    to_state IS NULL OR to_state IN ('queued', 'running', 'succeeded', 'failed', 'unknown')
  ),
  actor_type      TEXT NOT NULL CHECK (
    actor_type IN ('caller', 'operator', 'recovery', 'system')
  ),
  actor_id        TEXT CHECK (actor_id IS NULL OR length(actor_id) <= 128),
  occurred_at_ms  INTEGER NOT NULL CHECK (occurred_at_ms > 0),
  reason_code     TEXT CHECK (reason_code IS NULL OR length(reason_code) <= 64),
  metadata_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX job_events_job_seq ON job_events(job_id, event_seq);

CREATE TRIGGER jobs_no_delete BEFORE DELETE ON jobs
BEGIN SELECT RAISE(ABORT, 'jobs are retained to preserve idempotency and FIFO sequence'); END;

CREATE TRIGGER job_events_no_update BEFORE UPDATE ON job_events
BEGIN SELECT RAISE(ABORT, 'job_events is append-only'); END;

CREATE TRIGGER job_events_no_delete BEFORE DELETE ON job_events
BEGIN SELECT RAISE(ABORT, 'job_events is append-only'); END;
