from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID, uuid4
import logging

from app.db.connect_db import get_db_session
from app.models.memory_models import User
from pydantic import BaseModel, EmailStr
from sqlalchemy.exc import IntegrityError
import traceback

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/users", tags=["users"])


class CreateUserRequest(BaseModel):
    email: EmailStr
    name: str | None = None
    # id is generated server-side. Clients should NOT supply an id.


class CreateUserResponse(BaseModel):
    id: UUID
    email: EmailStr
    name: str | None = None


@router.post("/", response_model=CreateUserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    req: CreateUserRequest,
    db: AsyncSession = Depends(get_db_session)
):
    try:
        user_id = uuid4()
        new_user = User(id=user_id, email=req.email, name=req.name)
        db.add(new_user)
        await db.flush()

        logger.info(f"Created user {new_user.id}")
        return CreateUserResponse(id=new_user.id, email=new_user.email, name=new_user.name)
    except Exception as e:
        logger.error(f"Failed to create user: {e}")
        raise HTTPException(status_code=500, detail="Failed to create user")
