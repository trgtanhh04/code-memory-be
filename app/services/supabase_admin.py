from typing import Optional
import logging
import httpx
from config.config import SUPABASE_URL, SERVICE_ROLE_KEY

logger = logging.getLogger(__name__)

async def create_supabase_user(email: str, name: str = None):
    url = f"{SUPABASE_URL}/auth/v1/admin/users"
    headers = {
        "apikey": SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "email": email,
        "user_metadata": {
            "full_name": name if name else ""
        },
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code in (200, 201):
                user_data = response.json()
                supa_id = user_data.get('id')
                logger.info(f"Supabase user created: {user_data['id']}")
                return supa_id
            else:
                raise Exception(f"Failed to create Supabase user: {response.status_code} - {response.text}")
    except httpx.RequestError as e:
        logger.error(f"HTTP request error while creating Supabase user: {e}")
        raise

