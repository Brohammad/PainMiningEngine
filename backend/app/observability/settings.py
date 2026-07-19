"""Environment-backed observability settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ObservabilitySettings(BaseSettings):
    """Tracing and request-correlation configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="OBSERVABILITY_",
        extra="ignore",
    )

    service_name: str = "signalmine"
    service_version: str = "0.1.0"
    otlp_traces_endpoint: str | None = None
    trace_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    request_id_header: str = "X-Request-ID"
