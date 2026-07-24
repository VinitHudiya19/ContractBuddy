"""
FastAPI application entrypoint.
Sets up lifespan, middleware, exception handlers, API routing, and static frontend serving.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.v1 import admin, auth, contracts, conversations, documents, health, users
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.qdrant_client import close_qdrant, ensure_collection
from app.db.redis_client import close_redis
from app.middleware.error_handler import register_exception_handlers

configure_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "starting backend server",
        extra={
            "env": settings.app_env,
            "llm_provider": settings.llm_provider,
            "embedding_provider": settings.embedding_provider,
        },
    )
    try:
        await ensure_collection()
    except Exception as exc:
        logger.error("qdrant server not reachable at startup", extra={"error": str(exc)})
    yield
    await close_redis()
    await close_qdrant()
    logger.info("shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Multi-tenant RAG Document Q&A backend service",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)

register_exception_handlers(app)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(documents.router)
app.include_router(documents.reindex_router)
app.include_router(conversations.router)
app.include_router(admin.router)
app.include_router(contracts.router)

frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
