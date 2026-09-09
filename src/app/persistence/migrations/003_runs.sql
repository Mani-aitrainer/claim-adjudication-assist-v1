CREATE TABLE IF NOT EXISTS run_audit (
    run_id         TEXT PRIMARY KEY,
    document_id    TEXT,
    status         TEXT,
    decision_json  JSONB,
    total_cost_usd DOUBLE PRECISION,
    duration_ms    DOUBLE PRECISION,
    degraded       BOOLEAN,
    created_at     TIMESTAMPTZ DEFAULT now()
);
