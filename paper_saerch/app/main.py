from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from paper_saerch.app.api.routes import router
from paper_saerch.app.services.redis_runtime import close_redis_client


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_redis_client()


app = FastAPI(
    title="Paper Search Agent API",
    version="0.1.0",
    description="Independent backend API service for multi-source paper retrieval.",
    lifespan=lifespan,
)
app.include_router(router)
