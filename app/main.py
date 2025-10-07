import logging
import sys
import os
from contextlib import asynccontextmanager
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.connect_db import db_manager, initialize_all_databases
from app.api.memory_routes import router as memory_router
from app.api.project_routes import router as project_router
from app.api.apikey_routes import router as apikey_router
from app.api.user_routes import router as user_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting CodeMemory Backend...")
    
    try:
        # Initialize database connections
        success = await initialize_all_databases()
        if success:
            logger.info("Database connections initialized")
        else:
            logger.error("Failed to initialize databases")
    except Exception as e:
        logger.error(f"Startup error: {e}")

    yield
    
    # Shutdown
    logger.info("Shutting down CodeMemory Backend...")
    try:
        await db_manager.close_connections()
        logger.info("Database connections closed")
    except Exception as e:
        logger.error(f"Shutdown error: {e}")


app = FastAPI(
    title="CodeMemory Backend",
    description="An intelligent memory system for AI coding agents",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(memory_router)
app.include_router(project_router)
app.include_router(apikey_router)
app.include_router(user_router)


@app.get("/")
async def root():
    return {"message": "CodeMemory Backend API", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    try:
        health_status = await db_manager.test_connections()
        
        return {
            "status": "healthy" if health_status else "unhealthy",
            "services": {
                "postgresql": "up" if health_status else "down",
                "redis": "up" if health_status else "down"
            }
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")