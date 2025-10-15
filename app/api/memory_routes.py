from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.ext.asyncio import AsyncSession
from redis import Redis
import logging
from typing import List, Optional
from uuid import UUID

from app.schemas.memory_schemas import (
    SaveMemoryRequest, MemoryResponse, GetMemoriesResponse, 
    GetRecentMemoriesRequest, GetRecentMemoriesResponse,
    SearchMemoryRequest, SearchResultsResponse, PerformedBy, DeleteMemoryResponse
)
from app.services.save_memory_service import SaveMemoryService
from app.services.project_service import ProjectService
from app.services.search_memory_service import SearchMemoryService
from app.db.connect_db import get_db_session, get_redis, db_manager
import uuid
import json
from app.api.deps import require_apikey, get_user_from_apikey, get_performer_by_api_key
from app.models.memory_models import UserProject, ApiKey, User
from sqlalchemy import select
from sqlalchemy import func, text
from sqlalchemy import select, and_, func, text, delete
from app.models.memory_models import Memory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/memories", tags=["memories"])

async def get_save_memory_service(
    db: AsyncSession = Depends(get_db_session),
    redis: Optional[Redis] = Depends(get_redis)
) -> SaveMemoryService:
    return SaveMemoryService(db=db, redis=redis)


async def get_project_service(
    db: AsyncSession = Depends(get_db_session)
) -> ProjectService:
    return ProjectService(db=db)


async def get_search_service(
    db: AsyncSession = Depends(get_db_session),
    redis: Optional[Redis] = Depends(get_redis)
) -> SearchMemoryService:
    return SearchMemoryService(db=db, redis=redis)


async def verify_user_project_access(
    project_id: UUID,
    user_id: UUID,
    db: AsyncSession
) -> bool:
    try:
        result = await db.execute(
            select(UserProject).where(
                UserProject.user_id == user_id,
                UserProject.project_id == project_id
            )
        )
        return result.scalar_one_or_none() is not None
    except Exception as e:
        logger.error(f"Error verifying user project access: {e}")
        return False


