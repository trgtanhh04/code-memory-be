from fastapi import Header, Request, HTTPException, Depends
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from datetime import datetime

from app.db.connect_db import get_db_session
from app.models.memory_models import ApiKey
from app.services.apikey_service import verify_secret


async def get_user_from_apikey(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key")
):
    raw = None
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization.split(" ", 1)[1].strip()
    elif x_api_key:
        raw = x_api_key
    else:
        raw = request.query_params.get("apiKey")

    if not raw:
        return None

    if "." not in raw:
        raise HTTPException(status_code=401, detail="Invalid apiKey format")
    key_id_str, secret = raw.split(".", 1)
    try:
        key_id = UUID(key_id_str)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid apiKey id")

    ak = await db.get(ApiKey, key_id)
    if not ak or ak.revoked:
        raise HTTPException(status_code=401, detail="ApiKey not found or revoked")

    if not verify_secret(secret, ak.hashed_secret):
        raise HTTPException(status_code=401, detail="Invalid apiKey secret")

    ak.last_used_at = datetime.utcnow()
    await db.flush()

    return {"user_id": ak.user_id, "api_key_id": ak.id, "scopes": ak.scopes}


def require_apikey(required_scope: Optional[str] = None):
    """Dependency factory that ensures an apiKey is present and optionally enforces a scope.

    Usage in route: current_user: dict = Depends(require_apikey('save'))
    """
    async def _dependency(current_user: Optional[dict] = Depends(get_user_from_apikey)):
        if not current_user:
            raise HTTPException(status_code=401, detail="Missing or invalid apiKey")

        if required_scope:
            scopes = current_user.get("scopes") or []
            # normalize scopes to strings
            if required_scope not in scopes:
                raise HTTPException(status_code=403, detail="ApiKey does not have required scope")

        return current_user

    return _dependency
