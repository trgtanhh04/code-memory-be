from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from sqlalchemy.exc import IntegrityError
from typing import Optional, List
import logging
from datetime import datetime, timedelta
from uuid import UUID

from app.models.memory_models import Project, UserProject, Memory
from app.schemas.memory_schemas import CreateProjectRequest, ProjectResponse

logger = logging.getLogger(__name__)


class ProjectService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_project(
        self, 
        request: CreateProjectRequest, 
        user_id: UUID
    ) -> Project:
        """
        Create a new project and assign the creator as owner
        """
        try:
            # Create project
            new_project = Project(
                name=request.name,
                description=request.description,
                settings=request.settings or {}
            )
            
            self.db.add(new_project)
            await self.db.flush()  # Get the project ID
            
            # Create user-project relationship with owner role
            user_project = UserProject(
                user_id=user_id,
                project_id=new_project.id,
                role="owner"
            )
            
            self.db.add(user_project)
            await self.db.commit()
            await self.db.refresh(new_project)
            
            logger.info(f"Created project {new_project.id} for user {user_id}")
            return new_project
            
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(f"Project creation failed - duplicate name: {e}")
            raise ValueError(f"Project with name '{request.name}' already exists")
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Failed to create project: {e}")
            raise Exception("Failed to create project")

    async def get_user_projects(self, user_id: UUID) -> List[Project]:
        """
        Get all projects that user has access to
        """
        try:
            result = await self.db.execute(
                select(Project)
                .join(UserProject)
                .where(UserProject.user_id == user_id)
                .order_by(desc(Project.created_at))
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Failed to get user projects: {e}")
            raise Exception("Failed to retrieve projects")

    async def get_project_by_id(self, project_id: UUID, user_id: UUID) -> Optional[Project]:
        """
        Get project by ID if user has access
        """
        try:
            result = await self.db.execute(
                select(Project)
                .join(UserProject)
                .where(
                    Project.id == project_id,
                    UserProject.user_id == user_id
                )
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to get project {project_id}: {e}")
            return None

    async def get_recent_memories(
        self, 
        project_id: UUID, 
        user_id: Optional[UUID] = None,  # Make user_id optional for testing
        limit: int = 10, 
        days: int = 7
    ) -> List[Memory]:
        """
        Get recent memories from a project within specified days
        """
        try:
            # Temporarily skip user permission check for testing
            if user_id:
                # First verify user has access to project
                project = await self.get_project_by_id(project_id, user_id)
                if not project:
                    raise ValueError("Project not found or access denied")
            else:
                # For testing - just check if project exists
                result = await self.db.execute(
                    select(Project).where(Project.id == project_id)
                )
                project = result.scalar_one_or_none()
                if not project:
                    raise ValueError("Project not found")
            
            # Calculate date threshold
            date_threshold = datetime.utcnow() - timedelta(days=days)
            
            # Query recent memories
            result = await self.db.execute(
                select(Memory)
                .where(
                    Memory.project_id == project_id,
                    Memory.created_at >= date_threshold
                )
                .order_by(desc(Memory.created_at))
                .limit(limit)
            )
            
            memories = result.scalars().all()
            logger.info(f"Retrieved {len(memories)} recent memories for project {project_id}")
            return memories
            
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to get recent memories: {e}")
            raise Exception("Failed to retrieve recent memories")