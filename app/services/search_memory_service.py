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
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, text
from redis import Redis
from app.vector_db.embed import get_embedding_model
from app.models.memory_models import Memory
from collections import Counter


project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

logger = logging.getLogger(__name__)

VECTOR_WEIGHT = 0.7
KEYWORD_WEIGHT = 0.3
HYBRID_BOOST = 0.1
TAG_BOOST = 0.15
PHRASE_BOOST = 0.25

STOPWORDS = {
    'the', 'is', 'in', 'at', 'which', 'on', 'and', 'a', 'an', 'how', 'do', 'i', 'to',
    'for', 'of', 'use', 'uses', 'using', 'with', 'that', 'this', 'it', 'be', 'are',
    'was', 'were', 'by', 'from', 'as', 'have', 'has', 'had', 'or', 'but'
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
        try:

            try:
                await self.db.rollback()
            except Exception:
                logger.debug("Initial rollback (cleanup) failed or no active transaction")

            if not query or not query.strip():
                raise ValueError("Query cannot be empty")
            query = query.strip()

            # Bước 1: Kiểm tra Cache
            cached_results = await self._check_cache(query, project_id, tags, limit)
            if cached_results:
                logger.info("Returning cached search results")
                return cached_results

            # Bước 2: Tìm kiếm theo vector và từ khóa
            query_embedding = await self._generate_query_embedding(query)
            vector_results = await self._vector_search(
                query_embedding=query_embedding,
                project_id=project_id,
                tags=tags,
                limit=limit,
                similarity_threshold=similarity_threshold
            )
            keyword_results = await self.keyword_search(
                keywords=query.split(),
                project_id=project_id,
                limit=limit,
                full_query=query
            )

            # Bước 3: Kết hợp và xếp hạng kết quả
            results = self._rank_results(vector_results, keyword_results, top_k=top_k, request_tags=tags)

            # Bước 4: Cache kết quả
            await self._cache_results(results, query, project_id, tags, limit)

            return results
        except Exception as e:
            logger.error(f"Error searching memory: {e}")
            raise

    async def _generate_query_embedding(self, query: str) -> Optional[List[float]]:
        try:
            if hasattr(self.embedding_model, "embed_text"):
                maybe = self.embedding_model.embed_text(query)
                if asyncio.iscoroutine(maybe):
                    return await maybe
                return await asyncio.to_thread(self.embedding_model.embed_text, query)
            elif hasattr(self.embedding_model, "embed_query"):
                return await asyncio.to_thread(self.embedding_model.embed_query, query)
            elif hasattr(self.embedding_model, "embed_documents"):
                embeddings = await asyncio.to_thread(self.embedding_model.embed_documents, [query])
                return embeddings[0] if isinstance(embeddings, list) and embeddings else None
            else:
                raise AttributeError("Embedding model has no recognized embed method")
        except Exception as e:
            logger.warning(f"Embedding failed, will still run keyword search: {e}")
            return None

    async def _vector_search(
        self,
        query_embedding: List[float],
        project_id: Optional[UUID],
        tags: Optional[List[str]],
        limit: int,
        similarity_threshold: float
    ) -> List[Dict]:
        try:
            if not query_embedding:
                logger.warning("Query embedding is empty, skipping vector search")
                return []
            try:
                ann_results = await self._vector_search_ann(query_embedding, project_id, tags, limit, similarity_threshold)
                if ann_results is not None:
                    return ann_results
            except Exception as e:
                logger.debug(f"ANN DB search failed or not supported, falling back: {e}")

            base_query = self._build_vector_query(project_id, tags)
            try:
                result = await self.db.execute(base_query)
            except Exception as e:
                logger.error(f"DB error during vector candidates fetch: {e}")
                try:
                    await self.db.rollback()
                except Exception:
                    logger.debug("Rollback failed or not applicable")
                return []
            memories = result.scalars().all()

            if not memories:
                logger.info("No memories with embeddings found for vector search")
                return []

            # Tính toán độ tương đồng
            return self._calculate_similarity(memories, query_embedding, similarity_threshold, limit)
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

    async def _vector_search_ann(
        self,
        query_embedding: List[float],
        project_id: Optional[UUID],
        tags: Optional[List[str]],
        limit: int,
        similarity_threshold: float,
    ) -> Optional[List[Dict]]:
        try:
            if not query_embedding:
                return []

            vec_literal = '[' + ','.join(str(float(x)) for x in query_embedding) + ']'

            where_clauses = ["embedding IS NOT NULL"]
            params = {"q": vec_literal, "limit": limit}

            if project_id:
                where_clauses.append("project_id = :project_id")
                params["project_id"] = str(project_id)

            if tags:
                tag_conds = []
                for i, t in enumerate(tags):
                    key = f"tag{i}"
                    tag_conds.append(f"array_to_string(tags, ',') ILIKE :{key}")
                    params[key] = f"%{t}%"
                where_clauses.append("(" + " OR ".join(tag_conds) + ")")

            where_sql = " AND ".join(where_clauses)

            sql = (
                "SELECT id, content, summary, tags, project_id, created_at, embedding <-> :q::vector AS distance "
                f"FROM memories WHERE {where_sql} ORDER BY distance ASC LIMIT :limit"
            )

            result = await self.db.execute(text(sql), params)
            rows = result.mappings().all()

            results = []
            for row in rows:
                dist = row.get("distance")
                try:
                    sim = 1.0 / (1.0 + float(dist)) if dist is not None else 0.0
                except Exception:
                    sim = 0.0

                if sim >= similarity_threshold:
                    results.append({
                        "id": row["id"],
                        "content": row["content"],
                        "summary": row.get("summary"),
                        "tags": row.get("tags") or [],
                        "project_id": row.get("project_id"),
                        "created_at": row.get("created_at"),
                        "score": float(sim),
                        "search_type": "vector"
                    })

            return results
        except Exception as e:
            logger.debug(f"DB ANN search error: {e}")
            return None

    def _build_vector_query(self, project_id: Optional[UUID], tags: Optional[List[str]]):
        query_conditions = [Memory.embedding.isnot(None)]
        if project_id:
            query_conditions.append(Memory.project_id == project_id)
        if tags:
            tag_conditions = [func.array_to_string(Memory.tags, ',').like(f'%{tag}%') for tag in tags]
            query_conditions.append(or_(*tag_conditions))
        return select(Memory).where(and_(*query_conditions)) if query_conditions else select(Memory).where(Memory.embedding.isnot(None))

    def _calculate_similarity(self, memories, query_embedding, similarity_threshold, limit):
        similar_memories = []
        for memory in memories:
            if memory.embedding is None or query_embedding is None:
                continue
            mem_emb = list(memory.embedding)
            if len(mem_emb) != len(query_embedding):
                continue

            similarity = self._calculate_cosine_similarity(query_embedding, mem_emb)
            if similarity >= similarity_threshold:
                similar_memories.append({
                    "id": memory.id,
                    "content": memory.content,
                    "summary": memory.summary,
                    "tags": memory.tags or [],
                    "project_id": memory.project_id,
                    "created_at": memory.created_at,
                    "score": float(similarity),
                    "search_type": "vector"
                })

        similar_memories.sort(key=lambda x: x["score"], reverse=True)
        return similar_memories[:limit]
    

    def _rank_results(self, vector_results: List[Dict], keyword_results: List[Dict], top_k: int = 10, request_tags: Optional[List[str]] = None) -> List[Dict]:
        try:
            # Create combined results dictionary (memory_id -> result)
            combined_results = {}

            # Normalize request tags (lowercase and remove extra spaces)
            req_tags_norm = [t.lower().strip() for t in (request_tags or [])]

            # Add vector results
            for result in vector_results:
                memory_id = result["id"]
                result["vector_score"] = result["score"]
                # mark as vector-only by default (may be upgraded to hybrid below)
                result["search_type"] = "vector"
                result["keyword_score"] = 0.0
                result["combined_score"] = result["score"] * VECTOR_WEIGHT  # Start combined score with vector weight
                combined_results[memory_id] = result

            for result in keyword_results:
                memory_id = result["id"]
                if memory_id in combined_results:
                    # Memory found in both searches - boost score
                    existing = combined_results[memory_id]
                    existing["keyword_score"] = result["score"]
                    # Combined score using both vector and keyword weights
                    existing["combined_score"] = (
                        existing["vector_score"] * VECTOR_WEIGHT +    # Vector weight
                        existing["keyword_score"] * KEYWORD_WEIGHT +  # Keyword weight
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
                    # ensure keyword-only is marked
                    result["search_type"] = result.get("search_type", "keyword")
                    result["combined_score"] = min(result["combined_score"], 1.0)
                    combined_results[memory_id] = result

            for res in combined_results.values():
                doc_tags = [t.lower().strip() for t in (res.get("tags") or [])]
                if any(rt in doc_tags for rt in req_tags_norm):
                    res["combined_score"] = min(res["combined_score"] + TAG_BOOST, 1.0)

            final_results = list(combined_results.values())
            final_results.sort(key=lambda x: x["combined_score"], reverse=True)

            ranked_results = []
            for i, result in enumerate(final_results[:top_k]):
                result["score"] = float(max(0.0, min(result["combined_score"], 1.0)))
                result["rank"] = i + 1
                result.pop("vector_score", None)
                result.pop("keyword_score", None)
                result.pop("combined_score", None)
                ranked_results.append(result)

            logger.info(f"Ranked {len(ranked_results)} combined results from {len(vector_results)} vector + {len(keyword_results)} keyword results")
            return ranked_results

        except Exception as e:
            logger.error(f"Error ranking results: {e}")
            return vector_results[:top_k] if vector_results else keyword_results[:top_k]


    def _calculate_cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        import math
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = math.sqrt(sum(a * a for a in vec1))
        magnitude2 = math.sqrt(sum(b * b for b in vec2))
        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0
        return (dot_product / (magnitude1 * magnitude2) + 1) / 2

    async def keyword_search(self, keywords: List[str], project_id: Optional[UUID] = None, limit: int = 10, full_query: Optional[str] = None) -> List[Dict]:
        try:
            if not keywords:
                raise ValueError("Keywords list cannot be empty")

            token_segments = [token for kw in keywords for token in re.findall(r"\w+", kw.lower(), flags=re.UNICODE)]
            token_segments = [t for t in token_segments if t and t not in STOPWORDS and len(t) >= 3]
            token_segments = list(dict.fromkeys(token_segments))
            if not token_segments:
                return []

            token_conditions = [or_(
                func.lower(Memory.content).like(f"%{token}%"),
                func.lower(Memory.summary).like(f"%{token}%"),
                func.lower(func.array_to_string(Memory.tags, ' ')).like(f"%{token}%")
            ) for token in token_segments]

            where_clause = or_(*token_conditions)
            if project_id:
                where_clause = and_(where_clause, Memory.project_id == project_id)

            fetch_limit = max(limit * 5, 50)
            query = select(Memory).where(where_clause).order_by(Memory.created_at.desc()).limit(fetch_limit)
            try:
                result = await self.db.execute(query)
            except Exception as e:
                logger.error(f"DB error during keyword candidates fetch: {e}")
                try:
                    await self.db.rollback()
                except Exception:
                    logger.debug("Rollback failed or not applicable")
                return []
            memories = result.scalars().all()

            candidates = []
            for memory in memories:
                combined = " ".join([memory.content or "", memory.summary or "", " ".join(memory.tags or [])]).lower()
                matched = sum(1 for token in token_segments if token in combined)
                score = matched / len(token_segments) if token_segments else 0.0

                phrase_bonus = PHRASE_BOOST if full_query and full_query.lower().strip() in combined else 0.0
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
            return candidates[:limit]
        except Exception as e:
            logger.error(f"Error in keyword search: {e}")
            return []

    async def _check_cache(
        self, 
        query: str, 
        project_id: Optional[UUID], 
        tags: Optional[List[str]], 
        limit: int
    ) -> Optional[List[Dict]]:
        if not self.redis:
            return None

        try:
            cache_params = {
                "query": query,
                "project_id": str(project_id) if project_id else None,
                "tags": sorted(tags) if tags else None,
                "limit": limit
            }
            cache_key = f"search:{hashlib.md5(json.dumps(cache_params, sort_keys=True).encode()).hexdigest()}"
            
            cached_data = self.redis.get(cache_key)
            if cached_data:
                try:
                    parsed = json.loads(cached_data)
                except Exception:
                    # corrupted cache entry
                    return None

                repaired = False
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict) and "search_type" not in item:

                            st = "unknown"
                            src = item.get("sources") or {}
                            try:
                                v = float(src.get("vector", 0) or 0)
                            except Exception:
                                v = 0.0
                            try:
                                k = float(src.get("keyword", 0) or 0)
                            except Exception:
                                k = 0.0

                            if v > 0 and k > 0:
                                st = "hybrid"
                            elif v > 0:
                                st = "vector"
                            elif k > 0:
                                st = "keyword"

                            item["search_type"] = st
                            repaired = True

                if repaired:

                    try:
                        await self._cache_results(parsed, query, project_id, tags, limit)
                    except Exception:
                        logger.debug("Failed to re-cache repaired search results")

                return parsed
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
        if not self.redis:
            return

        try:
            cache_params = {
                "query": query,
                "project_id": str(project_id) if project_id else None,
                "tags": sorted(tags) if tags else None,
                "limit": limit
            }
            cache_key = f"search:{hashlib.md5(json.dumps(cache_params, sort_keys=True).encode()).hexdigest()}"

            self.redis.setex(cache_key, 3600, json.dumps(results, default=str))
            logger.info(f"Cached search results with key: {cache_key}")
        except Exception as e:
            logger.warning(f"Failed to cache results: {e}")
