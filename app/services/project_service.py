from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.exc import IntegrityError
from typing import Optional, List
from datetime import datetime, timedelta
from uuid import UUID
import logging

from app.models.memory_models import Project, UserProject, Memory, User
from app.schemas.memory_schemas import CreateProjectRequest

logger = logging.getLogger(__name__)


class ProjectService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # Create project and assign owner
    async def create_project(self, request: CreateProjectRequest, user_id: UUID) -> Project:
        try:
            user = await self._ensure_user_exists(user_id)

            # Create project
            project = Project(
                name=request.name,
                description=request.description,
                settings=request.settings or {}
            )
            self.db.add(project)
            await self.db.flush()

            # Assign user as owner
            self.db.add(UserProject(user_id=user_id, project_id=project.id, role="owner"))
            await self.db.commit()
            await self.db.refresh(project)

            logger.info(f"Created project {project.id} for user {user_id}")
            return project

        except IntegrityError as e:
            await self.db.rollback()
            logger.error(f"Project creation failed - duplicate name: {e}")
            raise ValueError(f"Project with name '{request.name}' already exists")
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Failed to create project: {e}")
            raise Exception("Failed to create project")

    async def _ensure_user_exists(self, user_id: UUID) -> User:
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                id=user_id,
                email=f"user-{user_id}@test.com",
                name="Test User"
            )
            self.db.add(user)
            await self.db.flush()
            logger.info(f"Created test user {user_id}")
        return user

    # Retrieve user projects
    async def get_user_projects(self, user_id: UUID) -> List[Project]:
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

    # Retrieve project by id with user check
    async def get_project_by_id(self, project_id: UUID, user_id: UUID) -> Optional[Project]:
        try:
            result = await self.db.execute(
                select(Project)
                .join(UserProject)
                .where(Project.id == project_id, UserProject.user_id == user_id)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to get project {project_id}: {e}")
            return None

    # Get recent memories for a project
    async def get_recent_memories(
        self,
        project_id: UUID,
        user_id: Optional[UUID] = None,
        limit: int = 10,
        days: int = 7
    ) -> List[Memory]:
        try:
            project = await self._get_project_with_access(project_id, user_id)

            date_threshold = datetime.utcnow() - timedelta(days=days)
            result = await self.db.execute(
                select(Memory)
                .where(Memory.project_id == project_id, Memory.created_at >= date_threshold)
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

    async def _get_project_with_access(self, project_id: UUID, user_id: Optional[UUID]) -> Project:
        if user_id:
            project = await self.get_project_by_id(project_id, user_id)
            if not project:
                raise ValueError("Project not found or access denied")
        else:
            result = await self.db.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()
            if not project:
                raise ValueError("Project not found")
        return project
