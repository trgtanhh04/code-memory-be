from sqlalchemy import (
    Column, String, Text, Integer, Float, DateTime, ForeignKey, JSON, ARRAY,
    UniqueConstraint, func, Boolean
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY as PG_ARRAY
from sqlalchemy.orm import relationship, declarative_base
# from pgvector.sqlalchemy import Vector  # Comment out for now
import uuid

Base = declarative_base()

def default_uuid():
    return str(uuid.uuid4())
    
# ----------- Core Models -----------
class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=default_uuid, index=True)
    email = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=True)
    preferences = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # relationships
    projects = relationship("UserProject", back_populates="user")


class Project(Base):
    __tablename__ = "projects"
    id = Column(UUID(as_uuid=True), primary_key=True, default=default_uuid, index=True)
    name = Column(String, nullable=False, unique=True)
    description = Column(Text, nullable=True)
    settings = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationship
    members = relationship("UserProject", back_populates="project")
    memories = relationship("Memory", back_populates="project", cascade="all, delete-orphan")
    search_logs = relationship("SearchLog", back_populates="project", cascade="all, delete-orphan")


class UserProject(Base):
    __tablename__ = "user_projects"
    id = Column(UUID(as_uuid=True), primary_key=True, default=default_uuid, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String, nullable=True) 
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    user = relationship("User", back_populates="projects")
    project = relationship("Project", back_populates="members")

    __table_args__ = (
        UniqueConstraint("user_id", "project_id", name="uq_user_project"),
    )

class Memory(Base):
    __tablename__ = "memories"
    id = Column(UUID(as_uuid=True), primary_key=True, default=default_uuid, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    tags = Column(PG_ARRAY(Text), nullable=True)
    meta_data = Column(JSONB, nullable=True)
    embedding = Column(PG_ARRAY(Float), nullable=True)  # Temporary fallback
    usage_count = Column(Integer, default=0)
    last_accessed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    project = relationship("Project", back_populates="memories")

class SearchLog(Base):
    __tablename__ = "search_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=default_uuid, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    query = Column(Text, nullable=False)
    filters = Column(JSONB, nullable=True)
    results = Column(JSONB, nullable=True)
    result_count = Column(Integer, default=0)
    execution_time_ms = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("Project", back_populates="search_logs")


