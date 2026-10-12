CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS gov_regulations (
    id SERIAL PRIMARY KEY,
    service_code VARCHAR(50) NOT NULL,
    title VARCHAR(255) NOT NULL,
    section VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1024),
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE gov_regulations ADD COLUMN IF NOT EXISTS fts_tokens tsvector 
GENERATED ALWAYS AS (to_tsvector('russian', title || ' ' || content)) STORED;

CREATE INDEX IF NOT EXISTS idx_regulations_fts ON gov_regulations USING GIN (fts_tokens);
CREATE INDEX IF NOT EXISTS idx_regulations_embedding_hnsw ON gov_regulations USING hnsw (embedding vector_cosine_ops);