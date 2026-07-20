"""Environment-backed configuration for the URL HTML collector."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class URLCollectorSettings(BaseSettings):
    """HTTP settings loaded from ``URL_COLLECTOR_*`` variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="URL_COLLECTOR_",
        extra="ignore",
    )

    user_agent: str = Field(
        default="signalmine-url-collector/1.0",
        min_length=1,
    )
    request_timeout_seconds: float = Field(default=15.0, gt=0)
