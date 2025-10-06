from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, validator


class SaveMemoryRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=50000)
    project_id: UUID
    tags: Optional[List[str]] = Field(default=None, max_items=20)
    metadata: Optional[Dict[str, Any]] = Field(default=None)

    @validator('content')
    def validate_content(cls, v):
        if not v or not v.strip():
            raise ValueError('Content cannot be empty')
        return v.strip()

    @validator('tags')
    def validate_tags(cls, v):
        if v is not None:
            return list(set([tag.strip() for tag in v if tag.strip()]))[:20]
        return v


class MemoryResponse(BaseModel):
    id: UUID
    content: str
    tags: List[str]
    created_at: datetime
    updated_at: datetime
    project_id: UUID
    meta_data: Dict[str, Any]
    usage_count: int = 0
    embedding_dimensions: Optional[int] = None

    class Config:
        from_attributes = True


class SearchMemoryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    project_id: Optional[UUID] = None
    tags: Optional[List[str]] = None
    limit: int = Field(default=10, ge=1, le=100)
    similarity_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    top_k: int = Field(default=10, ge=1, le=50)


class SearchHit(BaseModel):
    id: UUID
    content: str
    summary: Optional[str] = None
    tags: List[str] = []
    project_id: UUID
    created_at: datetime
    score: float
    search_type: str
    rank: Optional[int] = None


class SearchResultsResponse(BaseModel):
    results: List[SearchHit]
    count: int

    class Config:
        from_attributes = True


class GetMemoriesRequest(BaseModel):
    project_id: UUID
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)
    tags: Optional[List[str]] = None
    search_content: Optional[str] = None


class GetMemoriesResponse(BaseModel):
    memories: List[MemoryResponse]
    total: int
    page: int
    limit: int
    total_pages: int


# ============= PROJECT SCHEMAS =============

class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=1000)
    settings: Optional[Dict[str, Any]] = Field(default=None)

    @validator('name')
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError('Project name cannot be empty')
        return v.strip()

    @validator('description')
    def validate_description(cls, v):
        if v is not None:
            return v.strip() if v.strip() else None
        return v


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    settings: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class GetRecentMemoriesRequest(BaseModel):
    project_id: UUID
    limit: int = Field(default=10, ge=1, le=50)
    days: int = Field(default=7, ge=1, le=30)


class GetRecentMemoriesResponse(BaseModel):
    memories: List[MemoryResponse]
    total: int

    class Config:
        from_attributes = True