@router.post("/save", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
async def save_memory(
    request: SaveMemoryRequest,
    save_service: SaveMemoryService = Depends(get_save_memory_service),
    db: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(require_apikey("save"))
):
    try:
        if not current_user or not current_user.get("user_id"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid apiKey")
        user_uuid = current_user["user_id"]

        performer = None
        try:
            ak_id = current_user.get("api_key_id")
            if ak_id:
                ak = await db.get(ApiKey, ak_id)
                if ak and not ak.revoked:
                    u = await db.get(User, ak.user_id)
                    if u:
                        performer = PerformedBy(id=u.id, email=u.email, name=u.name)
        except Exception:
            performer = None

        memory = await save_service.save_memory(
            content=request.content,
            project_id=request.project_id,
            user_id=user_uuid,
            tags=request.tags,
            metadata=request.metadata
        )
        
        # Build response
        response = MemoryResponse(
            id=memory.id,
            content=memory.content,
            tags=memory.tags or [],
            created_at=memory.created_at,
            updated_at=memory.updated_at,
            project_id=memory.project_id,
            meta_data=memory.meta_data or {},
            usage_count=memory.usage_count,
            embedding_dimensions=len(memory.embedding) if memory.embedding is not None else None,
            performed_by=performer
        )
        
        logger.info(f"Memory saved successfully via API: {memory.id}")
        return response
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error saving memory: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while saving memory"
        )


@router.get("/health")
async def health_check():
    """Health check endpoint for memory service"""
    return {
        "status": "healthy",
        "service": "memory-api",
        "version": "1.0.0",
        "features": ["save_memory"]
    }


@router.get("/projects/{project_id}/count")
async def get_memory_count(
    project_id: UUID,
    db: AsyncSession = Depends(get_db_session)
):
    try:
        result = await db.execute(
            text("SELECT COUNT(*) FROM memories WHERE project_id = :project_id"),
            {"project_id": str(project_id)}
        )
        count = result.scalar()
        
        return {
            "project_id": project_id,
            "memory_count": count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting memory count: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )
        

@router.get("/projects/{project_id}", response_model=GetMemoriesResponse)
async def get_memories(
    project_id: UUID,
    page: int = 1,
    limit: int = 20,
    tags: Optional[str] = None,
    search_content: Optional[str] = None,
    db: AsyncSession = Depends(get_db_session)
):
    try:
        tag_list = []
        if tags:
            tag_list = [tag.strip() for tag in tags.split(",") if tag.strip()]

        offset = (page - 1) * limit
        
        query_conditions = [Memory.project_id == project_id]
        
        if tag_list:
            for tag in tag_list:
                query_conditions.append(Memory.tags.contains([tag]))
        
        if search_content:
            query_conditions.append(Memory.content.ilike(f"%{search_content}%"))
        
        # Count total
        count_query = select(func.count(Memory.id)).where(and_(*query_conditions))
        total_result = await db.execute(count_query)
        total = total_result.scalar()
        
        memories_query = (
            select(Memory)
            .where(and_(*query_conditions))
            .order_by(Memory.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        
        result = await db.execute(memories_query)
        memories = result.scalars().all()
        
        memory_responses = []
        for memory in memories:
            memory_responses.append(MemoryResponse(
                id=memory.id,
                content=memory.content,
                tags=memory.tags or [],
                created_at=memory.created_at,
                updated_at=memory.updated_at,
                project_id=memory.project_id,
                meta_data=memory.meta_data or {},
                usage_count=memory.usage_count,
                embedding_dimensions=len(memory.embedding) if memory.embedding is not None else None
            ))
        
        total_pages = (total + limit - 1) // limit
        
        return GetMemoriesResponse(
            memories=memory_responses,
            total=total,
            page=page,
            limit=limit,
            total_pages=total_pages
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting memories: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get("/projects/{project_id}/recent", response_model=GetRecentMemoriesResponse)
async def get_recent_memories(
    project_id: UUID,
    limit: int = 10,
    days: int = 7,
    current_user: dict = Depends(require_apikey("search")),
    project_service: ProjectService = Depends(get_project_service)
):
    try:
        if not current_user or not current_user.get("user_id"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid apiKey")

        if limit > 50:
            limit = 50
        if days > 30:
            days = 30
        
        memories = await project_service.get_recent_memories(
            project_id=project_id,
            limit=limit,
            days=days
        )
        
        # Build response
        memory_responses = []
        for memory in memories:
            memory_responses.append(MemoryResponse(
                id=memory.id,
                content=memory.content,
                tags=memory.tags or [],
                created_at=memory.created_at,
                updated_at=memory.updated_at,
                project_id=memory.project_id,
                meta_data=memory.meta_data or {},
                usage_count=memory.usage_count,
                embedding_dimensions=len(memory.embedding) if memory.embedding is not None else None
            ))
        
        return GetRecentMemoriesResponse(
            memories=memory_responses,
            total=len(memory_responses)
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting recent memories: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


# --------------- Delete Memory Endpoint ---------------

@router.delete("/{memory_id}", response_model=DeleteMemoryResponse)
async def delete_memory(
    memory_id: UUID,
    current_user: dict = Depends(require_apikey("delete")),
    db: AsyncSession = Depends(get_db_session),
    redis: Optional[Redis] = Depends(get_redis)
):
    """
    Delete a memory by ID
    
    - **memory_id**: UUID of the memory to delete
    - **X-User-ID**: User ID header (temporary authentication method)
    """
    try:
        if not current_user or not current_user.get("user_id"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid apiKey")
        user_uuid = current_user["user_id"]
        
        memory_query = select(Memory).where(Memory.id == memory_id)
        result = await db.execute(memory_query)
        memory = result.scalar_one_or_none()
        
        if not memory:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Memory not found"
            )
        
        # Api key
        performer = None
        try:
            ak_id = current_user.get("api_key_id")
            if ak_id:
                ak = await db.get(ApiKey, ak_id)
                if ak and not ak.revoked:
                    u = await db.get(User, ak.user_id)
                    if u:
                        performer = PerformedBy(id=u.id, email=u.email, name=u.name)
        except Exception:
            performer = None
        
        
        await db.delete(memory)
        await db.commit()
        
        if redis:
            try:
                memory_cache_key = f"memory:{memory_id}"
                redis.delete(memory_cache_key)
                
                project_cache_key = f"project:{memory.project_id}:memories"
                redis.delete(project_cache_key)
                
                user_recent_key = f"user:{user_uuid}:recent_memories"
                redis.lrem(user_recent_key, 0, str(memory_id))
                
                logger.info(f"Cleared cache for deleted memory: {memory_id}")
            except Exception as cache_error:
                logger.warning(f"Failed to clear cache after deletion: {cache_error}")
        
        logger.info(f"Memory deleted successfully: {memory_id}")
        if performer:
            return DeleteMemoryResponse(deleted_id=memory_id, performed_by=performer)
        return DeleteMemoryResponse(deleted_id=memory_id, performed_by=PerformedBy(id=user_uuid, email=None, name=None))
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting memory: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while deleting memory"
        )


# --------------- Vector Search Endpoint ---------------
@router.post("/search", response_model=SearchResultsResponse)
async def search_memories(
    request: SearchMemoryRequest,
    db: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(require_apikey("search")),
    search_service: SearchMemoryService = Depends(get_search_service)
):
    try:
        if not current_user or not current_user.get("user_id"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid apiKey")
        resolved_user = current_user["user_id"]
        query = request.query
        if not query:
            raise HTTPException(status_code=422, detail="Missing 'query' in request body")
        
        # Api key
        performer = None
        try:
            ak_id = current_user.get("api_key_id")
            if ak_id:
                ak = await db.get(ApiKey, ak_id)
                if ak and not ak.revoked:
                    u = await db.get(User, ak.user_id)
                    if u:
                        performer = PerformedBy(id=u.id, email=u.email, name=u.name)
        except Exception:
            performer = None

        project_id = request.project_id
        tags = request.tags
        limit = request.limit
        similarity_threshold = request.similarity_threshold
        top_k = request.top_k

        project_uuid = project_id
        
        results = await search_service.search_memory(
            query=query,
            project_id=project_uuid,
            tags=tags,
            limit=limit,
            similarity_threshold=similarity_threshold,
            top_k=top_k
        )

        try:
            logger.info(f"Search performed by user: {resolved_user} on project: {project_uuid} query='{query}' results={len(results)}")
        except Exception:
            pass

        try:
            try:
                log_session = await db_manager.get_async_session()
            except Exception as e:
                logger.debug(f"Could not create logging session: {e}")
                log_session = None

            if log_session is not None:
                try:
                    log_id = str(uuid.uuid4())
                    await log_session.execute(
                        text(
                            "INSERT INTO search_logs (id, project_id, query, filters, results, created_at) "
                            "VALUES (:id, :project_id, :query, :filters, :results, now())"
                        ),
                        {
                            "id": log_id,
                            "project_id": str(project_uuid) if project_uuid else None,
                            "query": query,
                            "filters": json.dumps({"tags": tags} if tags else {}, default=str),
                            "results": json.dumps(
                                [
                                    {"id": str(r.get("id")), "score": r.get("score"), "search_type": r.get("search_type")} for r in results
                                ],
                                default=str,
                            ),
                        },
                    )
                    await log_session.commit()
                except Exception as e:
                    logger.debug(f"Failed to write search_log (best-effort): {e}")
                    try:
                        await log_session.rollback()
                    except Exception:
                        pass
                finally:
                    try:
                        await log_session.close()
                    except Exception:
                        pass
        except Exception:
            logger.debug("Unexpected error in search logging block")

        return {
            "results": results, 
            "count": len(results),
            "performed_by": performer
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in search endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during search")
