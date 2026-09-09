"""FastAPI application entrypoint.

Wires up settings, structured logging, CORS, RFC 7807 error handlers and the
v1 API router. Kept deliberately thin — anything more than app wiring belongs
in `app.core` or `app.services`.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger

settings = get_settings()
configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("startup", app_env=settings.app_env, llm_backend=settings.llm_backend)
    yield
    logger.info("shutdown")


app = FastAPI(
    title="Manak Sahayak API",
    description=(
        "AI-assisted access to Indian Standards and BIS certification "
        "services. See /docs for the interactive schema."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(api_router)
