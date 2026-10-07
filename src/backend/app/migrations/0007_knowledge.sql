-- 0007: shared knowledge base for RAG (REQ-RAG-01..07). pgvector, exact cosine search (no ANN index:
-- the corpus is ~10 chunks; an index would add complexity without measurable benefit).
-- vector(1536) = dimension VERIFIED live for openai/text-embedding-3-small via OpenRouter (RAG-01).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE knowledge_documents (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id       text NOT NULL UNIQUE CHECK (source_id ~ '^[a-z0-9][a-z0-9-]{0,63}$'),
    title           text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
    reference       text NOT NULL CHECK (length(reference) BETWEEN 1 AND 200),   -- e.g. 02_support_policy.md
    path            text NOT NULL CHECK (length(path) BETWEEN 1 AND 300),
    content_sha256  text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),    -- exact source version
    embedding_model text NOT NULL CHECK (length(embedding_model) BETWEEN 1 AND 200),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER knowledge_documents_set_updated_at BEFORE UPDATE ON knowledge_documents
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE knowledge_chunks (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- Deleting a document (its file was removed) removes its chunks: no orphan evidence.
    document_id     bigint NOT NULL REFERENCES knowledge_documents (id) ON DELETE CASCADE,
    chunk_key       text NOT NULL UNIQUE CHECK (chunk_key ~ '^[a-z0-9][a-z0-9-]{0,63}#[a-z0-9-]{1,64}$'),
    ordinal         integer NOT NULL,
    section         text NOT NULL CHECK (length(section) BETWEEN 1 AND 200),
    content         text NOT NULL CHECK (length(content) BETWEEN 1 AND 4000),
    content_sha256  text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    -- Model that produced THIS vector: search refuses to mix vector spaces.
    embedding_model text NOT NULL CHECK (length(embedding_model) BETWEEN 1 AND 200),
    embedding       vector(1536) NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, ordinal)
);
CREATE TRIGGER knowledge_chunks_set_updated_at BEFORE UPDATE ON knowledge_chunks
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
