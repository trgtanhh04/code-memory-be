import hashlib
import json
import logging
import sys
import os
import asyncio
import re
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

# Ranking and fusion weights (tune these)
VECTOR_WEIGHT = 0.7
KEYWORD_WEIGHT = 0.3
HYBRID_BOOST = 0.1
TAG_BOOST = 0.15
PHRASE_BOOST = 0.25

# Basic stopword list to reduce noisy keyword matches
STOPWORDS = {
    'the','is','in','at','which','on','and','a','an','how','do','i','to',
    'for','of','use','uses','using','with','that','this','it','be','are',
    'was','were','by','from','as','have','has','had','or','but'
}

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
            
            # Always attempt both vector and keyword search.
            # Try to generate an embedding for semantic search; if embedding
            # generation fails, _vector_search will return an empty list.
            try:
                if hasattr(self.embedding_model, "embed_text"):
                    maybe = self.embedding_model.embed_text(query)
                    if asyncio.iscoroutine(maybe):
                        query_embedding = await maybe
                    else:
                        query_embedding = await asyncio.to_thread(self.embedding_model.embed_text, query)
                elif hasattr(self.embedding_model, "embed_query"):
                    query_embedding = await asyncio.to_thread(self.embedding_model.embed_query, query)
                elif hasattr(self.embedding_model, "embed_documents"):
                    embeddings = await asyncio.to_thread(self.embedding_model.embed_documents, [query])
                    query_embedding = embeddings[0] if isinstance(embeddings, list) and embeddings else None
                else:
                    raise AttributeError("Embedding model has no recognized embed method")
            except Exception as e:
                logger.warning(f"Embedding failed, will still run keyword search: {e}")
                query_embedding = None

            # Run vector search (will be a no-op if query_embedding is None)
            vector_results = await self._vector_search(
                query_embedding=query_embedding,
                project_id=project_id,
                tags=tags,
                limit=limit,
                similarity_threshold=similarity_threshold
            )

            # Always run keyword search for fusion/ranking (pass full query for phrase boost)
            keyword_results = await self.keyword_search(
                keywords=query.split(),
                project_id=project_id,
                limit=limit,
                full_query=query
            )

            # Combine and rank results (Fusion) — pass request tags for tag-boost
            results = self._rank_results(vector_results, keyword_results, top_k=top_k, request_tags=tags)
            
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
                            "id": memory.id,
                            "content": memory.content,
                            "summary": memory.summary,
                            "tags": memory.tags or [],
                            "project_id": memory.project_id,
                            "created_at": memory.created_at,
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

            # Clamp to valid range in case of tiny floating-point overshoot
            normalized_sim = max(0.0, min(normalized_sim, 1.0))

            return normalized_sim
            
        except Exception as e:
            logger.error(f"Error calculating cosine similarity: {e}")
            return 0.0
    
    def _rank_results(self, vector_results: List[Dict], keyword_results: List[Dict], top_k: int = 10, request_tags: Optional[List[str]] = None) -> List[Dict]:
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
            
            # Normalize request tags
            req_tags_norm = [t.lower().strip() for t in (request_tags or [])]

            # Add vector results
            for result in vector_results:
                memory_id = result["id"]
                result["vector_score"] = result["score"]
                result["keyword_score"] = 0.0
                # start combined score with vector weight
                result["combined_score"] = result["score"] * VECTOR_WEIGHT
                combined_results[memory_id] = result
            
            # Add/update with keyword results
            for result in keyword_results:
                memory_id = result["id"]
                if memory_id in combined_results:
                    # Memory found in both searches - boost score
                    existing = combined_results[memory_id]
                    existing["keyword_score"] = result["score"]
                    existing["combined_score"] = (
                        existing["vector_score"] * VECTOR_WEIGHT +  # Vector weight
                        result["score"] * KEYWORD_WEIGHT +           # Keyword weight  
                        HYBRID_BOOST                                  # Boost for appearing in both
                    )
                    # Clamp combined score to 1.0
                    existing["combined_score"] = min(existing["combined_score"], 1.0)
                    existing["search_type"] = "hybrid"
                else:
                    # Keyword-only result
                    result["vector_score"] = 0.0
                    result["keyword_score"] = result["score"]
                    result["combined_score"] = result["score"] * KEYWORD_WEIGHT  # Keyword weight
                    result["combined_score"] = min(result["combined_score"], 1.0)
                    combined_results[memory_id] = result
            
            # Convert to list and sort by combined score
            final_results = list(combined_results.values())
            final_results.sort(key=lambda x: x["combined_score"], reverse=True)
            
            # Update final scores and limit results
            ranked_results = []
            # Apply tag-boosts: if any request tag appears in document tags, add TAG_BOOST
            for res in final_results:
                doc_tags = [t.lower().strip() for t in (res.get("tags") or [])]
                if any(rt in doc_tags or any(rt in dt for dt in doc_tags) for rt in req_tags_norm):
                    res["combined_score"] = min(res["combined_score"] + TAG_BOOST, 1.0)

            # Re-sort after applying tag boosts
            final_results.sort(key=lambda x: x["combined_score"], reverse=True)

            for i, result in enumerate(final_results[:top_k]):
                # Ensure returned score is clamped to [0.0, 1.0]
                result["score"] = float(max(0.0, min(result["combined_score"], 1.0)))
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
        limit: int = 10,
        full_query: Optional[str] = None,
    ) -> List[Dict]:
        try:
            if not keywords:
                raise ValueError("Keywords list cannot be empty")

            # Tokenize keywords and filter stopwords/short tokens
            token_segments: List[str] = []
            for kw in keywords:
                parts = re.findall(r"\w+", kw.lower() or "")
                token_segments.extend(parts)

            # remove duplicates, stopwords, and tokens shorter than 3 chars
            token_segments = [t for t in dict.fromkeys(token_segments) if t and t not in STOPWORDS and len(t) >= 3]
            if not token_segments:
                return []

            # Build DB conditions to match any token in content/summary/tags
            token_conditions = []
            for token in token_segments:
                token_like = f"%{token}%"
                content_match = func.lower(Memory.content).like(token_like)
                summary_match = func.lower(Memory.summary).like(token_like)
                tags_match = func.lower(func.array_to_string(Memory.tags, ' ')).like(token_like)
                token_conditions.append(or_(content_match, summary_match, tags_match))

            where_clause = or_(*token_conditions)
            if project_id:
                where_clause = and_(where_clause, Memory.project_id == project_id)

            fetch_limit = max(limit * 5, 50)
            query = (
                select(Memory)
                .where(where_clause)
                .order_by(Memory.created_at.desc())
                .limit(fetch_limit)
            )

            result = await self.db.execute(query)
            memories = result.scalars().all()

            candidates = []
            for memory in memories:
                combined = " ".join([
                    (memory.content or ""),
                    (memory.summary or ""),
                    " ".join(memory.tags or [])
                ]).lower()

                matched = 0
                for token in token_segments:
                    if token in combined:
                        matched += 1

                score = (matched / len(token_segments)) if token_segments else 0.0

                # Require a minimum number of matched tokens or minimum ratio
                min_matched_tokens = 2
                min_match_ratio = 0.25
                if matched < min_matched_tokens and score < min_match_ratio:
                    # skip weak matches
                    continue

                phrase_bonus = 0.0
                if full_query:
                    fq = full_query.lower().strip()
                    if fq and fq in combined:
                        phrase_bonus = PHRASE_BOOST

                final_score = min(score + phrase_bonus, 1.0)

                if score > 0:
                    memory_dict = {
                        "id": memory.id,
                        "content": memory.content,
                        "summary": memory.summary,
                        "tags": memory.tags or [],
                        "project_id": memory.project_id,
                        "created_at": memory.created_at,
                        "score": float(final_score),
                        "search_type": "keyword"
                    }
                    candidates.append(memory_dict)

            candidates.sort(key=lambda x: (x["score"], x["created_at"]), reverse=True)
            results = candidates[:limit]

            logger.info(f"Keyword search found {len(results)} ranked results for tokens: {token_segments}")
            return results
        except Exception as e:
            logger.error(f"Error in keyword search: {e}")
            return []
    
    async def _keyword_search_db(
        self,
        keywords: List[str],
        project_id: Optional[UUID] = None,
        limit: int = 10,
        full_query: Optional[str] = None,
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
            # Tokenize keywords into word segments (remove punctuation) so
            # 'Vue.js' => ['vue', 'js'] and a query isn't overly strict.
            token_segments: List[str] = []
            for kw in keywords:
                # extract word characters (letters, numbers, _)
                parts = re.findall(r"\w+", kw.lower() or "")
                token_segments.extend(parts)

            # remove empty and duplicate tokens
            token_segments = [t for t in dict.fromkeys(token_segments) if t]

            if not token_segments:
                return []

            # Build search conditions: match any token in any of the searchable fields
            token_conditions = []
            for token in token_segments:
                token_like = f"%{token}%"
                content_match = func.lower(Memory.content).like(token_like)
                summary_match = func.lower(Memory.summary).like(token_like)
                tags_match = func.lower(func.array_to_string(Memory.tags, ' ')).like(token_like)
                token_conditions.append(or_(content_match, summary_match, tags_match))

            # Combine token conditions with OR (any token match is sufficient)
            where_clause = or_(*token_conditions)
            
            # Add project filter if specified
            if project_id:
                where_clause = and_(where_clause, Memory.project_id == project_id)
            
            # Build final query - fetch more candidates than `limit` so we can
            # re-rank by token-match score locally. This reduces false positives.
            fetch_limit = max(limit * 5, 50)
            query = (
                select(Memory)
                .where(where_clause)
                .order_by(Memory.created_at.desc())
                .limit(fetch_limit)
            )
            
            # Execute query
            result = await self.db.execute(query)
            memories = result.scalars().all()
            
            # Score each candidate by token match ratio across content/summary/tags
            candidates = []
            for memory in memories:
                # Combine searchable fields
                combined = " ".join([
                    (memory.content or ""),
                    (memory.summary or ""),
                    " ".join(memory.tags or [])
                ]).lower()

                # Count matched tokens
                matched = 0
                for token in token_segments:
                    if token in combined:
                        matched += 1

                    score = (matched / len(token_segments)) if token_segments else 0.0

                    # Phrase boost: if the full query (lowercased) appears verbatim in the document
                    phrase_bonus = 0.0
                    if full_query:
                        fq = full_query.lower().strip()
                        if fq and fq in combined:
                            phrase_bonus = PHRASE_BOOST

                    final_score = min(score + phrase_bonus, 1.0)
                if score > 0:
                    memory_dict = {
                        "id": memory.id,
                        "content": memory.content,
                        "summary": memory.summary,
                        "tags": memory.tags or [],
                        "project_id": memory.project_id,
                        "created_at": memory.created_at,
                            "score": float(final_score),
                        "search_type": "keyword"
                    }
                    candidates.append(memory_dict)

            # Sort by computed score (desc) then recent
            candidates.sort(key=lambda x: (x["score"], x["created_at"]), reverse=True)

            results = candidates[:limit]

            logger.info(f"Keyword search found {len(results)} ranked results for tokens: {token_segments}")
            return results
            
        except Exception as e:
            logger.error(f"Database keyword search failed: {e}")
            return []