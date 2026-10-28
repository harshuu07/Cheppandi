-- the FAQ text, stored once
CREATE TABLE IF NOT EXISTS faq_chunks (
    id SERIAL PRIMARY KEY,                -- auto numbered id
    source TEXT NOT NULL,                 -- which file the text came from
    chunk_text TEXT NOT NULL,             -- one policy line
    UNIQUE (source, chunk_text)           -- the same line is never stored twice
);

-- one vector per chunk per embedding model
CREATE TABLE IF NOT EXISTS faq_embeddings (
    chunk_id INT NOT NULL REFERENCES faq_chunks(id) ON DELETE CASCADE,  -- which chunk this vector belongs to
    model TEXT NOT NULL,                  -- which embedding model made this vector
    embedding vector(3072) NOT NULL,      -- the numbers, must match the model's output length
    PRIMARY KEY (chunk_id, model)         -- one vector per chunk per model
);