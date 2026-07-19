"""HTTP request and response schemas."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, HttpUrl

from backend.app.schemas import Complaint


class ApiModel(BaseModel):
    """API model that rejects unknown properties."""

    model_config = ConfigDict(extra="forbid")


class ProcessRequest(ApiModel):
    """Request to process one Reddit URL."""

    url: HttpUrl


class ComplaintResponse(ApiModel):
    """Persisted complaint and its extraction row identifier."""

    id: UUID
    complaint: Complaint


class HealthResponse(ApiModel):
    """Database-backed service health."""

    status: Literal["ok"]


class MetricsResponse(ApiModel):
    """Current persisted stage counts."""

    raw_posts: int
    normalized_posts: int
    complaints: int
