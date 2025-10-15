import secrets
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID, uuid4

from app.models.memory_models import ApiKey, User
from fastapi import HTTPException, status


def _gen_secret(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)

def verify_secret(secret: str, stored: str) -> bool:
    if stored is None:
        return False
    return secret == stored

async def create_apikey(db: AsyncSession, user_id: UUID, name: str = None, scopes: list = None):
    secret = _gen_secret()
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {user_id} has not been created"
        )

    api_key = ApiKey(
        id=uuid4(),
        user_id=user_id,
        name=name,
        hashed_secret=f"{uuid4()}.{secret}",
        scopes=scopes or []
    )
    db.add(api_key)
    await db.flush()
    full_key = api_key.hashed_secret
    return api_key, full_key

async def revoke_apikey(db: AsyncSession, key_id):
    ak = await db.get(ApiKey, key_id)
    if not ak:
        return None
    ak.revoked = True
    ak.last_used_at = datetime.utcnow()
    await db.flush()
    return ak

async def unrevoke_apikey(db: AsyncSession, key_id):
    ak = await db.get(ApiKey, key_id)
    if not ak:
        return None
    ak.revoked = False
    ak.last_used_at = datetime.utcnow()
    await db.flush()
    return ak


async def delete_apikey(db: AsyncSession, key_id):
    ak = await db.get(ApiKey, key_id)
    if not ak:
        return None
    await db.delete(ak)
    await db.flush()
    return ak