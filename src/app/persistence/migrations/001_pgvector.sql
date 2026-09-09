CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS policy_chunks (
    id           BIGSERIAL PRIMARY KEY,
    domain       TEXT NOT NULL,
    doc_id       TEXT NOT NULL,
    clause_id    TEXT NOT NULL,
    page         INT,
    content      TEXT NOT NULL,
    content_hash TEXT UNIQUE NOT NULL,
    metadata     JSONB DEFAULT '{}',
    embedding    VECTOR(1536),
    created_at   TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_policy_chunks_embedding
    ON policy_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_policy_chunks_domain ON policy_chunks(domain);

CREATE TABLE IF NOT EXISTS policy_graph_edges (
    id         BIGSERIAL PRIMARY KEY,
    domain     TEXT NOT NULL,
    src        TEXT NOT NULL,
    src_type   TEXT NOT NULL,
    relation   TEXT NOT NULL,
    dst        TEXT NOT NULL,
    dst_type   TEXT NOT NULL,
    clause_id  TEXT,
    properties JSONB DEFAULT '{}'
);
