"""
Application Configuration
Reads from environment variables or .env file
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # ── Azure DevOps ──────────────────────────────
    ADO_ORG_URL: str = "https://dev.azure.com/your-org"
    ADO_PROJECT: str = "your-project"
    ADO_PAT: str = "your-ado-pat-token"

    # ── HuggingFace ───────────────────────────────
    HF_API_TOKEN: str = "hf_your_token_here"
    HF_MODEL: str = "mistralai/Mistral-7B-Instruct-v0.3"

    # ── Webhook Security (optional) ───────────────
    WEBHOOK_SECRET: Optional[str] = None

    # ── App ───────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    OUTPUT_DIR: str = "outputs"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
