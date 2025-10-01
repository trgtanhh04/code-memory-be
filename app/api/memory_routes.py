from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.ext.asyncio import AsyncSession
from redis import Redis
import logging
from typing import List, Optional
from uuid import UUID

from app.schemas.memory_schemas import SaveMemoryRequest, MemoryResponse
from app.services.save_memory_service import SaveMemoryService
from app.db.connect_db import get_db_session, get_redis
from app.models.memory_models import UserProject
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/memories", tags=["memories"])

async def get_save_memory_service(
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis)
) -> SaveMemoryService:
    """Dependency to get SaveMemoryService instance"""
    return SaveMemoryService(db=db, redis=redis)


async def verify_user_project_access(
    project_id: UUID,
    user_id: UUID,
    db: AsyncSession
) -> bool:
    """Verify that user has access to the project"""
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
    user_id: Optional[str] = Header(None, alias="X-User-ID"),  # Temporary auth via header
    save_service: SaveMemoryService = Depends(get_save_memory_service),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Save a new memory to the project
    
    - **content**: The memory content (required, 1-50000 chars)
    - **project_id**: UUID of the project to save memory to
    - **tags**: Optional list of tags (max 20)
    - **metadata**: Optional metadata dictionary
    - **X-User-ID**: User ID header (temporary authentication method)
    """
    try:
        # Temporary: Use default user_id if not provided
        if not user_id:
            user_id = "12345678-1234-5678-9012-123456789012"
        
        user_uuid = UUID(user_id)
        
        # Verify user has access to project
        # has_access = await verify_user_project_access(
        #     request.project_id, 
        #     user_uuid, 
        #     db
        # )
        
        # if not has_access:
        #     raise HTTPException(
        #         status_code=status.HTTP_403_FORBIDDEN,
        #         detail="User does not have access to this project"
        #     )
        
        # Save memory
        memory = await save_service.save_memory(
            content=request.content,
            project_id=request.project_id,
            user_id=user_uuid,  # For access validation
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
        has_access = await verify_user_project_access(project_id, user_uuid, db)
        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have access to this project"
            )
        
        # Count memories
        from sqlalchemy import func, text
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
        
