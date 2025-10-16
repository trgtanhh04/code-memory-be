from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID, uuid4
import logging

from app.db.connect_db import get_db_session
from app.models.memory_models import ApiKey, User
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
import traceback
from app.services.apikey_service import verify_secret


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
    

@router.get("/me")
async def get_user_id(
    supabase_user_id: str | None = Header(None, alias="X-SUPABASE-USER-ID"),
    db: AsyncSession = Depends(get_db_session)
):
    if not supabase_user_id:
        raise HTTPException(status_code=401, detail="Missing X-SUPABASE-USER-ID")
    try:
        result = await db.execute(select(User).where(User.supabase_user_id == supabase_user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail="ID not found")

    return {
        "user_id": str(user.id),
        "supabase_id": getattr(user, "supabase_user_id", None),
        "email": getattr(user, "email", None),
        "name": getattr(user, "name", None),
    }


@router.get("/user_by_api_key")
async def get_user_by_api_key(
    api_key: str | None = Header(None, alias="x-api-key"),
    db: AsyncSession = Depends(get_db_session)
):
    ak = await db.execute(select(ApiKey).where(ApiKey.raw_secret == api_key))
    ak = ak.scalar_one_or_none()

    if not ak or ak.revoked:
        raise HTTPException(status_code=401, detail="ApiKey not found or revoked")
    
    user = await db.get(User, ak.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "user_id": str(user.id),
        "name": user.name,
        "email": user.email,
        "supabase_user_id": user.supabase_user_id,
        "preferences": user.preferences,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }
        
    

