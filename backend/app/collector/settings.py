"""Environment-backed configuration for the Reddit collector."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class RedditSettings(BaseSettings):
    """PRAW and retry settings loaded from ``REDDIT_*`` variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="REDDIT_",
        extra="ignore",
    )

    client_id: str = Field(min_length=1)
    client_secret: SecretStr
    user_agent: str = Field(min_length=1)
    request_timeout_seconds: int = Field(default=10, gt=0)
    rate_limit_wait_seconds: int = Field(default=60, ge=0)
    retry_attempts: int = Field(default=3, ge=1, le=10)
    retry_backoff_seconds: float = Field(default=1.0, ge=0)
    comment_limit: int = Field(default=20, ge=0)
    comment_max_depth: int = Field(default=3, ge=0)
