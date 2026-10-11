CREATE TABLE schema_migrations (
  version       INTEGER PRIMARY KEY,
  name          TEXT NOT NULL UNIQUE,
  checksum      TEXT NOT NULL CHECK (length(checksum) = 64),
  applied_at_utc TEXT NOT NULL
);
