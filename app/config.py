from typing import Optional
from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        case_sensitive=True,
        # add these only if you use a local .env file
        # env_file=".env",
        # env_file_encoding="utf-8",
    )

    # Azure DevOps
    ADO_ORG_URL: str = "https://dev.azure.com/Dynamicssmartz"
    ADO_PROJECT: str = "Internal CRM"
    ADO_PAT: str = ""

    # xAI / Grok
    XAI_API_KEY: str = ""
    GROK_MODEL: str = "llama-3.3-70b-versatile"

    # Optional Security
    WEBHOOK_SECRET: Optional[str] = None

    # App Settings
    LOG_LEVEL: str = "INFO"
    OUTPUT_DIR: str = "outputs"

    @property
    def ADO_PROJECT_ENCODED(self) -> str:
        return quote((self.ADO_PROJECT or "").strip(), safe="")

    @property
    def HAS_GROK(self) -> bool:
        return bool(
            (self.XAI_API_KEY or "").strip() and (self.GROK_MODEL or "").strip()
        )


settings = Settings()


def validate_settings() -> None:
    missing = []

    if not (settings.ADO_PAT or "").strip():
        missing.append("ADO_PAT")

    if not settings.HAS_GROK:
        missing.append("XAI_API_KEY")

    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}"
        )


def debug_settings() -> None:
    print("ADO ORG URL:", settings.ADO_ORG_URL)
    print("ADO PROJECT:", settings.ADO_PROJECT)
    print("ADO PAT SET:", bool((settings.ADO_PAT or "").strip()))
    print("GROK MODEL:", settings.GROK_MODEL)
    print(
        "XAI KEY PREFIX:",
        settings.XAI_API_KEY[:12] if settings.XAI_API_KEY else "EMPTY",
    )
    print("XAI KEY LENGTH:", len(settings.XAI_API_KEY or ""))
    print("GROK ENABLED:", settings.HAS_GROK)
