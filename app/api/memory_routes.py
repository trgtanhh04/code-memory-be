from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.ext.asyncio import AsyncSession
from redis import Redis
import logging
from typing import List, Optional
from uuid import UUID

from app.schemas.memory_schemas import (
    SaveMemoryRequest, MemoryResponse, GetMemoriesResponse, 
    GetRecentMemoriesRequest, GetRecentMemoriesResponse
)
from app.services.save_memory_service import SaveMemoryService
from app.services.project_service import ProjectService
from app.db.connect_db import get_db_session, get_redis
from app.models.memory_models import UserProject
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
    user_id: Optional[str] = Header(None, alias="X-User-ID"), 
    save_service: SaveMemoryService = Depends(get_save_memory_service),
    db: AsyncSession = Depends(get_db_session)
):
    try:
        if not user_id:
            user_id = "12345678-1234-5678-9012-123456789012"
        
        user_uuid = UUID(user_id)
        
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
            embedding_dimensions=len(memory.embedding) if memory.embedding else None
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
    user_id: Optional[str] = Header(None, alias="X-User-ID"),
    db: AsyncSession = Depends(get_db_session)
):
    """Get total memory count for a project"""
    try:
        if not user_id:
            user_id = "12345678-1234-5678-9012-123456789012"
        
        user_uuid = UUID(user_id)
        
        # Verify access
        # has_access = await verify_user_project_access(project_id, user_uuid, db)
        # if not has_access:
        #     raise HTTPException(
        #         status_code=status.HTTP_403_FORBIDDEN,
        #         detail="User does not have access to this project"
        #     )
        
        # Count memories
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
    user_id: Optional[str] = Header(None, alias="X-User-ID"),
    db: AsyncSession = Depends(get_db_session)
):
    try:
        if not user_id:
            user_id = "12345678-1234-5678-9012-123456789012"
        
        user_uuid = UUID(user_id)
        
        # TEMPORARY: Skip permission check for testing
        # has_access = await verify_user_project_access(project_id, user_uuid, db)
        # if not has_access:
        #     raise HTTPException(status_code=403, detail="Access denied")
        
        # Parse tags
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
                embedding_dimensions=len(memory.embedding) if memory.embedding else None
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
    user_id: Optional[str] = Header(None, alias="X-User-ID"),
    project_service: ProjectService = Depends(get_project_service)
):
    try:
        if not user_id:
            user_id = "12345678-1234-5678-9012-123456789012"
        
        # user_uuid = UUID(user_id)  # Comment out for testing
        
        if limit > 50:
            limit = 50
        if days > 30:
            days = 30
        
        memories = await project_service.get_recent_memories(
            project_id=project_id,
            # user_id=user_uuid,  # Comment out for testing
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
                embedding_dimensions=len(memory.embedding) if memory.embedding else None
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

@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: UUID,
    user_id: Optional[str] = Header(None, alias="X-User-ID"),
    db: AsyncSession = Depends(get_db_session),
    redis: Optional[Redis] = Depends(get_redis)
):
    """
    Delete a memory by ID
    
    - **memory_id**: UUID of the memory to delete
    - **X-User-ID**: User ID header (temporary authentication method)
    """
    try:
        if not user_id:
            user_id = "12345678-1234-5678-9012-123456789012"
        
        user_uuid = UUID(user_id)
        
        # First, get the memory to verify it exists and user has access
        memory_query = select(Memory).where(Memory.id == memory_id)
        result = await db.execute(memory_query)
        memory = result.scalar_one_or_none()
        
        if not memory:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Memory not found"
            )
        
        # Verify user has access to the project (temporarily commented for testing)
        # has_access = await verify_user_project_access(memory.project_id, user_uuid, db)
        # if not has_access:
        #     raise HTTPException(
        #         status_code=status.HTTP_403_FORBIDDEN,
        #         detail="User does not have access to this memory"
        #     )
        
        # Delete the memory
        await db.delete(memory)
        await db.commit()
        
        # Clear related cache entries
        if redis:
            try:
                # Clear individual memory cache
                memory_cache_key = f"memory:{memory_id}"
                redis.delete(memory_cache_key)
                
                # Clear project memories cache
                project_cache_key = f"project:{memory.project_id}:memories"
                redis.delete(project_cache_key)
                
                # Clear user recent memories cache
                user_recent_key = f"user:{user_uuid}:recent_memories"
                redis.lrem(user_recent_key, 0, str(memory_id))
                
                logger.info(f"Cleared cache for deleted memory: {memory_id}")
            except Exception as cache_error:
                logger.warning(f"Failed to clear cache after deletion: {cache_error}")
        
        logger.info(f"Memory deleted successfully: {memory_id}")
        return  # 204 No Content response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting memory: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while deleting memory"
        )


# --------------- Vector Search Endpoint ---------------
