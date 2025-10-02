-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Test pgvector installation
SELECT * FROM pg_extension WHERE extname = 'vector';