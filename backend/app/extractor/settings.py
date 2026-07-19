"""Environment-backed configuration for the extraction engine."""

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExtractionSettings(BaseSettings):
    """OpenAI-compatible client settings loaded from ``EXTRACTION_*`` variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="EXTRACTION_",
        extra="ignore",
    )

    api_key: SecretStr
    model: str = Field(min_length=1)
    base_url: str | None = None
    instructor_mode: Literal["tools", "json", "json_schema"] = "tools"
    timeout_seconds: float = Field(default=60.0, gt=0)
    validation_retries: int = Field(default=2, ge=0, le=10)
