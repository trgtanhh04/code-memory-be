# pgvector Setup Guide

## Prerequisites

1. **Install pgvector package**:
```bash
pip install pgvector==0.2.4
```

2. **Enable pgvector extension in PostgreSQL database**:
```sql
-- Connect to your database and run:
CREATE EXTENSION IF NOT EXISTS vector;
```

## Setup Steps

### 1. Install Dependencies
```bash
cd e:\code-memory-be-github\code-memory-be
pip install -r requirements.txt
```

### 2. Enable pgvector in Database
Execute the SQL in `migrations/enable_pgvector.sql`:
```bash
# Option 1: Via psql
psql -h your-host -U your-user -d your-database -f migrations/enable_pgvector.sql

# Option 2: Via database management tool (pgAdmin, DBeaver, etc.)
# Just copy-paste the SQL content
```

### 3. Run Alembic Migration
```bash
# Generate migration (if needed)
alembic revision --autogenerate -m "Add pgvector support"

# Apply migration
alembic upgrade head
```

### 4. Verify Setup
```python
# Test script to verify pgvector is working
import asyncio
from app.db.connect_db import get_db_session
from app.services.vector_search_service import VectorSearchService

async def test_pgvector():
    async with get_db_session() as db:
        vector_service = VectorSearchService(db)
        success = await vector_service.create_embedding_index()
        print(f"pgvector setup: {'✅ Success' if success else '❌ Failed'}")

# Run test
asyncio.run(test_pgvector())
```

## Benefits of pgvector Integration

### ✅ **Performance Improvements**:
- **Native vector operations** in PostgreSQL
- **IVFFlat indexing** for fast similarity search
- **Cosine similarity** optimized queries

### ✅ **Simplified Architecture**:
- **Single database** for both relational and vector data
- **ACID transactions** for data consistency
- **No separate vector database** needed

### ✅ **Advanced Search Capabilities**:
- **Semantic similarity search** using embeddings
- **Hybrid search** (keyword + semantic)
- **Similar memory recommendations**

## Usage Examples

### Save Memory with Vector Embedding:
```python
# Automatic embedding generation and storage
memory = await save_service.save_memory(
    content="FastAPI authentication with JWT tokens",
    project_id=project_id,
    user_id=user_id,
    tags=["fastapi", "auth", "jwt"]
)
```

### Semantic Search:
```python
# Find similar memories using vector similarity
results = await vector_service.similarity_search(
    query="user authentication methods",
    project_id=project_id,
    limit=10,
    similarity_threshold=0.7
)

for memory, score in results:
    print(f"Score: {score:.3f} - {memory.content[:100]}...")
```

### Find Similar Memories:
```python
# Get memories similar to a specific memory
similar = await vector_service.find_similar_memories(
    memory_id=memory.id,
    project_id=project_id,
    limit=5
)
```

## Troubleshooting

### Common Issues:

1. **pgvector extension not found**:
```bash
# Install pgvector in PostgreSQL
# For Ubuntu/Debian:
sudo apt install postgresql-14-pgvector

# For macOS with Homebrew:
brew install pgvector
```

2. **Python package not found**:
```bash
pip install pgvector==0.2.4
```

3. **Migration fails**:
```bash
# Check if extension is enabled
SELECT * FROM pg_extension WHERE extname = 'vector';

# Enable manually if needed
CREATE EXTENSION IF NOT EXISTS vector;
```

## Performance Tips

1. **Choose optimal index parameters**:
```sql
-- For large datasets (>1M vectors)
CREATE INDEX ON memories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 1000);

-- For smaller datasets (<100K vectors)  
CREATE INDEX ON memories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

2. **Monitor query performance**:
```sql
EXPLAIN ANALYZE 
SELECT content, 1 - (embedding <=> '[0.1,0.2,...]') as similarity 
FROM memories 
ORDER BY embedding <=> '[0.1,0.2,...]' 
LIMIT 10;
```