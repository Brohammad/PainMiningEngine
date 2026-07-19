"""Strict Pydantic representations of the extraction contract."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Base model that rejects coercion and unknown fields."""

    model_config = ConfigDict(extra="forbid", strict=True)


class EvidenceSource(StrEnum):
    """Platforms permitted by the extraction JSON Schema."""

    REDDIT = "reddit"
    GITHUB = "github"
    HACKERNEWS = "hackernews"


class EvidenceField(StrEnum):
    """Normalized document fields that provenance may reference."""

    TITLE = "title"
    BODY = "body"
    COMMENT = "comment"


CharacterRange = Annotated[list[int], Field(min_length=2, max_length=2)]


class Provenance(StrictModel):
    """One exact evidence span in a normalized source document."""

    source: EvidenceSource
    field: EvidenceField
    comment_id: str | None = None
    character_range: CharacterRange
    confidence: Annotated[float, Field(ge=0, le=1)]

    @model_validator(mode="after")
    def validate_reference(self) -> Self:
        """Enforce range ordering and comment reference semantics."""

        start, end = self.character_range
        if start >= end:
            raise ValueError("character_range must satisfy start < end")
        if self.field is EvidenceField.COMMENT and self.comment_id is None:
            raise ValueError("comment_id is required for comment evidence")
        if self.field is not EvidenceField.COMMENT and self.comment_id is not None:
            raise ValueError("comment_id must be null for title or body evidence")
        return self


class TextField(StrictModel):
    """Nullable extracted text with supporting provenance."""

    value: str | None
    evidence: list[Provenance]

    @model_validator(mode="after")
    def validate_evidence_presence(self) -> Self:
        """Require evidence for claims and forbid it for null values."""

        if self.value is not None and not self.evidence:
            raise ValueError("non-null values require evidence")
        if self.value is None and self.evidence:
            raise ValueError("null values must not include evidence")
        return self


class TriStateField(StrictModel):
    """Budget ownership claim represented by the contract tri-state."""

    value: Literal["true", "false", "unknown"]
    evidence: list[Provenance]

    @model_validator(mode="after")
    def validate_evidence_presence(self) -> Self:
        """Require evidence for asserted true or false values."""

        if self.value != "unknown" and not self.evidence:
            raise ValueError("true or false budget ownership requires evidence")
        return self


class ToolMention(StrictModel):
    """Named existing tool with at least one source span."""

    name: Annotated[str, Field(min_length=1)]
    evidence: Annotated[list[Provenance], Field(min_length=1)]


class ComplaintCandidate(StrictModel):
    """Model-owned fields requested through Instructor."""

    pain_summary: TextField
    workflow: TextField
    workaround: TextField
    buyer: TextField
    budget_owner: TriStateField
    time_cost: TextField
    industry: TextField
    existing_tools: list[ToolMention]


class ExtractionMeta(StrictModel):
    """Host-owned extraction metadata."""

    model: Annotated[str, Field(min_length=1)]
    prompt_version: Annotated[str, Field(min_length=1)]
    source_id: str
    document_id: UUID
    extracted_at: datetime


class Complaint(ComplaintCandidate):
    """Complete extraction object matching ``schemas/extraction.json``."""

    meta: ExtractionMeta
