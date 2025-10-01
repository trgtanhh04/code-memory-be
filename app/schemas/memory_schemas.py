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


class SearchMemoryResponse(BaseModel):
    results: List[MemoryResponse]
    query: str
    total_results: int
    execution_time_ms: float