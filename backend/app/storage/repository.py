"""Idempotent insert-only persistence for pipeline stages."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.collector import RawRedditCapture
from backend.app.extractor import Complaint as ComplaintSchema
from backend.app.normalizer import NormalizedPost as NormalizedPostSchema
from backend.app.storage.models import Complaint, NormalizedPost, RawPost


@dataclass(frozen=True, slots=True)
class StageCounts:
    """Current row counts for each independently persisted stage."""

    raw_posts: int
    normalized_posts: int
    complaints: int


class SQLAlchemyStageStore:
    """Persist each pipeline stage in its own committed transaction."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save_raw(self, post: RawRedditCapture) -> UUID:
        """Insert a raw capture once and return its stable database id."""

        source = cast(Mapping[str, Any], post["source"])
        platform = str(source["platform"])
        external_id = str(source["external_id"])
        lookup = select(RawPost.id).where(
            RawPost.platform == platform,
            RawPost.external_id == external_id,
        )

        try:
            with self._session_factory.begin() as session:
                existing = session.scalar(lookup)
                if existing is not None:
                    return existing
                record = RawPost(
                    platform=platform,
                    external_id=external_id,
                    payload=dict(post),
                    fetched_at=self._timestamp(str(post["fetched_at"])),
                )
                session.add(record)
                session.flush()
                return record.id
        except IntegrityError:
            return self._existing_id(lookup)

    def save_normalized(
        self,
        post: NormalizedPostSchema,
        raw_post_id: UUID,
    ) -> UUID:
        """Insert a normalized document once without updating prior rows."""

        document_id = UUID(str(post["id"]))
        lookup = select(NormalizedPost.id).where(
            or_(
                NormalizedPost.raw_source_id == raw_post_id,
                NormalizedPost.id == document_id,
                (
                    (NormalizedPost.platform == str(post["platform"]))
                    & (NormalizedPost.external_id == str(post["external_id"]))
                ),
            )
        )

        try:
            with self._session_factory.begin() as session:
                existing = session.scalar(lookup)
                if existing is not None:
                    return existing
                record = NormalizedPost(
                    id=document_id,
                    raw_source_id=raw_post_id,
                    platform=str(post["platform"]),
                    external_id=str(post["external_id"]),
                    url=str(post["url"]),
                    title=str(post["title"]),
                    content=str(post["content"]),
                    comments=cast(
                        list[dict[str, Any]],
                        post["comments"],
                    ),
                    author=self._optional_string(post["author"]),
                    score=int(post["score"]),
                    community=self._optional_string(post.get("community")),
                    document_metadata=cast(
                        dict[str, Any],
                        post.get("metadata", {}),
                    ),
                    created_at=self._timestamp(str(post["created_at"])),
                    fetched_at=self._timestamp(str(post["fetched_at"])),
                )
                session.add(record)
                session.flush()
                return record.id
        except IntegrityError:
            return self._existing_id(lookup)

    def save_complaint(
        self,
        complaint: ComplaintSchema,
        normalized_post_id: UUID,
    ) -> UUID:
        """Insert an exact complaint result once as a versioned extraction."""

        if complaint.meta.document_id != normalized_post_id:
            raise ValueError("complaint document_id does not match normalized post")

        result = complaint.model_dump(mode="json")
        result_hash = self._content_hash(result)
        lookup = select(Complaint.id).where(
            Complaint.document_id == normalized_post_id,
            Complaint.result_hash == result_hash,
        )

        try:
            with self._session_factory.begin() as session:
                existing = session.scalar(lookup)
                if existing is not None:
                    return existing
                record = Complaint(
                    id=uuid4(),
                    document_id=normalized_post_id,
                    prompt_version=complaint.meta.prompt_version,
                    model=complaint.meta.model,
                    result=result,
                    result_hash=result_hash,
                    extracted_at=complaint.meta.extracted_at,
                )
                session.add(record)
                session.flush()
                return record.id
        except IntegrityError:
            return self._existing_id(lookup)

    def get_complaint(self, complaint_id: UUID) -> ComplaintSchema | None:
        """Load and strictly validate one persisted complaint."""

        with self._session_factory() as session:
            result = session.scalar(
                select(Complaint.result).where(Complaint.id == complaint_id)
            )
        if result is None:
            return None
        return ComplaintSchema.model_validate_json(json.dumps(result))

    def count_stages(self) -> StageCounts:
        """Return counts used by operational metrics."""

        with self._session_factory() as session:
            return StageCounts(
                raw_posts=session.scalar(select(func.count()).select_from(RawPost))
                or 0,
                normalized_posts=session.scalar(
                    select(func.count()).select_from(NormalizedPost)
                )
                or 0,
                complaints=session.scalar(select(func.count()).select_from(Complaint))
                or 0,
            )

    def check_health(self) -> None:
        """Raise if the database cannot execute a trivial query."""

        with self._session_factory() as session:
            session.execute(select(1))

    def _existing_id(self, lookup: Select[tuple[UUID]]) -> UUID:
        with self._session_factory() as session:
            existing = session.scalar(lookup)
            if existing is None:
                raise RuntimeError(
                    "idempotent insert conflicted without an existing row"
                )
            return existing

    @staticmethod
    def _timestamp(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @staticmethod
    def _optional_string(value: object | None) -> str | None:
        return None if value is None else str(value)

    @staticmethod
    def _content_hash(payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return sha256(canonical.encode("utf-8")).hexdigest()
