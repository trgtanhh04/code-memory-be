from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID, uuid4
import logging

from app.db.connect_db import get_db_session
from app.models.memory_models import User
from pydantic import BaseModel, EmailStr
from sqlalchemy.exc import IntegrityError
import traceback


from app.services.supabase_admin import create_supabase_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/users", tags=["users"])


class CreateUserRequest(BaseModel):
    email: EmailStr
    name: str | None = None


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

        try:
            supabase_uid = await create_supabase_user(req.email, name=req.name)
        except Exception as e:
            logger.warning(f"Supabase admin create failed: {e}")
            supabase_uid = None

        # create local user
        new_user = User(id=user_id, email=req.email, name=req.name, supabase_user_id=supabase_uid)
        db.add(new_user)
        await db.flush()

        logger.info(f"Created user {new_user.id}")
        return CreateUserResponse(id=new_user.id, email=new_user.email, name=new_user.name)
    except Exception as e:
        logger.error(f"Failed to create user: {e}")
        raise HTTPException(status_code=500, detail="Failed to create user")
