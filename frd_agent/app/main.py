"""
FRD AI Agent - Main Application Entry Point
Listens to Azure DevOps webhooks and generates FRD documents
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import webhook, health
from app.utils.logger import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 FRD AI Agent starting up...")
    yield
    logger.info("🛑 FRD AI Agent shutting down...")


app = FastAPI(
    title="FRD AI Agent",
    description="Automated Functional Requirements Document generator using Azure DevOps webhooks and HuggingFace LLM",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook.router, prefix="/api/v1", tags=["Webhook"])
app.include_router(health.router, tags=["Health"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
