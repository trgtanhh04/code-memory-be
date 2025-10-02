from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.ext.asyncio import AsyncSession
import logging
from typing import List, Optional
from uuid import UUID

from app.schemas.memory_schemas import CreateProjectRequest, ProjectResponse
from app.services.project_service import ProjectService
from app.db.connect_db import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


async def get_project_service(
    db: AsyncSession = Depends(get_db_session)
) -> ProjectService:
    """Dependency to get ProjectService instance"""
    return ProjectService(db=db)


@router.post("/create", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    request: CreateProjectRequest,
    user_id: Optional[str] = Header(None, alias="X-User-ID"),
    project_service: ProjectService = Depends(get_project_service)
):
    """
    Create a new project
    
    - **name**: Project name (required, 1-100 chars, must be unique)
    - **description**: Optional project description (max 1000 chars)
    - **settings**: Optional project settings as JSON object
    - **X-User-ID**: User ID header (temporary authentication method)
    """
    try:
        # Temporary: Use default user_id if not provided
        if not user_id:
            user_id = "12345678-1234-5678-9012-123456789012"
        
        user_uuid = UUID(user_id)
        
        # Create project
        project = await project_service.create_project(
            request=request,
            # user_id=user_uuid
        )
        
        # Build response
        response = ProjectResponse(
            id=project.id,
            name=project.name,
            description=project.description,
            settings=project.settings,
            created_at=project.created_at,
            updated_at=project.updated_at
        )
        
        logger.info(f"Project created successfully via API: {project.id}")
        return response
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error creating project: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while creating project"
        )


@router.get("/", response_model=List[ProjectResponse])
async def get_user_projects(
    user_id: Optional[str] = Header(None, alias="X-User-ID"),
    project_service: ProjectService = Depends(get_project_service)
):
    """
    Get all projects that user has access to
    
    - **X-User-ID**: User ID header (temporary authentication method)
    """
    try:
        # Temporary: Use default user_id if not provided
        if not user_id:
            user_id = "12345678-1234-5678-9012-123456789012"
        
        user_uuid = UUID(user_id)
        
        # Get user projects
        projects = await project_service.get_user_projects(user_uuid)
        
        # Build response
        project_responses = []
        for project in projects:
            project_responses.append(ProjectResponse(
                id=project.id,
                name=project.name,
                description=project.description,
                settings=project.settings,
                created_at=project.created_at,
                updated_at=project.updated_at
            ))
        
        logger.info(f"Retrieved {len(project_responses)} projects for user {user_uuid}")
        return project_responses
        
    except Exception as e:
        logger.error(f"Unexpected error getting user projects: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while getting projects"
        )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project_by_id(
    project_id: UUID,
    user_id: Optional[str] = Header(None, alias="X-User-ID"),
    project_service: ProjectService = Depends(get_project_service)
):
    """
    Get project by ID if user has access
    
    - **project_id**: UUID of the project
    - **X-User-ID**: User ID header (temporary authentication method)
    """
    try:
        # Temporary: Use default user_id if not provided
        if not user_id:
            user_id = "12345678-1234-5678-9012-123456789012"
        
        user_uuid = UUID(user_id)
        
        # Get project
        project = await project_service.get_project_by_id(
            project_id=project_id,
            # user_id=user_uuid
        )
        
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found or access denied"
            )
        
        # Build response
        response = ProjectResponse(
            id=project.id,
            name=project.name,
            description=project.description,
            settings=project.settings,
            created_at=project.created_at,
            updated_at=project.updated_at
        )
        
        logger.info(f"Retrieved project {project_id} for user {user_uuid}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error getting project: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while getting project"
        )


@router.get("/health")
async def health_check():
    """Health check endpoint for project service"""
    return {
        "status": "healthy",
        "service": "project-api",
        "version": "1.0.0",
        "features": ["create_project", "get_projects", "get_project_by_id"]
    }