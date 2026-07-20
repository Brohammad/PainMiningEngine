"""HTTP request and response schemas."""

from datetime import datetime
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


class StageTraceResponse(ApiModel):
    """Timing and outcome for one pipeline stage."""

    stage: Literal["collector", "normalizer", "extractor", "validator", "storage"]
    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    status: Literal["success", "failure"]
    error: str | None = None
    operation: str | None = None


class PipelineTraceResponse(ApiModel):
    """Stage-by-stage record for one pipeline invocation."""

    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    status: Literal["success", "failure"]
    stages: list[StageTraceResponse]
    error: str | None = None


class ComplaintResponse(ApiModel):
    """Persisted complaint and its extraction row identifier."""

    id: UUID
    complaint: Complaint


class ProcessResponse(ApiModel):
    """Processed complaint with trace and processing history metadata."""

    id: UUID
    complaint: Complaint
    trace: PipelineTraceResponse
    duplicate: bool
    duplicate_match: Literal["url", "platform_id", "content_hash"] | None = None
    processing_run_id: UUID | None = None
    status: Literal["completed", "duplicate_skipped"]


class ProcessingRunResponse(ApiModel):
    """One persisted processing history record."""

    id: UUID
    input_url: str | None
    platform: str
    external_id: str
    normalized_content_hash: str | None
    normalized_document_id: UUID | None
    complaint_id: UUID | None
    status: Literal["completed", "duplicate_skipped"]
    duplicate_match: Literal["url", "platform_id", "content_hash"] | None = None
    started_at: datetime
    completed_at: datetime


class HealthResponse(ApiModel):
    """Database-backed service health."""

    status: Literal["ok"]
