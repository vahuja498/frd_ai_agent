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
    ADO_PAT: str = os.getenv("ADO_PAT", "")

    # -------------------------------
    # 🤖 AI Model Configuration
    # -------------------------------
    # Primary LLM: Gemini
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
    HF_API_TOKEN: str = os.getenv("HF_API_TOKEN", "")
    HF_MODEL: str = os.getenv("HF_MODEL", "mistralai/Mistral-7B-Instruct-v0.2")

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

    @property
    def HAS_GEMINI(self) -> bool:
        return bool(self.GEMINI_API_KEY and self.GEMINI_MODEL)

    @property
    def HAS_HUGGINGFACE(self) -> bool:
        return bool(self.HF_API_TOKEN and self.HF_MODEL)

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

    # Require at least one LLM provider
    if not settings.HAS_GEMINI and not settings.HAS_HUGGINGFACE:
        missing.append("GEMINI_API_KEY or HF_API_TOKEN")

    if missing:
        raise ValueError(
            f"❌ Missing required environment variables: {', '.join(missing)}"
        )


# Run validation at import
validate_settings()
