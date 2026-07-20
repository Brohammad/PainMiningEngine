"""Direct synchronous orchestration for the V1 pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from backend.app.collector.source_collector import SourceCollector
from backend.app.collector.types import RawDiscussion
from backend.app.extractor import Complaint
from backend.app.normalizer import DiscussionNormalizer, NormalizedPost
from backend.app.observability import NoOpTelemetry, TelemetryRecorder
from backend.app.pipeline.result import PipelineResult
from backend.app.source_identity import DiscussionIdentityResolver
from backend.app.storage.duplicates import DuplicateMatch, DuplicateMatchType
from backend.app.storage.hash import normalized_content_hash


class Extractor(Protocol):
    """Extractor dependency required by the pipeline."""

    def extract(self, normalized: NormalizedPost) -> Complaint: ...


class Validator(Protocol):
    """Final validator dependency required by the pipeline."""

    def validate(
        self,
        complaint: Complaint,
        normalized: NormalizedPost,
    ) -> Complaint: ...


class StageStorage(Protocol):
    """Independent insert-only persistence required by a durable pipeline."""

    def save_raw(self, discussion: RawDiscussion) -> UUID: ...

    def save_normalized(
        self,
        post: NormalizedPost,
        raw_post_id: UUID,
    ) -> UUID: ...

    def save_complaint(
        self,
        complaint: Complaint,
        normalized_post_id: UUID,
    ) -> UUID: ...

    def find_duplicate(
        self,
        *,
        url: str | None = None,
        platform: str | None = None,
        external_id: str | None = None,
        content_hash_value: str | None = None,
    ) -> DuplicateMatch | None: ...

    def record_processing_run(
        self,
        *,
        input_url: str | None,
        platform: str,
        external_id: str,
        normalized_content_hash: str | None,
        normalized_document_id: UUID | None,
        complaint_id: UUID | None,
        status: str,
        duplicate_match: DuplicateMatchType | None,
        started_at: datetime,
        completed_at: datetime,
    ) -> UUID: ...


class SynchronousPipeline:
    """Run collector → normalizer → extractor → validator in the caller."""

    def __init__(
        self,
        collector: SourceCollector,
        normalizer: DiscussionNormalizer,
        extractor: Extractor,
        validator: Validator,
        storage: StageStorage | None = None,
        telemetry: TelemetryRecorder | None = None,
        identity_resolver: DiscussionIdentityResolver | None = None,
    ) -> None:
        self._collector = collector
        self._normalizer = normalizer
        self._extractor = extractor
        self._validator = validator
        self._storage = storage
        self._telemetry = telemetry or NoOpTelemetry()
        self._identity_resolver = identity_resolver

    def process_url(self, url: str) -> PipelineResult:
        """Collect and process one source URL synchronously."""

        run_started_at = datetime.now(UTC)
        with self._telemetry.pipeline_run():
            if self._storage is not None:
                duplicate = self._find_duplicate(url=url)
                if duplicate is not None:
                    return self._skip_duplicate(
                        duplicate,
                        input_url=url,
                        run_started_at=run_started_at,
                    )
                identity = (
                    self._identity_resolver.resolve_url(url)
                    if self._identity_resolver is not None
                    else None
                )
                if identity is not None:
                    duplicate = self._storage.find_duplicate(
                        platform=identity.source,
                        external_id=identity.discussion_id,
                    )
                    if duplicate is not None:
                        return self._skip_duplicate(
                            duplicate,
                            input_url=url,
                            run_started_at=run_started_at,
                            platform=identity.source,
                            external_id=identity.discussion_id,
                        )

            with self._telemetry.pipeline_stage("collect"):
                discussion = self._collector.fetch(url)
            return self._process_discussion(
                discussion,
                input_url=url,
                run_started_at=run_started_at,
            )

    def process_discussion(self, discussion: RawDiscussion) -> PipelineResult:
        """Process one already-collected RawDiscussion synchronously."""

        run_started_at = datetime.now(UTC)
        with self._telemetry.pipeline_run():
            return self._process_discussion(discussion, run_started_at=run_started_at)

    def process_post(self, discussion: RawDiscussion) -> PipelineResult:
        """Backward-compatible alias for :meth:`process_discussion`."""

        return self.process_discussion(discussion)

    def _process_discussion(
        self,
        discussion: RawDiscussion,
        *,
        input_url: str | None = None,
        run_started_at: datetime | None = None,
    ) -> PipelineResult:
        started_at = run_started_at or datetime.now(UTC)
        platform = str(discussion["source"])
        discussion_id = str(discussion["discussion_id"])

        if self._storage is not None:
            duplicate = self._find_duplicate(
                url=input_url,
                platform=platform,
                external_id=discussion_id,
            )
            if duplicate is not None:
                return self._skip_duplicate(
                    duplicate,
                    input_url=input_url,
                    run_started_at=started_at,
                    platform=platform,
                    external_id=discussion_id,
                )

        raw_post_id = None
        if self._storage is not None:
            with self._telemetry.pipeline_stage("persist_raw"):
                raw_post_id = self._storage.save_raw(discussion)
        with self._telemetry.pipeline_stage("normalize"):
            normalized = self._normalizer.normalize(discussion)
        content_hash = normalized_content_hash(normalized)

        if self._storage is not None:
            duplicate = self._storage.find_duplicate(content_hash_value=content_hash)
            if duplicate is not None:
                normalized_post_id = (
                    self._save_normalized(normalized, raw_post_id)
                    if raw_post_id is not None
                    else duplicate.normalized_document_id
                )
                return self._skip_duplicate(
                    duplicate,
                    input_url=input_url,
                    run_started_at=started_at,
                    platform=platform,
                    external_id=discussion_id,
                    normalized_content_hash=content_hash,
                    normalized_document_id=normalized_post_id,
                )

        normalized_post_id = (
            self._save_normalized(normalized, raw_post_id)
            if raw_post_id is not None
            else None
        )
        with self._telemetry.pipeline_stage("extract"):
            complaint = self._extractor.extract(normalized)
        with self._telemetry.pipeline_stage("validate"):
            validated = self._validator.validate(complaint, normalized)
        complaint_id = None
        if self._storage is not None and normalized_post_id is not None:
            with self._telemetry.pipeline_stage("persist_complaint"):
                complaint_id = self._storage.save_complaint(
                    validated,
                    normalized_post_id,
                )
        processing_run_id = self._record_completed_run(
            input_url=input_url,
            platform=platform,
            external_id=discussion_id,
            normalized_content_hash=content_hash,
            normalized_document_id=normalized_post_id,
            complaint_id=complaint_id,
            started_at=started_at,
        )
        return PipelineResult(
            complaint=validated,
            duplicate=False,
            processing_run_id=processing_run_id,
            complaint_id=complaint_id,
            status="completed",
        )

    def process_normalized(self, normalized: NormalizedPost) -> PipelineResult:
        """Process one already-normalized document synchronously."""

        run_started_at = datetime.now(UTC)
        with self._telemetry.pipeline_run():
            platform = str(normalized["platform"])
            discussion_id = str(normalized["external_id"])
            content_hash = normalized_content_hash(normalized)

            if self._storage is not None:
                duplicate = self._find_duplicate(
                    url=str(normalized["url"]),
                    platform=platform,
                    external_id=discussion_id,
                    content_hash=content_hash,
                )
                if duplicate is not None:
                    return self._skip_duplicate(
                        duplicate,
                        input_url=str(normalized["url"]),
                        run_started_at=run_started_at,
                        platform=platform,
                        external_id=discussion_id,
                        normalized_content_hash=content_hash,
                        normalized_document_id=duplicate.normalized_document_id,
                    )

            with self._telemetry.pipeline_stage("extract"):
                complaint = self._extractor.extract(normalized)
            with self._telemetry.pipeline_stage("validate"):
                validated = self._validator.validate(complaint, normalized)
            complaint_id = None
            normalized_post_id = UUID(str(normalized["id"]))
            if self._storage is not None:
                with self._telemetry.pipeline_stage("persist_complaint"):
                    complaint_id = self._storage.save_complaint(
                        validated,
                        normalized_post_id,
                    )
            processing_run_id = self._record_completed_run(
                input_url=str(normalized["url"]),
                platform=platform,
                external_id=discussion_id,
                normalized_content_hash=content_hash,
                normalized_document_id=normalized_post_id,
                complaint_id=complaint_id,
                started_at=run_started_at,
            )
            return PipelineResult(
                complaint=validated,
                duplicate=False,
                processing_run_id=processing_run_id,
                complaint_id=complaint_id,
                status="completed",
            )

    def _save_normalized(
        self,
        normalized: NormalizedPost,
        raw_post_id: UUID,
    ) -> UUID:
        if self._storage is None:
            raise RuntimeError("storage is required to persist normalized data")
        with self._telemetry.pipeline_stage("persist_normalized"):
            return self._storage.save_normalized(normalized, raw_post_id)

    def _find_duplicate(
        self,
        *,
        url: str | None = None,
        platform: str | None = None,
        external_id: str | None = None,
        content_hash: str | None = None,
    ) -> DuplicateMatch | None:
        if self._storage is None:
            return None
        return self._storage.find_duplicate(
            url=url,
            platform=platform,
            external_id=external_id,
            content_hash_value=content_hash,
        )

    def _skip_duplicate(
        self,
        duplicate: DuplicateMatch,
        *,
        input_url: str | None,
        run_started_at: datetime,
        platform: str | None = None,
        external_id: str | None = None,
        normalized_content_hash: str | None = None,
        normalized_document_id: UUID | None = None,
    ) -> PipelineResult:
        resolved_platform = platform or "reddit"
        resolved_external_id = external_id or duplicate.complaint.meta.source_id
        if self._storage is None:
            return PipelineResult(
                complaint=duplicate.complaint,
                duplicate=True,
                duplicate_match=duplicate.match_type,
                complaint_id=duplicate.complaint_id,
                status="duplicate_skipped",
            )

        processing_run_id = self._storage.record_processing_run(
            input_url=input_url,
            platform=resolved_platform,
            external_id=resolved_external_id,
            normalized_content_hash=normalized_content_hash,
            normalized_document_id=(
                normalized_document_id or duplicate.normalized_document_id
            ),
            complaint_id=duplicate.complaint_id,
            status="duplicate_skipped",
            duplicate_match=duplicate.match_type,
            started_at=run_started_at,
            completed_at=datetime.now(UTC),
        )
        return PipelineResult(
            complaint=duplicate.complaint,
            duplicate=True,
            duplicate_match=duplicate.match_type,
            processing_run_id=processing_run_id,
            complaint_id=duplicate.complaint_id,
            status="duplicate_skipped",
        )

    def _record_completed_run(
        self,
        *,
        input_url: str | None,
        platform: str,
        external_id: str,
        normalized_content_hash: str,
        normalized_document_id: UUID | None,
        complaint_id: UUID | None,
        started_at: datetime,
    ) -> UUID | None:
        if self._storage is None:
            return None
        return self._storage.record_processing_run(
            input_url=input_url,
            platform=platform,
            external_id=external_id,
            normalized_content_hash=normalized_content_hash,
            normalized_document_id=normalized_document_id,
            complaint_id=complaint_id,
            status="completed",
            duplicate_match=None,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
