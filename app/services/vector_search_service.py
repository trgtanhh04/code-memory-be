"""
Vector Search Service using pgvector
Handles similarity search operations for memory embeddings
"""
import logging
from typing import List, Tuple, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from app.models.memory_models import Memory
from app.vector_db.embed import get_embedding_model

logger = logging.getLogger(__name__)

class VectorSearchService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedding_model = get_embedding_model()

    async def similarity_search(
        self,
        query: str,
        project_id: UUID,
        limit: int = 10,
        similarity_threshold: float = 0.7
    ) -> List[Tuple[Memory, float]]:
        """
        Perform similarity search using pgvector cosine similarity
        
        Args:
            query: Search query text
            project_id: Project UUID to search within
            limit: Maximum number of results
            similarity_threshold: Minimum similarity score (0-1)
            
        Returns:
            List of (Memory, similarity_score) tuples
        """
        try:
            # Generate embedding for query
            query_embedding = await self.embedding_model.aembed_query(query)
            if not query_embedding:
                logger.warning("Failed to generate embedding for query")
                return []

            # Convert to string format for SQL
            embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
            
            # Perform similarity search using pgvector
            similarity_query = text("""
                SELECT 
                    memories.*,
                    1 - (embedding <=> :query_embedding) as similarity_score
                FROM memories 
                WHERE 
                    project_id = :project_id 
                    AND embedding IS NOT NULL
                    AND 1 - (embedding <=> :query_embedding) >= :threshold
                ORDER BY embedding <=> :query_embedding
                LIMIT :limit
            """)
            
            result = await self.db.execute(
                similarity_query,
                {
                    "query_embedding": embedding_str,
                    "project_id": str(project_id),
                    "threshold": similarity_threshold,
                    "limit": limit
                }
            )
            
            # Process results
            search_results = []
            for row in result:
                # Create Memory object from row
                memory = Memory(
                    id=row.id,
                    project_id=row.project_id,
                    content=row.content,
                    summary=row.summary,
                    tags=row.tags,
                    meta_data=row.meta_data,
                    embedding=row.embedding,
                    usage_count=row.usage_count,
                    last_accessed_at=row.last_accessed_at,
                    created_at=row.created_at,
                    updated_at=row.updated_at
                )
                similarity_score = float(row.similarity_score)
                search_results.append((memory, similarity_score))
            
            logger.info(f"Vector search found {len(search_results)} results for project {project_id}")
            return search_results
            
        except Exception as e:
            logger.error(f"Vector search failed: {str(e)}")
            return []

    async def find_similar_memories(
        self,
        memory_id: UUID,
        project_id: UUID,
        limit: int = 5
    ) -> List[Tuple[Memory, float]]:
        """
        Find memories similar to a given memory
        
        Args:
            memory_id: ID of the reference memory
            project_id: Project UUID to search within
            limit: Maximum number of results
            
        Returns:
            List of (Memory, similarity_score) tuples
        """
        try:
            # Get the reference memory's embedding
            memory_query = select(Memory).where(Memory.id == memory_id)
            result = await self.db.execute(memory_query)
            reference_memory = result.scalar_one_or_none()
            
            if not reference_memory or not reference_memory.embedding:
                logger.warning(f"Memory {memory_id} not found or has no embedding")
                return []
            
            # Convert embedding to string format
            embedding_str = '[' + ','.join(map(str, reference_memory.embedding)) + ']'
            
            # Find similar memories (excluding the reference memory itself)
            similarity_query = text("""
                SELECT 
                    memories.*,
                    1 - (embedding <=> :reference_embedding) as similarity_score
                FROM memories 
                WHERE 
                    project_id = :project_id 
                    AND id != :memory_id
                    AND embedding IS NOT NULL
                ORDER BY embedding <=> :reference_embedding
                LIMIT :limit
            """)
            
            result = await self.db.execute(
                similarity_query,
                {
                    "reference_embedding": embedding_str,
                    "project_id": str(project_id),
                    "memory_id": str(memory_id),
                    "limit": limit
                }
            )
            
            # Process results
            similar_memories = []
            for row in result:
                memory = Memory(
                    id=row.id,
                    project_id=row.project_id,
                    content=row.content,
                    summary=row.summary,
                    tags=row.tags,
                    meta_data=row.meta_data,
                    embedding=row.embedding,
                    usage_count=row.usage_count,
                    last_accessed_at=row.last_accessed_at,
                    created_at=row.created_at,
                    updated_at=row.updated_at
                )
                similarity_score = float(row.similarity_score)
                similar_memories.append((memory, similarity_score))
            
            logger.info(f"Found {len(similar_memories)} similar memories for {memory_id}")
            return similar_memories
            
        except Exception as e:
            logger.error(f"Similar memory search failed: {str(e)}")
            return []

    async def create_embedding_index(self) -> bool:
        """
        Create pgvector index for fast similarity search (768 dimensions)
        This should be called during database initialization
        """
        try:
            # Create IVFFlat index for cosine similarity (optimized for 768 dims)
            index_query = text("""
                CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_memories_embedding 
                ON memories USING ivfflat (embedding vector_cosine_ops) 
                WITH (lists = 100)
            """)
            await self.db.execute(index_query)
            await self.db.commit()
            
            logger.info("pgvector index created successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create pgvector index: {str(e)}")
            return False