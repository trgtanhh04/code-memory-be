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

# import secrets
# import logging
# from datetime import datetime
# from uuid import UUID, uuid4

# from passlib.context import CryptContext
# from passlib.exc import UnknownHashError
# from sqlalchemy.ext.asyncio import AsyncSession

# from app.models.memory_models import ApiKey

# logger = logging.getLogger(__name__)

# # Hỗ trợ nhiều scheme để nhận diện hash ở các môi trường khác nhau.
# # Bạn có thể giảm còn 1-2 scheme sau khi đã migrate hết.
# pwd_ctx = CryptContext(
#     schemes=["bcrypt", "argon2", "pbkdf2_sha256"],
#     deprecated="auto",
# )

# def _gen_secret(nbytes: int = 24) -> str:
#     return secrets.token_urlsafe(nbytes)

# def hash_secret(secret: str) -> str:
#     return pwd_ctx.hash(secret)

# def verify_secret(secret: str, hashed: str) -> bool:
#     """
#     Giữ nguyên signature để tương thích các chỗ gọi cũ.
#     Dùng verify_and_update() để:
#       - verify
#       - nếu cần thì đề xuất new_hash (không update DB trong hàm này)
#     """
#     try:
#         valid, _new_hash = pwd_ctx.verify_and_update(secret, hashed)
#         return bool(valid)
#     except UnknownHashError:
#         # Không nhận diện được format hash -> coi như không hợp lệ
#         # (tránh raise để không bắn 500 lên tầng request)
#         sample = (hashed[:16] + '...') if isinstance(hashed, str) else 'n/a'
#         logger.warning("Unknown hash format for API key (sample=%s)", sample)
#         return False
#     except ValueError as e:
#         # Phòng trường hợp backend bcrypt giới hạn 72 bytes hoặc lỗi format hiếm
#         msg = str(e)
#         if "72" in msg or "longer than 72" in msg:
#             try:
#                 truncated = secret.encode()[:72].decode(errors="ignore")
#                 valid, _ = pwd_ctx.verify_and_update(truncated, hashed)
#                 return bool(valid)
#             except Exception:
#                 return False
#         logger.exception("Passlib ValueError during verify: %s", e)
#         return False
#     except Exception as e:
#         logger.exception("Unexpected error during secret verification: %s", e)
#         return False

# async def verify_and_upgrade_secret(db: AsyncSession, api_key: ApiKey, secret: str) -> bool:
#     """
#     Khuyến nghị dùng: verify + nếu passlib đề xuất new_hash thì cập nhật DB.
#     Dùng trong deps khi bạn đã load được đối tượng ApiKey từ DB.
#     """
#     try:
#         valid, new_hash = pwd_ctx.verify_and_update(secret, api_key.hashed_secret)
#         if not valid:
#             return False
#         # Nếu passlib khuyến nghị nâng cấp hash -> cập nhật DB
#         if new_hash and new_hash != api_key.hashed_secret:
#             api_key.hashed_secret = new_hash
#             api_key.last_used_at = datetime.utcnow()
#             await db.flush()
#         return True
#     except UnknownHashError:
#         sample = (api_key.hashed_secret[:16] + '...') if isinstance(api_key.hashed_secret, str) else 'n/a'
#         logger.warning("Unknown hash format for API key (sample=%s)", sample)
#         return False
#     except ValueError as e:
#         msg = str(e)
#         if "72" in msg or "longer than 72" in msg:
#             try:
#                 truncated = secret.encode()[:72].decode(errors="ignore")
#                 valid, new_hash = pwd_ctx.verify_and_update(truncated, api_key.hashed_secret)
#                 if not valid:
#                     return False
#                 if new_hash and new_hash != api_key.hashed_secret:
#                     api_key.hashed_secret = new_hash
#                     api_key.last_used_at = datetime.utcnow()
#                     await db.flush()
#                 return True
#             except Exception:
#                 return False
#         logger.exception("Passlib ValueError during verify: %s", e)
#         return False
#     except Exception as e:
#         logger.exception("Unexpected error during verify_and_upgrade_secret: %s", e)
#         return False

# async def create_apikey(
#     db: AsyncSession,
#     user_id: UUID,
#     name: str = None,
#     project_id: UUID = None,
#     scopes: list = None
# ):
#     secret = _gen_secret()
#     api_key = ApiKey(
#         id=uuid4(),
#         user_id=user_id,
#         name=name,
#         hashed_secret=hash_secret(secret),
#         project_id=project_id,
#         scopes=scopes or []
#     )
#     db.add(api_key)
#     await db.flush()
#     full_key = f"{api_key.id}.{secret}"
#     return api_key, full_key

# async def revoke_apikey(db: AsyncSession, key_id):
#     ak = await db.get(ApiKey, key_id)
#     if not ak:
#         return None
#     ak.revoked = True
#     ak.last_used_at = datetime.utcnow()
#     await db.flush()
#     return ak
