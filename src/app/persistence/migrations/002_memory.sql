CREATE TABLE IF NOT EXISTS long_term_memory (
    id             BIGSERIAL PRIMARY KEY,
    scope_key      TEXT NOT NULL,
    scope_value    TEXT NOT NULL,
    fact_type      TEXT NOT NULL,
    fact_json      JSONB NOT NULL,
    source_run_id  TEXT NOT NULL,
    created_at     TIMESTAMPTZ DEFAULT now(),
    expires_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_long_term_memory_scope
    ON long_term_memory(scope_key, scope_value);
