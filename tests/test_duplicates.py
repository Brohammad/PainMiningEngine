"""Duplicate detection and processing history tests."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from backend.app.collector.reddit_identity import canonicalize_reddit_url
from backend.app.extractor import (
    Complaint as ComplaintSchema,
)
from backend.app.normalizer import RedditNormalizer
from backend.app.pipeline import SynchronousPipeline
from backend.app.storage import SQLAlchemyStageStore
from backend.app.storage.hash import normalized_content_hash
from backend.app.storage.models import ProcessingRun
from tests.test_persistence import (
    StaticExtractor,
    StaticNormalizer,
    StaticValidator,
    UnusedCollector,
    make_complaint,
    make_raw_capture,
    make_store,
)


class CountingCollector:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.calls = 0

    def fetch(self, url: str) -> dict[str, Any]:
        self.calls += 1
        return self.raw


class CountingExtractor:
    def __init__(self, complaint: ComplaintSchema) -> None:
        self.complaint = complaint
        self.calls = 0

    def extract(self, _normalized: dict[str, Any]) -> ComplaintSchema:
        self.calls += 1
        return self.complaint


def seed_completed_pipeline(
    store: SQLAlchemyStageStore,
) -> tuple[dict[str, Any], dict[str, Any], ComplaintSchema, UUID]:
    raw = make_raw_capture()
    normalized = RedditNormalizer().normalize(raw)
    document_id = UUID(str(normalized["id"]))
    complaint = make_complaint(document_id)
    raw_id = store.save_raw(raw)
    normalized_id = store.save_normalized(normalized, raw_id)
    complaint_id = store.save_complaint(complaint, normalized_id)
    run_id = store.record_processing_run(
        input_url=str(normalized["url"]),
        platform=str(normalized["platform"]),
        external_id=str(normalized["external_id"]),
        normalized_content_hash=normalized_content_hash(normalized),
        normalized_document_id=normalized_id,
        complaint_id=complaint_id,
        status="completed",
        duplicate_match=None,
        started_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
        completed_at=datetime(2026, 7, 20, 12, 1, tzinfo=UTC),
    )
    return normalized, raw, complaint, run_id


def test_find_duplicate_by_platform_id(tmp_path: Any) -> None:
    store, _factory = make_store(tmp_path)
    normalized, _raw, complaint, _run_id = seed_completed_pipeline(store)

    match = store.find_duplicate(platform="reddit", external_id="t3_post1")

    assert match is not None
    assert match.match_type == "platform_id"
    assert match.complaint == complaint
    assert match.normalized_document_id == UUID(str(normalized["id"]))


def test_find_duplicate_by_url(tmp_path: Any) -> None:
    store, _factory = make_store(tmp_path)
    normalized, _raw, complaint, _run_id = seed_completed_pipeline(store)
    alias_url = "https://old.reddit.com/r/devops/comments/post1/slug/"

    match = store.find_duplicate(url=alias_url)

    assert match is not None
    assert match.match_type == "url"
    assert match.complaint == complaint
    assert canonicalize_reddit_url(alias_url) == normalized["url"]


def test_find_duplicate_by_content_hash(tmp_path: Any) -> None:
    store, _factory = make_store(tmp_path)
    normalized, _raw, complaint, _run_id = seed_completed_pipeline(store)

    match = store.find_duplicate(content_hash_value=normalized_content_hash(normalized))

    assert match is not None
    assert match.match_type == "content_hash"
    assert match.complaint == complaint


def test_pipeline_skips_platform_id_duplicate_without_reprocessing(
    tmp_path: Any,
) -> None:
    store, _factory = make_store(tmp_path)
    _normalized, raw, complaint, _run_id = seed_completed_pipeline(store)
    collector = CountingCollector(raw)
    extractor = CountingExtractor(complaint)
    pipeline = SynchronousPipeline(
        collector=collector,
        normalizer=RedditNormalizer(),
        extractor=extractor,
        validator=StaticValidator(),
        storage=store,
    )

    result = pipeline.process_post(raw)

    assert result.duplicate is True
    assert result.duplicate_match == "platform_id"
    assert result.complaint == complaint
    assert collector.calls == 0
    assert extractor.calls == 0
    assert result.processing_run_id is not None


def test_pipeline_skips_url_duplicate_before_collection(tmp_path: Any) -> None:
    store, _factory = make_store(tmp_path)
    _normalized, raw, complaint, _run_id = seed_completed_pipeline(store)
    collector = CountingCollector(raw)
    extractor = CountingExtractor(complaint)
    pipeline = SynchronousPipeline(
        collector=collector,
        normalizer=RedditNormalizer(),
        extractor=extractor,
        validator=StaticValidator(),
        storage=store,
    )
    url = "https://www.reddit.com/r/devops/comments/post1/duplicate/"

    result = pipeline.process_url(url)

    assert result.duplicate is True
    assert result.duplicate_match == "url"
    assert collector.calls == 0
    assert extractor.calls == 0
    assert result.status == "duplicate_skipped"


def test_pipeline_skips_content_hash_duplicate_after_normalize(
    tmp_path: Any,
) -> None:
    store, _factory = make_store(tmp_path)
    _normalized, _raw, complaint, _run_id = seed_completed_pipeline(store)
    raw = make_raw_capture()
    raw = dict(raw)
    raw["discussion_id"] = "t3_post2"
    raw["metadata"] = dict(raw["metadata"])
    raw["metadata"]["score"] = raw["metadata"].get("score", 42)
    collector = CountingCollector(raw)
    extractor = CountingExtractor(complaint)
    pipeline = SynchronousPipeline(
        collector=collector,
        normalizer=RedditNormalizer(),
        extractor=extractor,
        validator=StaticValidator(),
        storage=store,
    )

    result = pipeline.process_post(raw)

    assert result.duplicate is True
    assert result.duplicate_match == "content_hash"
    assert extractor.calls == 0


def test_find_duplicate_ignores_empty_content_hash(tmp_path: Any) -> None:
    store, _factory = make_store(tmp_path)

    assert store.find_duplicate(content_hash_value="") is None

    raw = make_raw_capture()
    normalized = RedditNormalizer().normalize(raw)
    document_id = UUID(str(normalized["id"]))
    raw_id = store.save_raw(raw)

    with _factory.begin() as session:
        from backend.app.storage.models import NormalizedPost

        session.add(
            NormalizedPost(
                id=document_id,
                raw_source_id=raw_id,
                platform=str(normalized["platform"]),
                external_id=str(normalized["external_id"]),
                url=str(normalized["url"]),
                content_hash="",
                title=str(normalized["title"]),
                content=str(normalized["content"]),
                comments=normalized["comments"],
                author=normalized.get("author"),
                score=int(normalized["score"]),
                community=normalized.get("community"),
                document_metadata=normalized.get("metadata", {}),
                created_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
                fetched_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
            )
        )

    assert (
        store.find_duplicate(content_hash_value=normalized_content_hash(normalized))
        is None
    )


def test_second_pipeline_run_is_idempotent_and_records_history(
    tmp_path: Any,
) -> None:
    store, factory = make_store(tmp_path)
    raw = make_raw_capture()
    normalized = RedditNormalizer().normalize(raw)
    complaint = make_complaint(UUID(str(normalized["id"])))
    pipeline = SynchronousPipeline(
        collector=UnusedCollector(),
        normalizer=StaticNormalizer(normalized),
        extractor=StaticExtractor(complaint),
        validator=StaticValidator(),
        storage=store,
    )

    first = pipeline.process_post(raw)
    second = pipeline.process_post(raw)

    assert first.duplicate is False
    assert second.duplicate is True
    assert second.complaint == first.complaint
    assert first.processing_run_id is not None
    assert second.processing_run_id is not None
    assert first.processing_run_id != second.processing_run_id

    with factory() as session:
        runs = session.scalars(select(ProcessingRun)).all()
    assert len(runs) == 2
    assert {run.status for run in runs} == {"completed", "duplicate_skipped"}
