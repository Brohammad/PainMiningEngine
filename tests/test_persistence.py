"""Persistence and durable synchronous pipeline tests."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.extractor import (
    Complaint as ComplaintSchema,
)
from backend.app.extractor import (
    ExtractionMeta,
    TextField,
    TriStateField,
)
from backend.app.normalizer import RedditNormalizer
from backend.app.pipeline import SynchronousPipeline
from backend.app.storage import (
    Base,
    Complaint,
    NormalizedPost,
    RawPost,
    SQLAlchemyStageStore,
)

ROOT = Path(__file__).parents[1]


def make_raw_capture() -> dict[str, Any]:
    return {
        "fetched_at": "2024-07-19T10:00:00+00:00",
        "source": {
            "platform": "reddit",
            "external_id": "t3_post1",
            "permalink": "https://www.reddit.com/r/devops/comments/post1/",
            "subreddit": "devops",
            "api": "praw",
        },
        "post": {
            "id": "post1",
            "name": "t3_post1",
            "title": "Certificate rotation is painful",
            "selftext": "Manual certificate rotation takes hours.",
            "author": "operator",
            "score": 42,
            "upvote_ratio": 0.95,
            "num_comments": 0,
            "created_utc": 1_721_379_600.0,
            "url": "https://www.reddit.com/r/devops/comments/post1/",
            "permalink": "/r/devops/comments/post1/",
            "subreddit": "devops",
            "link_flair_text": "Discussion",
            "over_18": False,
            "is_self": True,
        },
        "comments": [],
        "fetch_meta": {
            "comment_limit": 20,
            "comment_sort": "top",
        },
    }


def make_complaint(
    document_id: UUID,
    *,
    extracted_at: datetime | None = None,
) -> ComplaintSchema:
    empty = TextField(value=None, evidence=[])
    return ComplaintSchema(
        pain_summary=empty,
        workflow=empty,
        workaround=empty,
        buyer=empty,
        budget_owner=TriStateField(value="unknown", evidence=[]),
        time_cost=empty,
        industry=empty,
        existing_tools=[],
        meta=ExtractionMeta(
            model="test-model",
            prompt_version="extract_v1",
            source_id="t3_post1",
            document_id=document_id,
            extracted_at=extracted_at or datetime(2026, 7, 19, 12, 30, tzinfo=UTC),
        ),
    )


def make_store(tmp_path: Path) -> tuple[
    SQLAlchemyStageStore,
    sessionmaker[Session],
]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'stages.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        class_=Session,
        expire_on_commit=False,
    )
    return SQLAlchemyStageStore(factory), factory


def stage_counts(factory: sessionmaker[Session]) -> tuple[int, int, int]:
    with factory() as session:
        return (
            session.scalar(select(func.count()).select_from(RawPost)) or 0,
            session.scalar(select(func.count()).select_from(NormalizedPost)) or 0,
            session.scalar(select(func.count()).select_from(Complaint)) or 0,
        )


def test_stage_store_is_idempotent_and_never_overwrites(
    tmp_path: Path,
) -> None:
    store, factory = make_store(tmp_path)
    raw = make_raw_capture()
    normalized = RedditNormalizer().normalize(raw)
    document_id = UUID(str(normalized["id"]))
    complaint = make_complaint(document_id)

    raw_id = store.save_raw(raw)
    assert store.save_raw(raw) == raw_id

    changed_raw = deepcopy(raw)
    changed_raw["post"]["selftext"] = "This must not overwrite the first capture."
    assert store.save_raw(changed_raw) == raw_id

    normalized_id = store.save_normalized(normalized, raw_id)
    assert normalized_id == document_id
    assert store.save_normalized(normalized, raw_id) == normalized_id

    complaint_id = store.save_complaint(complaint, normalized_id)
    assert store.save_complaint(complaint, normalized_id) == complaint_id
    assert stage_counts(factory) == (1, 1, 1)
    assert store.get_complaint(complaint_id) == complaint
    assert store.get_complaint(uuid4()) is None
    assert store.count_stages().raw_posts == 1
    assert store.count_stages().normalized_posts == 1
    assert store.count_stages().complaints == 1
    store.check_health()

    later = make_complaint(
        normalized_id,
        extracted_at=complaint.meta.extracted_at + timedelta(minutes=1),
    )
    assert store.save_complaint(later, normalized_id) != complaint_id
    assert stage_counts(factory) == (1, 1, 2)

    with factory() as session:
        stored_raw = session.get(RawPost, raw_id)
        assert stored_raw is not None
        assert (
            stored_raw.payload["post"]["selftext"]
            == "Manual certificate rotation takes hours."
        )


class StaticNormalizer:
    def __init__(self, normalized: dict[str, Any]) -> None:
        self.normalized = normalized

    def normalize(self, _raw: dict[str, Any]) -> dict[str, Any]:
        return self.normalized


class StaticExtractor:
    def __init__(self, complaint: ComplaintSchema) -> None:
        self.complaint = complaint

    def extract(self, _normalized: dict[str, Any]) -> ComplaintSchema:
        return self.complaint


class FailingExtractor:
    def extract(self, _normalized: dict[str, Any]) -> ComplaintSchema:
        raise RuntimeError("extraction failed")


class StaticValidator:
    def validate(
        self,
        complaint: ComplaintSchema,
        _normalized: dict[str, Any],
    ) -> ComplaintSchema:
        return complaint


class UnusedCollector:
    def fetch_post(self, _url: str) -> dict[str, Any]:
        raise AssertionError("collector should not run for process_post")


def test_pipeline_persists_all_stages_idempotently(tmp_path: Path) -> None:
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

    assert first == second == complaint
    assert stage_counts(factory) == (1, 1, 1)


def test_pipeline_commits_each_completed_stage_independently(
    tmp_path: Path,
) -> None:
    store, factory = make_store(tmp_path)
    raw = make_raw_capture()
    normalized = RedditNormalizer().normalize(raw)
    pipeline = SynchronousPipeline(
        collector=UnusedCollector(),
        normalizer=StaticNormalizer(normalized),
        extractor=FailingExtractor(),
        validator=StaticValidator(),
        storage=store,
    )

    try:
        pipeline.process_post(raw)
    except RuntimeError as exc:
        assert str(exc) == "extraction failed"
    else:
        raise AssertionError("pipeline should propagate extraction failure")

    assert stage_counts(factory) == (1, 1, 0)


def test_alembic_upgrade_creates_all_stage_tables(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite+pysqlite:///{database_path}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")

    table_names = set(inspect(create_engine(database_url)).get_table_names())
    assert {
        "raw_sources",
        "normalized_documents",
        "extractions",
        "alembic_version",
    } <= table_names
