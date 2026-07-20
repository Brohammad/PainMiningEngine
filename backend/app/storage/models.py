"""SQLAlchemy 2.x models for immutable pipeline stages."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    """Declarative base for SignalMine persistence models."""


class RawPost(Base):
    """Immutable raw source capture."""

    __tablename__ = "raw_sources"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "external_id",
            name="uq_raw_sources_platform_external_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    platform: Mapped[str] = mapped_column(String, nullable=False)
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT,
        nullable=False,
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class NormalizedPost(Base):
    """Immutable normalized document linked to one raw capture."""

    __tablename__ = "normalized_documents"
    __table_args__ = (
        UniqueConstraint(
            "raw_source_id",
            name="uq_normalized_documents_raw_source_id",
        ),
        UniqueConstraint(
            "platform",
            "external_id",
            name="uq_normalized_documents_platform_external_id",
        ),
        Index(
            "ix_normalized_documents_content_hash",
            "content_hash",
        ),
        Index(
            "ix_normalized_documents_url",
            "url",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    raw_source_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("raw_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    platform: Mapped[str] = mapped_column(String, nullable=False)
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    comments: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT,
        nullable=False,
    )
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    community: Mapped[str | None] = mapped_column(String, nullable=True)
    document_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON_DOCUMENT,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    normalized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Complaint(Base):
    """Immutable versioned extraction linked to a normalized document."""

    __tablename__ = "extractions"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "result_hash",
            name="uq_extractions_document_result_hash",
        ),
        Index(
            "ix_extractions_document_extracted_at",
            "document_id",
            "extracted_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("normalized_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    prompt_version: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    temperature: Mapped[float] = mapped_column(Float, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT,
        nullable=False,
    )
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class ProcessingRun(Base):
    """Processing history for idempotent pipeline execution."""

    __tablename__ = "processing_runs"
    __table_args__ = (
        Index(
            "ix_processing_runs_input_url",
            "input_url",
        ),
        Index(
            "ix_processing_runs_platform_external_id",
            "platform",
            "external_id",
        ),
        Index(
            "ix_processing_runs_content_hash",
            "normalized_content_hash",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    input_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform: Mapped[str] = mapped_column(String, nullable=False)
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    normalized_content_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    normalized_document_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("normalized_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    complaint_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("extractions.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    duplicate_match: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
