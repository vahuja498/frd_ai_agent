"""
Application Configuration
Loads environment variables safely (NO hardcoded secrets)
"""

import os
from urllib.parse import quote
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # -------------------------------
    # 🔗 Azure DevOps Configuration
    # -------------------------------
    ADO_ORG_URL: str = os.getenv("ADO_ORG_URL", "https://dev.azure.com/Dynamicssmartz")

    ADO_PROJECT: str = os.getenv("ADO_PROJECT", "Internal CRM")

    # ⚠️ DO NOT hardcode PAT here
    ADO_PAT: str = os.getenv("ADO_PAT")

    # -------------------------------
    # 🤖 AI Model Configuration
    # -------------------------------
    HF_API_TOKEN: str = os.getenv("HF_API_TOKEN")

    HF_MODEL: str = os.getenv("HF_MODEL", "HuggingFaceH4/zephyr-7b-beta")

    # -------------------------------
    # 🔐 Optional Security
    # -------------------------------
    WEBHOOK_SECRET: Optional[str] = os.getenv("WEBHOOK_SECRET")

    # -------------------------------
    # ⚙️ App Settings
    # -------------------------------
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "outputs")

    # -------------------------------
    # 🔧 Helpers
    # -------------------------------
    @property
    def ADO_PROJECT_ENCODED(self) -> str:
        return quote(self.ADO_PROJECT, safe="")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Singleton instance
settings = Settings()


# -------------------------------
# 🚨 Validate critical configs
# -------------------------------
def validate_settings():
    missing = []

    if not settings.ADO_PAT:
        missing.append("ADO_PAT")

    if not settings.HF_API_TOKEN:
        missing.append("HF_API_TOKEN")

    if missing:
        raise ValueError(
            f"❌ Missing required environment variables: {', '.join(missing)}"
        )


# Run validation at import
validate_settings()
