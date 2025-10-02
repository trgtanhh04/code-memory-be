import asyncio
import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import redis
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import text
from typing import AsyncGenerator, Optional
import logging

from config.config import (
    DATABASE_URL,  
    REDIS_URL,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Enable Redis logging
redis_logger = logging.getLogger('redis')
redis_logger.setLevel(logging.DEBUG)

Base = declarative_base()

class DatabaseManager:

    def __init__(self):
        self.pg_engine = None
        self.async_pg_engine = None
        self.async_session_factory = None
        self.redis_client = None
        self.redis_async_client = None
    
    async def initialize_postgresql(self) -> bool:
        try:
            self.async_pg_engine = create_async_engine(
                DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"),
                echo=False,
                pool_pre_ping=True,
                pool_recycle=3600
            )
            
            self.async_session_factory = sessionmaker(
                bind=self.async_pg_engine,
                class_=AsyncSession,
                expire_on_commit=False
            )
            
            async with self.async_pg_engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            
            logger.info("PostgreSQL connection initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL: {e}")
            return False
    
    def initialize_redis(self) -> bool:
        """Initialize Redis connection with retry logic"""
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                if not REDIS_URL:
                    logger.warning("REDIS_URL not configured")
                    return False

                logger.info(f"Redis connection attempt {attempt + 1}/{max_retries}")
                
                # Create connection with optimized settings for Upstash
                self.redis_client = redis.from_url(
                    REDIS_URL,
                    decode_responses=True,
                    socket_keepalive=True,
                    socket_keepalive_options={},
                    socket_connect_timeout=10,  # 10s connect timeout
                    socket_timeout=5,           # 5s read timeout
                    retry_on_timeout=True,
                    health_check_interval=30    # Health check every 30s
                )
                
                # Test connection with ping
                logger.info("Testing Redis connection with PING...")
                ping_result = self.redis_client.ping()
                logger.info(f"Redis PING successful: {ping_result}")
                
                # Test basic operations
                test_key = "connection_test"
                self.redis_client.setex(test_key, 10, "test_value")
                test_value = self.redis_client.get(test_key)
                logger.info(f"Redis test operation: {test_value}")
                
                logger.info("Redis connection initialized successfully")
                return True
                
            except redis.ConnectionError as e:
                logger.warning(f"Redis connection attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    logger.error("All Redis connection attempts failed")
                    return False
                    
            except Exception as e:
                logger.error(f"Redis initialization error: {e}")
                return False
        
        return False

    
    async def get_async_session(self) -> AsyncSession:
        if not self.async_session_factory:
            await self.initialize_postgresql()
        return self.async_session_factory()
    
    def get_redis_client(self) -> redis.Redis:
        if not self.redis_client:
            self.initialize_redis()
        return self.redis_client
    
    async def close_connections(self):
        try:
            if self.async_pg_engine:
                await self.async_pg_engine.dispose()
                logger.info("PostgreSQL connections closed")
            
            if self.redis_client:
                self.redis_client.close()
                logger.info("Redis connections closed")
                
        except Exception as e:
            logger.error(f"Error closing connections: {e}")

# Connect to databases
db_manager = DatabaseManager()

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    session = await db_manager.get_async_session()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

def get_redis() -> Optional[redis.Redis]:
    """Get Redis client - returns None if Redis not available"""
    try:
        return db_manager.get_redis_client()
    except Exception as e:
        logger.warning(f"Redis not available: {e}")
        return None

async def initialize_all_databases():
    pg_success = await db_manager.initialize_postgresql()
    redis_success = db_manager.initialize_redis()
    if pg_success and redis_success:
        logger.info("All databases initialized successfully!")
        return True
    else:
        logger.error("Some database connections failed")
        return False

if __name__ == "__main__":
    async def main():
        success = await initialize_all_databases()
        await db_manager.close_connections()
        return success

