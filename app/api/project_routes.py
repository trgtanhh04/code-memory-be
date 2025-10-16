from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.ext.asyncio import AsyncSession
import logging
from typing import List, Optional
from uuid import UUID
from fastapi import Path
from app.schemas.memory_schemas import CreateProjectRequest, ProjectResponse, UpdateProjectRequest
from app.services.project_service import ProjectService
from app.services.repomix_service import RepoAnalyzerService
from app.db.connect_db import get_db_session
import os

DEFAULT_USER_ID = os.getenv("DEFAULT_USER_ID", "12345678-1234-5678-9012-123456789012")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


# repo_analyzer = RepoAnalyzerService()

# async def get_project_service(
#     db: AsyncSession = Depends(get_db_session),
# ) -> ProjectService:
#     return ProjectService(db=db, repo_analyzer=repo_analyzer)

async def get_repo_analyzer() -> RepoAnalyzerService:
    return RepoAnalyzerService()

async def get_project_service(
    db: AsyncSession = Depends(get_db_session),
    repo_analyzer: RepoAnalyzerService = Depends(get_repo_analyzer)
) -> ProjectService:
    return ProjectService(db=db, repo_analyzer=repo_analyzer)


@router.post("/create", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    request: CreateProjectRequest,
    user_id: Optional[str] = Header(None, alias="X-User-ID"),
    project_service: ProjectService = Depends(get_project_service)
):
    try:
        if not user_id:
            user_id = DEFAULT_USER_ID
        
        user_uuid = UUID(user_id)
        
        project = await project_service.create_project(
            request=request,
            user_id=user_uuid  
        )
        
        project_response = ProjectResponse(
            id=project.id,
            name=project.name,
            description=project.description,
            technologies=project.technologies,
            settings=project.settings,
            created_at=project.created_at,
            updated_at=project.updated_at
        )
        
        logger.info(f"Project created successfully: {project.id}")
        return project_response
        
    except ValueError as e:
        logger.error(f"Validation error creating project: {e}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error creating project: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create project"
        )
    


@router.patch("/{project_id}", response_model=ProjectResponse)
async def edit_project(
    request: UpdateProjectRequest,
    user_id: Optional[str] = Header(None, alias="X-User-ID"),
    project_service: ProjectService = Depends(get_project_service),
    project_id: UUID = Path(...),
):
    try:
        if not user_id:
            user_id = DEFAULT_USER_ID

        user_uuid = UUID(user_id)
        
        project = await project_service.edit_project(
            project_id=project_id,
            request=request,
            user_id=user_uuid
        )
        
        project_response = ProjectResponse(
            id=project.id,
            name=project.name,
            description=project.description,
            is_active=project.is_active,
            repo_url=project.repo_url,
            technologies=project.technologies,
            memories_count=project.memories_count,
            members_count=project.members_count,
            last_active_at=project.last_active_at,
            settings=project.settings,
            created_at=project.created_at,
            updated_at=project.updated_at
        )
        
        logger.info(f"Project edited successfully: {project.id}")
        return project_response
        
    except ValueError as e:
        logger.error(f"Validation error editing project: {e}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error editing project: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to edit project"
        )


@router.get("/{project_id}/recent", response_model=list)
async def get_recent_memories(
    project_id: UUID,
    limit: int = 10,
    days: int = 7,
    user_id: Optional[str] = Header(None, alias="X-User-ID"),
    project_service: ProjectService = Depends(get_project_service)
):
    try:
        user_uuid = None
        if user_id:
            try:
                user_uuid = UUID(user_id)
            except ValueError:
                pass
        
        memories = await project_service.get_recent_memories(
            project_id=project_id,
            user_id=user_uuid,
            limit=min(limit, 50),
            days=min(days, 30)
        )
        
        memory_list = []
        for memory in memories:
            memory_dict = {
                "id": str(memory.id),
                "content": memory.content,
                "summary": memory.summary,
                "tags": memory.tags or [],
                "project_id": str(memory.project_id),
                "created_at": memory.created_at.isoformat(),
                "updated_at": memory.updated_at.isoformat() if memory.updated_at else None
            }
            memory_list.append(memory_dict)
        
        logger.info(f"Retrieved {len(memory_list)} recent memories for project {project_id}")
        return memory_list
        
    except ValueError as e:
        logger.error(f"Get recent memories error: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error getting recent memories: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve recent memories"
        )


@router.get("/user", response_model=list)
async def get_user_projects(
    user_id: Optional[str] = Header(None, alias="X-User-ID"),
    project_service: ProjectService = Depends(get_project_service)
):
    try:
        if not user_id:
            user_id = DEFAULT_USER_ID
        
        user_uuid = UUID(user_id)
        
        projects = await project_service.get_user_projects(user_uuid)
        
        project_list = []
        for project in projects:
            project_dict = {
                "id": str(project.id),
                "name": project.name,
                "description": project.description,
                "settings": project.settings,
                "created_at": project.created_at.isoformat(),
                "updated_at": project.updated_at.isoformat() if project.updated_at else None
            }
            project_list.append(project_dict)
        
        logger.info(f"Retrieved {len(project_list)} projects for user {user_uuid}")
        return project_list
        
    except Exception as e:
        logger.error(f"Unexpected error getting user projects: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve user projects"
        )

@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project_details(
    project_id: UUID,
    user_id: Optional[str] = Header(None, alias="X-User-ID"),
    project_service: ProjectService = Depends(get_project_service)
):
    try:
        if not user_id:
            user_id = DEFAULT_USER_ID
        
        user_uuid = UUID(user_id)
        
        project = await project_service.get_project_by_id(project_id, user_uuid)
        
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found or access denied"
            )
        
        project_response = ProjectResponse(
            id=project.id,
            name=project.name,
            description=project.description,
            is_active=project.is_active,
            repo_url=project.repo_url,
            technologies=project.technologies,
            memories_count=project.memories_count,
            members_count=project.members_count,
            last_active_at=project.last_active_at,
            settings=project.settings,
            created_at=project.created_at,
            updated_at=project.updated_at
        )
        
        logger.info(f"Retrieved project details for {project_id}")
        return project_response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error getting project details: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve project details"
        )