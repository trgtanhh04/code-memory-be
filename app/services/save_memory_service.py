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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from redis import Redis

from app.models.memory_models import Memory, UserProject
from app.vector_db.embed import get_embedding_model

logger = logging.getLogger(__name__)


class SaveMemoryService:
    def __init__(self, db: AsyncSession, redis: Optional[Redis] = None):
        self.db = db
        self.redis = redis
        self.embedding_model = get_embedding_model()

    async def save_memory(
        self,
        content: str,
        project_id: UUID,
        user_id: UUID,
        tags: List[str] = None,
        metadata: Dict = None
    ) -> Memory:
        """Save a memory with content, generate embeddings, and cache results."""
        try:
            await self._validate_input(content, project_id, user_id)
            
            # Process content
            processed_content = self._sanitize_content(content)
            
            # Generate embeddings
            embedding_vector = await self._generate_embedding(processed_content)
            
            # Prepare data
            processed_tags = tags or await self._auto_generate_tags(processed_content)
            
            # Save to database (following ERD schema)
            memory = await self._save_to_database(
                content=processed_content,
                embedding=embedding_vector,
                project_id=project_id,
                tags=processed_tags,
                metadata=metadata
            )
            
            # Cache results
            await self._cache_memory(memory, user_id, project_id)
            
            logger.info(f"Memory saved successfully: {memory.id}")
            return memory
            
        except Exception as e:
            logger.error(f"Failed to save memory: {str(e)}")
            raise

    async def _validate_input(self, content: str, project_id: UUID, user_id: UUID):
        if not content or not content.strip():
            raise ValueError("Content cannot be empty")
        
        if len(content) > 50000:
            raise ValueError("Content too large (max 50KB)")
        
        await self._validate_user_project_access(user_id, project_id)

    async def _validate_user_project_access(self, user_id: UUID, project_id: UUID):
        result = await self.db.execute(
            select(UserProject).where(
                UserProject.user_id == user_id,
                UserProject.project_id == project_id
            )
        )
        
        if not result.scalar_one_or_none():
            raise PermissionError(f"User has no access to project {project_id}")

    def _sanitize_content(self, content: str) -> str:
        return ' '.join(content.split()).strip()



    async def _generate_embedding(self, content: str) -> Optional[List[float]]:
        try:
            embedding = await self.embedding_model.aembed_query(content)
            return embedding
        except Exception as e:
            logger.warning(f"Failed to generate embedding: {str(e)}")
            return None



    async def _auto_generate_tags(self, content: str) -> List[str]:
        words = content.lower().split()
        
        programming_keywords = {
            'python', 'javascript', 'react', 'fastapi', 'sql', 'database',
            'api', 'authentication', 'security', 'async', 'function', 'class'
        }
        
        tags = []
        for word in words:
            clean_word = ''.join(char for char in word if char.isalnum())
            if clean_word in programming_keywords and clean_word not in tags:
                tags.append(clean_word)
                
        return tags[:10]

    async def _save_to_database(
        self,
        content: str,
        embedding: Optional[List[float]],
        project_id: UUID,
        tags: List[str],
        metadata: Optional[Dict]
    ) -> Memory:
        memory = Memory(
            id=uuid4(),
            project_id=project_id,
            content=content,
            embedding=embedding,
            tags=tags or [],
            meta_data=metadata or {},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        self.db.add(memory)
        await self.db.flush()
        
        return memory

    async def _cache_memory(self, memory: Memory, user_id: UUID, project_id: UUID):
        try:
            if self.redis:  # Only cache if Redis is available
                cache_key = f"memory:{memory.id}"
                memory_data = {
                    "id": str(memory.id),
                    "content": memory.content,
                    "tags": memory.tags,
                    "created_at": memory.created_at.isoformat(),
                    "project_id": str(memory.project_id)
                }
                
                self.redis.setex(cache_key, 3600, json.dumps(memory_data))
                
                user_recent_key = f"user:{user_id}:recent_memories"
                self.redis.lpush(user_recent_key, str(memory.id))
                self.redis.ltrim(user_recent_key, 0, 49)
                self.redis.expire(user_recent_key, 86400)
                
                project_cache_key = f"project:{project_id}:memories"
                self.redis.delete(project_cache_key)
            else:
                logger.info("Redis not available, skipping cache operations")
            
        except Exception as e:
            logger.warning(f"Failed to cache memory: {str(e)}")

# async def create_test_data(db: AsyncSession):
#     """Create test user and project data"""
#     from app.models.memory_models import User, Project, UserProject
#     from sqlalchemy import select
#     import time
    
#     # Generate unique names with timestamp
#     timestamp = int(time.time())
#     user_email = f"developer{timestamp}@codememory.com"
#     project_name = f"AI Assistant Development {timestamp}"
    
#     # Check if user already exists
#     existing_user = await db.execute(select(User).where(User.email == user_email))
#     user = existing_user.scalar_one_or_none()
    
#     if not user:
#         # Test user
#         user = User(
#             id=uuid4(),
#             email=user_email,
#             name="Test Developer",
#             created_at=datetime.utcnow()
#         )
#         db.add(user)
    
#     # Check if project already exists
#     existing_project = await db.execute(select(Project).where(Project.name == project_name))
#     project = existing_project.scalar_one_or_none()
    
#     if not project:
#         # Test project
#         project = Project(
#             id=uuid4(),
#             name=project_name,
#             description="Building intelligent coding assistant with memory capabilities",
#             created_at=datetime.utcnow()
#         )
#         db.add(project)
    
#     # Check if user-project relationship exists
#     existing_user_project = await db.execute(
#         select(UserProject).where(
#             UserProject.user_id == user.id,
#             UserProject.project_id == project.id
#         )
#     )
#     user_project_rel = existing_user_project.scalar_one_or_none()
    
#     if not user_project_rel:
#         # User-project relationship
#         user_project = UserProject(
#             user_id=user.id,
#             project_id=project.id,
#             role="owner",
#             created_at=datetime.utcnow()
#         )
#         db.add(user_project)
    
#     await db.commit()
    
#     return user.id, project.id
