import secrets
from datetime import datetime
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID, uuid4

from app.models.memory_models import ApiKey

pwd_ctx = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def _gen_secret(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_secret(secret: str) -> str:
    return pwd_ctx.hash(secret)


def verify_secret(secret: str, hashed: str) -> bool:
    try:
        return pwd_ctx.verify(secret, hashed)
    except ValueError as e:
        # bcrypt backend can raise ValueError when password > 72 bytes.
        msg = str(e)
        if "72" in msg or "longer than 72" in msg:
            try:
                # Truncate to bcrypt's 72-byte limit and retry. This mirrors
                # bcrypt's historical behavior of truncating passwords.
                truncated = secret.encode()[:72].decode(errors="ignore")
                return pwd_ctx.verify(truncated, hashed)
            except Exception:
                return False
        raise
    except AttributeError as e:
        # This can happen if the bcrypt backend is not properly installed
        # or is an incompatible build. Log and fall back to a safe failure.
        # The caller should handle a False return (authentication failure).
        try:
            import logging
            logger = logging.getLogger(__name__)
            # If the stored hash looks like a bcrypt hash, indicate that it
            # requires migration. We cannot verify bcrypt hashes reliably
            # if the bcrypt C backend is broken in the environment.
            if isinstance(hashed, str) and hashed.startswith(('$2b$', '$2a$', '$2y$')):
                logger.error("Detected legacy bcrypt hash but bcrypt backend is unavailable; consider migrating this API key to pbkdf2_sha256: %s", e)
            else:
                logger.error("Password verify failed due to bcrypt/backend issue: %s", e)
        except Exception:
            pass
        return False

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
