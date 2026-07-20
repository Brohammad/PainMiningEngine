"""Pipeline execution outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from backend.app.extractor import Complaint
from backend.app.storage.duplicates import DuplicateMatchType

ProcessingStatus = Literal["completed", "duplicate_skipped"]


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Complaint output plus duplicate and history metadata."""

    complaint: Complaint
    duplicate: bool = False
    duplicate_match: DuplicateMatchType | None = None
    processing_run_id: UUID | None = None
    complaint_id: UUID | None = None
    status: ProcessingStatus = "completed"
