from fastapi import APIRouter, Depends, HTTPException, status, Header
from typing import Optional
from uuid import UUID
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.connect_db import get_db_session
from app.services.apikey_service import create_apikey, delete_apikey, revoke_apikey, unrevoke_apikey
from app.models.memory_models import ApiKey as ApiKeyModel

router = APIRouter(prefix="/api/v1/apikeys", tags=["apikeys"])


class CreateApiKeyRequest(BaseModel):
    name: Optional[str] = None
    scopes: Optional[list] = None


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_key(req: CreateApiKeyRequest, user_id: Optional[str] = Header(None, alias="X-User-ID"), db: AsyncSession = Depends(get_db_session)):
    """
    Create a new API key for the user.
    
    - **user_id**: ID of the user creating the API key
    - **name**: Name of the API key
    """
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID (use real auth in production)")
    try:
        user_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="X-User-ID must be a valid UUID")
    api_key_obj, full_key = await create_apikey(db=db, user_id=user_uuid, name=req.name, scopes=req.scopes)
    return {"id": str(api_key_obj.id), "api_key": full_key}


class ApiKeyResponse(BaseModel):
    id: UUID
    name: Optional[str] = None
    api_key: Optional[str] = None
    scopes: Optional[list] = None
    revoked: bool
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None


@router.get("/", response_model=list[ApiKeyResponse])
async def list_keys(
    limit: int = 100,
    offset: int = 0,
    user_id: Optional[str] = Header(None, alias="X-User-ID"),
    db: AsyncSession = Depends(get_db_session),
):
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID")
    try:
        user_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="X-User-ID must be a valid UUID or you have to create a user first")

    res = await db.execute(select(ApiKeyModel).where(ApiKeyModel.user_id == user_uuid).order_by(ApiKeyModel.created_at.desc()).limit(limit).offset(offset))
    rows = res.scalars().all()
    out = []
    for r in rows:
        out.append(
            ApiKeyResponse(
                id=r.id,
                name=r.name,
                api_key=r.hashed_secret,
                scopes=r.scopes,
                revoked=bool(r.revoked),
                created_at=r.created_at.isoformat() if r.created_at else None,
                last_used_at=r.last_used_at.isoformat() if r.last_used_at else None,
            )
        )
    return out

@router.post("/{key_id}/revoke")
async def revoke_key(key_id: UUID, user_id: Optional[str] = Header(None, alias="X-User-ID"), db: AsyncSession = Depends(get_db_session)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID")
    try:
        _ = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="X-User-ID must be a valid UUID")
    ak = await revoke_apikey(db=db, key_id=key_id)
    if not ak:
        raise HTTPException(status_code=404, detail="ApiKey not found")
    return {"status": "revoked", "id": str(key_id)}

@router.post("/{key_id}/unrevoke")
async def unrevoke_key(key_id: UUID, user_id: Optional[str] = Header(None, alias="X-User-ID"), db: AsyncSession = Depends(get_db_session)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID")
    try:
        _ = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="X-User-ID must be a valid UUID")
    ak = await unrevoke_apikey(db=db, key_id=key_id)
    if not ak:
        raise HTTPException(status_code=404, detail="ApiKey not found")
    return {"status": "unrevoked", "id": str(key_id)}

@router.delete("/{key_id}")
async def delete_key(key_id: UUID, user_id: Optional[str] = Header(None, alias="X-User-ID"), db: AsyncSession = Depends(get_db_session)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID")
    try:
        _ = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="X-User-ID must be a valid UUID")
    ak = await delete_apikey(db=db, key_id=key_id)
    if not ak:
        raise HTTPException(status_code=404, detail="ApiKey not found")
    return {"status": "deleted", "id": str(key_id)}
                                                                     