"""GitHub collector settings."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class GitHubSettings(BaseSettings):
    """Environment-backed settings for the GitHub REST collector."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="GITHUB_",
        extra="ignore",
    )

    token: SecretStr | None = None
    user_agent: str = "signalmine-github-collector/1.0"
    request_timeout_seconds: float = 15.0
    comment_limit: int = 50
    retry_attempts: int = 3
    retry_backoff_seconds: float = 1.0
    api_base_url: str = "https://api.github.com"
