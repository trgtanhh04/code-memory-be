from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from app.db.connect_db import get_db_session
from app.models.memory_models import User
from sqlalchemy.future import select
from config.config import SUPABASE_WEBHOOK_SECRET
import hmac
import hashlib
import json
import logging


router = APIRouter(prefix="/api/v1/supabase", tags=["supabase"])
logger = logging.getLogger(__name__)


@router.post("/user_created")
async def user_created(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    try:
        # Read body first
        body = await request.body()

        # signature header optional depending on config
        signature = request.headers.get("x-supabase-signature") or request.headers.get("X-Supabase-Signature")
        static_secret = request.headers.get("x-webhook-secret") or request.headers.get("X-Webhook-Secret")

        # If SUPABASE_WEBHOOK_SECRET is set, accept either:
        # - X-Webhook-Secret matching the configured secret (static header added via Supabase UI), or
        # - X-Supabase-Signature HMAC signature computed by a forwarder/edge function
        if SUPABASE_WEBHOOK_SECRET:
            if static_secret and static_secret == SUPABASE_WEBHOOK_SECRET:
                logger.debug("Received static webhook secret header; accepted")
            else:
                if not signature:
                    logger.warning("Missing signature header for webhook")
                    raise HTTPException(status_code=400, detail="Missing signature header")
                if not verify_signature(signature, body):
                    logger.warning("Invalid webhook signature")
                    raise HTTPException(status_code=403, detail="Invalid signature")
        else:
            logger.debug("SUPABASE_WEBHOOK_SECRET not set; skipping signature verification")

        payload = json.loads(body)

        # accept multiple payload shapes
        user_data = payload.get("record") or payload.get("new") or payload.get("data") or payload.get("user")
        if not user_data or not isinstance(user_data, dict):
            logger.warning("Webhook payload missing user data: %s", payload)
            raise HTTPException(status_code=400, detail="Missing user data in payload")

        supabase_user_id = user_data.get("id")
        email = user_data.get("email")
        metadata = user_data.get("user_metadata") or {}
        full_name = metadata.get("full_name") if isinstance(metadata, dict) else user_data.get("name")

        # Lookup by supabase_user_id first
        existing_user = None
        if supabase_user_id:
            res = await db.execute(select(User).where(User.supabase_user_id == supabase_user_id))
            existing_user = res.scalar_one_or_none()

        # If not found, lookup by email and merge
        if not existing_user and email:
            res = await db.execute(select(User).where(User.email == email))
            existing_user = res.scalar_one_or_none()

        if existing_user:
            changed = False
            if supabase_user_id and existing_user.supabase_user_id != supabase_user_id:
                existing_user.supabase_user_id = supabase_user_id
                changed = True
            if full_name and existing_user.name != full_name:
                existing_user.name = full_name
                changed = True
            if changed:
                await db.flush()
                logger.info("Updated existing user from webhook: %s", existing_user.id)
            return {"status": "user exists", "user_id": str(existing_user.id)}

        # create new local user, guard against race conditions using IntegrityError
        new_user = User(supabase_user_id=supabase_user_id, email=email, name=full_name)
        db.add(new_user)
        try:
            await db.commit()
            await db.refresh(new_user)
            logger.info("Created new user from webhook: %s", new_user.id)
            return {"status": "user created", "user_id": str(new_user.id)}
        except IntegrityError:
            # rollback and try to find existing user by email (concurrent insert)
            await db.rollback()
            res = await db.execute(select(User).where(User.email == email))
            existing_user = res.scalar_one_or_none()
            if existing_user:
                if supabase_user_id and existing_user.supabase_user_id != supabase_user_id:
                    existing_user.supabase_user_id = supabase_user_id
                    await db.flush()
                return {"status": "user exists", "user_id": str(existing_user.id)}
            raise

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error processing user_created webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


def verify_signature(signature: str, body: bytes) -> bool:
    if not SUPABASE_WEBHOOK_SECRET:
        return False
    secret = SUPABASE_WEBHOOK_SECRET.encode("utf-8")
    expected_signature = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected_signature)
