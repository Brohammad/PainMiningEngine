"""Source-agnostic duplicate match records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from backend.app.extractor import Complaint as ComplaintSchema

DuplicateMatchType = Literal["url", "platform_id", "content_hash"]


@dataclass(frozen=True, slots=True)
class DuplicateMatch:
    """One previously processed discussion that should not be reprocessed."""

    match_type: DuplicateMatchType
    normalized_document_id: UUID
    complaint_id: UUID
    complaint: ComplaintSchema
