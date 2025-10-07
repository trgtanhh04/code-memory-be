import secrets
from datetime import datetime
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID, uuid4

from app.models.memory_models import ApiKey

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

def _gen_secret(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_secret(secret: str) -> str:
    return pwd_ctx.hash(secret)


def verify_secret(secret: str, hashed: str) -> bool:
    return pwd_ctx.verify(secret, hashed)

async def create_apikey(db: AsyncSession, user_id: UUID, name: str = None, project_id: UUID = None, scopes: list = None):
    secret = _gen_secret()
    api_key = ApiKey(
        id=uuid4(),
        user_id=user_id,
        name=name,
        hashed_secret=hash_secret(secret),
        project_id=project_id,
        scopes=scopes or []
    )
    db.add(api_key)
    await db.flush()
    full_key = f"{api_key.id}.{secret}"
    return api_key, full_key


async def revoke_apikey(db: AsyncSession, key_id):
    ak = await db.get(ApiKey, key_id)
    if not ak:
        return None
    ak.revoked = True
    ak.last_used_at = datetime.utcnow()
    await db.flush()
    return ak
