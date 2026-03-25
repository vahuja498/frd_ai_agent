from typing import Optional
from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Azure DevOps
    ADO_ORG_URL: str = "https://dev.azure.com/Dynamicssmartz"
    ADO_PROJECT: str = "Internal CRM"
    ADO_PAT: str = ""

    # AI Model Configuration
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"

    HF_API_TOKEN: str = ""
    HF_MODEL: str = "mistralai/Mistral-7B-Instruct-v0.2"

    # Optional Security
    WEBHOOK_SECRET: Optional[str] = None

    # App Settings
    LOG_LEVEL: str = "INFO"
    OUTPUT_DIR: str = "outputs"

    @property
    def ADO_PROJECT_ENCODED(self) -> str:
        return quote(self.ADO_PROJECT, safe="")

    @property
    def HAS_GEMINI(self) -> bool:
        return bool(self.GEMINI_API_KEY.strip() and self.GEMINI_MODEL.strip())

    @property
    def HAS_HUGGINGFACE(self) -> bool:
        return bool(self.HF_API_TOKEN.strip() and self.HF_MODEL.strip())


settings = Settings()


def validate_settings() -> None:
    missing = []

    if not settings.ADO_PAT:
        missing.append("ADO_PAT")

    if not settings.HAS_GEMINI and not settings.HAS_HUGGINGFACE:
        missing.append("GEMINI_API_KEY or HF_API_TOKEN")

    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}"
        )
