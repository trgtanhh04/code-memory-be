from fastapi import Header, Request, HTTPException, Depends
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from datetime import datetime

from app.db.connect_db import get_db_session
from app.models.memory_models import ApiKey
from app.services.apikey_service import verify_secret
from sqlalchemy import select
from typing import Optional
from app.models.memory_models import User
from app.schemas.memory_schemas import PerformedBy


async def get_user_from_apikey(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key")
):
    raw_key = None

    if authorization and authorization.lower().startswith("bearer "):
        raw_key = authorization.split(" ", 1)[1].strip()
    elif x_api_key:
        raw_key = x_api_key
    else:
        raw_key = request.query_params.get("apiKey")

    if not raw_key:
        return None

    if "." not in raw_key:
        raise HTTPException(status_code=401, detail="Invalid apiKey format")

    key_id_str, secret = raw_key.split(".", 1)

    ak = None
    try:
        key_id = UUID(key_id_str)
        ak = await db.get(ApiKey, key_id)
    except Exception:
        key_id = None

    if not ak:
        res = await db.execute(select(ApiKey).where(ApiKey.raw_secret == raw_key))
        ak = res.scalar_one_or_none()

    if not ak or ak.revoked:
        raise HTTPException(status_code=401, detail="ApiKey not found or revoked")

    stored = ak.raw_secret
    if stored != raw_key:
        if not verify_secret(secret, stored):
            raise HTTPException(status_code=401, detail="Invalid apiKey secret")


    ak.last_used_at = datetime.utcnow()
    await db.flush()

    return {"user_id": ak.user_id, "api_key_id": ak.id, "scopes": ak.scopes}


async def get_performer_by_api_key(
    raw_key: str,
    db: AsyncSession
) -> Optional[PerformedBy]:

    ak = await db.execute(select(ApiKey).where(ApiKey.raw_secret == raw_key))
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
    }


def require_apikey(required_scope: Optional[str] = None):
    async def _dependency(current_user: Optional[dict] = Depends(get_user_from_apikey)):
        if not current_user:
            raise HTTPException(status_code=401, detail="Missing or invalid apiKey")

        if required_scope:
            scopes = current_user.get("scopes") or []
            if required_scope not in scopes:
                raise HTTPException(status_code=403, detail="ApiKey does not have required scope")

        return current_user

    return _dependency
