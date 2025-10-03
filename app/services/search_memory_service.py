import hashlib
import json
import logging
import sys
import os
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID, uuid4

# Add project root to path for imports
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from app.vector_db.embed import get_embedding_model

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, text
from redis import Redis

from app.models.memory_models import Memory

logger = logging.getLogger(__name__)

class SearchMemoryService:
    def __init__(self, db: AsyncSession, redis: Optional[Redis] = None):
        self.db = db
        self.redis = redis
        self.embedding_model = get_embedding_model()

    async def search_memory(
        self,
        query: str,
        project_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        limit: int = 10,
        similarity_threshold: float = 0.5,
        top_k: int = 10,
        user_id: Optional[UUID] = None
    ) -> List[Dict]:
        """Search memories based on query using vector similarity."""
        try:
            if not query or not query.strip():
                raise ValueError("Query cannot be empty")
            query = query.strip()
            
            # Step 1: Check Cache (following diagram workflow)
            cached_results = await self._check_cache(query, project_id, tags, limit)
            if cached_results:
                logger.info("Returning cached search results")
                return cached_results
            
            # Step 2: Decide if semantic search is needed
            need_semantic = self._need_semantic_search(query)
            
            if need_semantic:
                # Generate embedding for the query
                query_embedding = await self.embedding_model.embed_text(query)
            
                # Perform vector search in the database
                vector_results = await self._vector_search(
                    query_embedding=query_embedding,
                    project_id=project_id,
                    tags=tags,
                    limit=limit,
                    similarity_threshold=similarity_threshold
                )
                
                # Also do keyword search for fusion
                keyword_results = await self.keyword_search(
                    keywords=query.split(),
                    project_id=project_id,
                    limit=limit
                )
                
                # Combine and rank results (Fusion)
                results = self._rank_results(vector_results, keyword_results, top_k=top_k)
            else:
                # Only keyword search for simple queries
                results = await self.keyword_search(
                    keywords=query.split(),
                    project_id=project_id,
                    limit=limit
                )
            
            # Cache results for future use
            await self._cache_results(results, query, project_id, tags, limit)

            return results
        except Exception as e:
            logger.error(f"Error searching memory: {e}")
            raise

    async def _vector_search(
        self,
        query_embedding: List[float],
        project_id: Optional[UUID],
        tags: Optional[List[str]],
        limit: int,
        similarity_threshold: float
    ) -> List[Dict]:
        """
        Perform vector similarity search in database using embeddings.
        
        Uses cosine similarity to find similar memories based on embeddings.
        Currently using ARRAY(Float) fallback - can be upgraded to pgvector later.
        """
        try:
            if not query_embedding:
                logger.warning("Query embedding is empty, skipping vector search")
                return []
            
            # Build base query
            query_conditions = []
            
            # Filter by project_id if specified
            if project_id:
                query_conditions.append(Memory.project_id == project_id)
            
            # Filter by tags if specified (array overlap)
            if tags:
                tag_conditions = []
                for tag in tags:
                    tag_conditions.append(func.array_to_string(Memory.tags, ',').like(f'%{tag}%'))
                query_conditions.append(or_(*tag_conditions))
            
            # Only search memories that have embeddings
            query_conditions.append(Memory.embedding.isnot(None))
            
            # Build query to get memories with embeddings
            base_query = select(Memory).where(and_(*query_conditions)) if query_conditions else select(Memory).where(Memory.embedding.isnot(None))
            
            # Execute query to get candidate memories
            result = await self.db.execute(base_query)
            memories = result.scalars().all()
            
            if not memories:
                logger.info("No memories with embeddings found for vector search")
                return []
            
            # Calculate similarities in Python (since we're using ARRAY fallback)
            similar_memories = []
            
            for memory in memories:
                if memory.embedding and len(memory.embedding) == len(query_embedding):
                    # Calculate cosine similarity
                    similarity = self._calculate_cosine_similarity(query_embedding, memory.embedding)
                    
                    if similarity >= similarity_threshold:
                        memory_dict = {
                            "id": str(memory.id),
                            "content": memory.content,
                            "summary": memory.summary,
                            "tags": memory.tags or [],
                            "project_id": str(memory.project_id),
                            "created_at": memory.created_at.isoformat(),
                            "score": float(similarity),
                            "search_type": "vector"
                        }
                        similar_memories.append(memory_dict)
            
            # Sort by similarity score (highest first)
            similar_memories.sort(key=lambda x: x["score"], reverse=True)
            
            # Limit results
            results = similar_memories[:limit]
            
            logger.info(f"Vector search found {len(results)} similar memories above threshold {similarity_threshold}")
            return results
            
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []
    
    def _calculate_cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """
        Calculate cosine similarity between two vectors.
        
        Cosine similarity = (A · B) / (||A|| * ||B||)
        Returns value between 0 and 1 (higher = more similar)
        """
        try:
            import math
            
            # Calculate dot product
            dot_product = sum(a * b for a, b in zip(vec1, vec2))
            
            # Calculate magnitudes
            magnitude1 = math.sqrt(sum(a * a for a in vec1))
            magnitude2 = math.sqrt(sum(b * b for b in vec2))
            
            # Avoid division by zero
            if magnitude1 == 0 or magnitude2 == 0:
                return 0.0
            
            # Calculate cosine similarity
            cosine_sim = dot_product / (magnitude1 * magnitude2)
            
            # Normalize to 0-1 range (cosine can be -1 to 1)
            normalized_sim = (cosine_sim + 1) / 2
            
            return normalized_sim
            
        except Exception as e:
            logger.error(f"Error calculating cosine similarity: {e}")
            return 0.0
    
    def _rank_results(self, vector_results: List[Dict], keyword_results: List[Dict], top_k: int = 10) -> List[Dict]:
        """
        Combine and rank results from vector and keyword search.
        
        Uses hybrid ranking:
        1. Boost results that appear in both searches
        2. Combine scores with weighted average
        3. Remove duplicates, keeping highest score
        """
        try:
            # Create combined results dictionary (memory_id -> result)
            combined_results = {}
            
            # Add vector results
            for result in vector_results:
                memory_id = result["id"]
                result["vector_score"] = result["score"]
                result["keyword_score"] = 0.0
                result["combined_score"] = result["score"] * 0.7  # Vector weight = 0.7
                combined_results[memory_id] = result
            
            # Add/update with keyword results
            for result in keyword_results:
                memory_id = result["id"]
                if memory_id in combined_results:
                    # Memory found in both searches - boost score
                    existing = combined_results[memory_id]
                    existing["keyword_score"] = result["score"]
                    existing["combined_score"] = (
                        existing["vector_score"] * 0.7 +  # Vector weight
                        result["score"] * 0.3 +           # Keyword weight  
                        0.2                               # Boost for appearing in both
                    )
                    existing["search_type"] = "hybrid"
                else:
                    # Keyword-only result
                    result["vector_score"] = 0.0
                    result["keyword_score"] = result["score"]
                    result["combined_score"] = result["score"] * 0.3  # Keyword weight = 0.3
                    combined_results[memory_id] = result
            
            # Convert to list and sort by combined score
            final_results = list(combined_results.values())
            final_results.sort(key=lambda x: x["combined_score"], reverse=True)
            
            # Update final scores and limit results
            ranked_results = []
            for i, result in enumerate(final_results[:top_k]):
                result["score"] = result["combined_score"]
                result["rank"] = i + 1
                # Clean up temporary score fields
                result.pop("vector_score", None)
                result.pop("keyword_score", None) 
                result.pop("combined_score", None)
                ranked_results.append(result)
            
            logger.info(f"Ranked {len(ranked_results)} combined results from {len(vector_results)} vector + {len(keyword_results)} keyword results")
            return ranked_results
            
        except Exception as e:
            logger.error(f"Error ranking results: {e}")
            # Fallback: just return vector results if ranking fails
            return vector_results[:top_k] if vector_results else keyword_results[:top_k]
    
    async def _check_cache(
        self, 
        query: str, 
        project_id: Optional[UUID], 
        tags: Optional[List[str]], 
        limit: int
    ) -> Optional[List[Dict]]:
        """Check if search results are cached."""
        if not self.redis:
            return None
            
        try:
            # Create cache key based on search parameters
            cache_params = {
                "query": query,
                "project_id": str(project_id) if project_id else None,
                "tags": sorted(tags) if tags else None,
                "limit": limit
            }
            cache_key = f"search:{hashlib.md5(json.dumps(cache_params, sort_keys=True).encode()).hexdigest()}"
            
            cached_data = self.redis.get(cache_key)
            if cached_data:
                return json.loads(cached_data)
            return None
        except Exception as e:
            logger.warning(f"Cache check failed: {e}")
            return None
    
    def _need_semantic_search(self, query: str) -> bool:
        """Decide if semantic search is needed based on query complexity."""
        # Simple heuristics for semantic search decision
        query_lower = query.lower()
        
        # Use semantic search for:
        # 1. Questions (contains question words)
        question_words = ['how', 'what', 'why', 'when', 'where', 'which', 'who']
        if any(word in query_lower for word in question_words):
            return True
            
        # 2. Complex phrases (more than 3 words)
        if len(query.split()) > 3:
            return True
            
        # 3. Conceptual terms
        conceptual_terms = ['pattern', 'approach', 'method', 'technique', 'strategy', 'concept']
        if any(term in query_lower for term in conceptual_terms):
            return True
            
        # Otherwise use keyword search
        return False
    
    async def _cache_results(
        self, 
        results: List[Dict], 
        query: str, 
        project_id: Optional[UUID], 
        tags: Optional[List[str]], 
        limit: int
    ):
        """Cache search results in Redis."""
        if not self.redis:
            return
        
        try:
            # Create same cache key as in _check_cache
            cache_params = {
                "query": query,
                "project_id": str(project_id) if project_id else None,
                "tags": sorted(tags) if tags else None,
                "limit": limit
            }
            cache_key = f"search:{hashlib.md5(json.dumps(cache_params, sort_keys=True).encode()).hexdigest()}"
            
            # Cache for 1 hour
            self.redis.setex(cache_key, 3600, json.dumps(results))
            logger.info(f"Cached search results with key: {cache_key}")
        except Exception as e:
            logger.warning(f"Failed to cache results: {e}")
    
    async def keyword_search(
        self,
        keywords: List[str],
        project_id: Optional[UUID] = None,
        limit: int = 10
    ) -> List[Dict]:
        """Search memories based on keywords."""
        try:
            if not keywords:
                raise ValueError("Keywords list cannot be empty")
            
            # Perform keyword search in the database
            results = await self._keyword_search_db(
                keywords=keywords,
                project_id=project_id,
                limit=limit
            )
            
            return results
        except Exception as e:
            logger.error(f"Error in keyword search: {e}")
            raise
    
    async def _keyword_search_db(
        self,
        keywords: List[str],
        project_id: Optional[UUID] = None,
        limit: int = 10
    ) -> List[Dict]:
        """
        Perform keyword search in database.
        
        Searches in these fields:
        1. content (main text) - using ILIKE for partial matches
        2. tags (array) - using ANY for array search  
        3. summary (optional summary text) - using ILIKE
        4. meta_data (JSONB) - using text search on JSON values
        """
        try:
            # Build search conditions for each keyword
            search_conditions = []
            
            for keyword in keywords:
                keyword_lower = f"%{keyword.lower()}%"
                
                # Search conditions for each field
                content_match = func.lower(Memory.content).like(keyword_lower)
                summary_match = func.lower(Memory.summary).like(keyword_lower) 
                tags_match = func.lower(func.array_to_string(Memory.tags, ' ')).like(keyword_lower)
                
                # Combine all field searches for this keyword
                keyword_condition = or_(
                    content_match,
                    summary_match, 
                    tags_match
                )
                search_conditions.append(keyword_condition)
            
            # Combine all keyword conditions (AND logic - all keywords must match)
            where_clause = and_(*search_conditions)
            
            # Add project filter if specified
            if project_id:
                where_clause = and_(where_clause, Memory.project_id == project_id)
            
            # Build final query
            query = (
                select(Memory)
                .where(where_clause)
                .order_by(Memory.created_at.desc())
                .limit(limit)
            )
            
            # Execute query
            result = await self.db.execute(query)
            memories = result.scalars().all()
            
            # Convert to dict format for consistency
            results = []
            for memory in memories:
                memory_dict = {
                    "id": str(memory.id),
                    "content": memory.content,
                    "summary": memory.summary,
                    "tags": memory.tags or [],
                    "project_id": str(memory.project_id),
                    "created_at": memory.created_at.isoformat(),
                    "score": 1.0,  # Keyword search gives binary relevance
                    "search_type": "keyword"
                }
                results.append(memory_dict)
            
            logger.info(f"Keyword search found {len(results)} results for keywords: {keywords}")
            return results
            
        except Exception as e:
            logger.error(f"Database keyword search failed: {e}")
            return []