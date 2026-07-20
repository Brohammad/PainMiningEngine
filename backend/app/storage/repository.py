"""Idempotent insert-only persistence for pipeline stages."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import Select, desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.collector.types import RawDiscussion
from backend.app.source_identity import normalize_lookup_url
from backend.app.extractor import Complaint as ComplaintSchema
from backend.app.normalizer import NormalizedPost as NormalizedPostSchema
from backend.app.storage.duplicates import DuplicateMatch, DuplicateMatchType
from backend.app.storage.hash import content_hash, normalized_content_hash
from backend.app.storage.models import Complaint, NormalizedPost, ProcessingRun, RawPost

ProcessingStatus = Literal["completed", "duplicate_skipped"]


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

    def save_raw(self, discussion: RawDiscussion) -> UUID:
        """Insert a raw capture once and return its stable database id."""

        platform = str(discussion["source"])
        external_id = str(discussion["discussion_id"])
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
                    payload=dict(discussion),
                    fetched_at=self._timestamp(str(discussion["fetched_at"])),
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
                    content_hash=normalized_content_hash(post),
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
        result_hash = content_hash(result)
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
                    provider=complaint.meta.provider,
                    temperature=complaint.meta.temperature,
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

    def find_duplicate(
        self,
        *,
        url: str | None = None,
        platform: str | None = None,
        external_id: str | None = None,
        content_hash_value: str | None = None,
    ) -> DuplicateMatch | None:
        """Return the latest completed processing result for one duplicate key."""

        if url is not None:
            match = self._find_duplicate_by_url(url)
            if match is not None:
                return match
        if platform is not None and external_id is not None:
            match = self._find_duplicate_by_platform_id(platform, external_id)
            if match is not None:
                return match
        if content_hash_value is not None:
            return self._find_duplicate_by_content_hash(content_hash_value)
        return None

    def record_processing_run(
        self,
        *,
        input_url: str | None,
        platform: str,
        external_id: str,
        normalized_content_hash: str | None,
        normalized_document_id: UUID | None,
        complaint_id: UUID | None,
        status: ProcessingStatus,
        duplicate_match: DuplicateMatchType | None,
        started_at: datetime,
        completed_at: datetime,
    ) -> UUID:
        """Persist one processing attempt."""

        with self._session_factory.begin() as session:
            record = ProcessingRun(
                input_url=input_url,
                platform=platform,
                external_id=external_id,
                normalized_content_hash=normalized_content_hash,
                normalized_document_id=normalized_document_id,
                complaint_id=complaint_id,
                status=status,
                duplicate_match=duplicate_match,
                started_at=started_at,
                completed_at=completed_at,
            )
            session.add(record)
            session.flush()
            return record.id

    def get_processing_run(self, run_id: UUID) -> ProcessingRun | None:
        """Load one processing history record."""

        with self._session_factory() as session:
            return session.get(ProcessingRun, run_id)

    def _find_duplicate_by_url(self, url: str) -> DuplicateMatch | None:
        lookup_url = normalize_lookup_url(url)
        with self._session_factory() as session:
            document_id = session.scalar(
                select(NormalizedPost.id)
                .where(NormalizedPost.url == lookup_url)
                .order_by(desc(NormalizedPost.normalized_at))
                .limit(1)
            )
            if document_id is None:
                document_id = session.scalar(
                    select(ProcessingRun.normalized_document_id)
                    .where(
                        ProcessingRun.input_url == lookup_url,
                        ProcessingRun.status == "completed",
                        ProcessingRun.complaint_id.is_not(None),
                    )
                    .order_by(desc(ProcessingRun.completed_at))
                    .limit(1)
                )
        if document_id is None:
            return None
        return self._match_for_document(document_id, "url")

    def _find_duplicate_by_platform_id(
        self,
        platform: str,
        external_id: str,
    ) -> DuplicateMatch | None:
        with self._session_factory() as session:
            document_id = session.scalar(
                select(NormalizedPost.id).where(
                    NormalizedPost.platform == platform,
                    NormalizedPost.external_id == external_id,
                )
            )
        if document_id is None:
            return None
        return self._match_for_document(document_id, "platform_id")

    def _find_duplicate_by_content_hash(
        self,
        content_hash_value: str,
    ) -> DuplicateMatch | None:
        if not content_hash_value:
            return None
        with self._session_factory() as session:
            document_id = session.scalar(
                select(NormalizedPost.id)
                .where(
                    NormalizedPost.content_hash == content_hash_value,
                    NormalizedPost.content_hash != "",
                )
                .order_by(desc(NormalizedPost.normalized_at))
                .limit(1)
            )
        if document_id is None:
            return None
        return self._match_for_document(document_id, "content_hash")

    def _match_for_document(
        self,
        document_id: UUID,
        match_type: DuplicateMatchType,
    ) -> DuplicateMatch | None:
        latest = self._get_latest_complaint_for_document(document_id)
        if latest is None:
            return None
        complaint_id, complaint = latest
        return DuplicateMatch(
            match_type=match_type,
            normalized_document_id=document_id,
            complaint_id=complaint_id,
            complaint=complaint,
        )

    def _get_latest_complaint_for_document(
        self,
        document_id: UUID,
    ) -> tuple[UUID, ComplaintSchema] | None:
        with self._session_factory() as session:
            row = session.execute(
                select(Complaint.id, Complaint.result)
                .where(Complaint.document_id == document_id)
                .order_by(desc(Complaint.extracted_at))
                .limit(1)
            ).one_or_none()
        if row is None:
            return None
        complaint_id, result = row
        return complaint_id, ComplaintSchema.model_validate_json(json.dumps(result))

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
