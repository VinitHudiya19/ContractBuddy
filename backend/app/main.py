"""
FastAPI application entrypoint.
Sets up lifespan, middleware, exception handlers, API routing, and static frontend serving.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.v1 import auth, contracts, conversations, documents, health, users
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.redis_client import close_redis
from app.db.session import create_tables_if_missing
from app.db.vector_store import close_vector_store, init_vector_store
from app.middleware.error_handler import register_exception_handlers
from app.providers.factory import get_llm
from app.services.bootstrap import warm_models

configure_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "starting backend server",
        extra={
            "env": settings.app_env,
            "database": "sqlite" if settings.is_sqlite else "postgresql",
            "llm": get_llm().name,
        },
    )

    # SQLite (local mode) has no migration step, so create anything missing.
    # Postgres deployments run `alembic upgrade head` from the entrypoint.
    if settings.is_sqlite:
        await create_tables_if_missing()

    # Picks Qdrant when reachable, otherwise the built-in SQL vector store.
    store = await init_vector_store()

    # Detached: the API serves immediately while the models load in the
    # background, so the first question doesn't pay the model load.
    warmup = asyncio.create_task(warm_models())

    logger.info("startup complete", extra={"vector_store": store.name, "docs": "/docs"})
    yield

    warmup.cancel()
    await close_redis()
    await close_vector_store()
    logger.info("shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Contract Q&A over your own PDF and DOCX contracts, with page-level citations",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

_cors_origins = settings.cors_origin_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    # Browsers reject `Access-Control-Allow-Origin: *` together with
    # credentials. Auth here is a Bearer header, not a cookie, so dropping
    # credentials when a wildcard is configured costs nothing.
    allow_credentials="*" not in _cors_origins,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
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
app.include_router(contracts.router)

# Serve the static UI from the same origin as the API, which keeps CORS out of
# the picture entirely. Mounted last so it never shadows an API route.
# Two layouts: a repo checkout (<repo>/frontend) and the container (/app/frontend).
_here = Path(__file__).resolve()
for candidate in (_here.parents[2] / "frontend", _here.parents[1] / "frontend"):
    if candidate.is_dir():
        app.mount("/", StaticFiles(directory=str(candidate), html=True), name="frontend")
        logger.info("serving frontend", extra={"path": str(candidate)})
        break
else:
    logger.warning("frontend directory not found; API-only mode")
