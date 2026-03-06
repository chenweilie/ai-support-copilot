"""
App configuration using pydantic-settings.
All values can be overridden via environment variables or .env file.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "AI Support Copilot"
    version: str = "1.0.0"
    debug: bool = False
    log_level: str = "INFO"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Google Sheets
    google_creds_json: str = ""          # JSON string of service account credentials
    google_creds_path: str = "credentials.json"
    google_sheet_id: str = ""
    google_sheet_name: str = "Tickets"

    # Slack
    slack_bot_token: str = ""
    slack_channel: str = "#support-copilot"
    slack_signing_secret: str = ""

    # Pipeline thresholds
    confidence_threshold: float = 0.75
    max_retries: int = 3


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
