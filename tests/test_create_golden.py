"""Unit tests for golden fixture creation."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.app.collector.discussion import coerce_to_discussion
from backend.app.evaluation import (
    GoldenCreateError,
    GoldenDataset,
    blank_expected_extraction,
    create_golden_case,
)
from backend.app.schemas import ComplaintCandidate

SCHEMA_DIRECTORY = Path(__file__).resolve().parents[1] / "schemas"
FIXED_TIME = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def make_raw_capture() -> dict[str, Any]:
    return {
        "fetched_at": "2024-07-19T15:30:00+05:30",
        "source": {
            "platform": "reddit",
            "external_id": "t3_post1",
            "permalink": "https://www.reddit.com/r/devops/comments/post1/",
            "subreddit": "devops",
            "api": "file",
        },
        "post": {
            "id": "post1",
            "name": "t3_post1",
            "title": "Certificate rotation is painful",
            "selftext": "Manual certificate rotation takes hours.",
            "author": "operator",
            "score": 42,
            "upvote_ratio": 0.95,
            "num_comments": 1,
            "created_utc": 1_721_379_600.0,
            "url": "https://example.com/source-link",
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


def test_blank_expected_extraction_matches_complaint_candidate_schema() -> None:
    payload = blank_expected_extraction()

    candidate = ComplaintCandidate.model_validate(payload)

    assert candidate.pain_summary.value is None
    assert candidate.budget_owner.value == "unknown"
    assert candidate.existing_tools == []


def test_create_golden_case_writes_input_expected_and_metadata(
    tmp_path: Path,
) -> None:
    raw = make_raw_capture()
    discussion = coerce_to_discussion(raw)
    output_dir = tmp_path / "case-new"

    case_dir = create_golden_case(
        raw,
        output_dir,
        created_at=FIXED_TIME,
        schema_directory=SCHEMA_DIRECTORY,
    )

    assert case_dir == output_dir
    assert json.loads((case_dir / "input.json").read_text(encoding="utf-8")) == discussion
    assert json.loads(
        (case_dir / "expected.json").read_text(encoding="utf-8")
    ) == blank_expected_extraction()
    metadata = json.loads((case_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["case_id"] == "case-new"
    assert metadata["annotation_status"] == "pending"
    assert metadata["input_schema"] == "raw_discussion"
    assert metadata["source"]["external_id"] == "t3_post1"
    assert metadata["post"]["title"] == "Certificate rotation is painful"
    assert metadata["created_at"] == FIXED_TIME.isoformat()


def test_created_golden_case_loads_for_evaluation(tmp_path: Path) -> None:
    raw = make_raw_capture()
    discussion = coerce_to_discussion(raw)
    dataset_root = tmp_path / "golden"
    create_golden_case(
        raw,
        dataset_root / "case-new",
        created_at=FIXED_TIME,
        schema_directory=SCHEMA_DIRECTORY,
    )

    dataset = GoldenDataset.load(dataset_root, schema_directory=SCHEMA_DIRECTORY)

    assert [case.case_id for case in dataset] == ["case-new"]
    assert dataset[0].raw == discussion
    assert dataset[0].gold.pain_summary.value is None


def test_create_golden_case_rejects_invalid_raw_schema(tmp_path: Path) -> None:
    discussion = coerce_to_discussion(make_raw_capture())
    discussion["title"] = None

    with pytest.raises(GoldenCreateError, match="schema validation"):
        create_golden_case(
            discussion,
            tmp_path / "case-bad",
            schema_directory=SCHEMA_DIRECTORY,
        )


def test_create_golden_case_rejects_non_raw_input(tmp_path: Path) -> None:
    with pytest.raises(GoldenCreateError, match="RawDiscussion"):
        create_golden_case(
            {"platform": "reddit"},
            tmp_path / "case-bad",
            schema_directory=SCHEMA_DIRECTORY,
        )


def test_create_golden_case_rejects_nonempty_output_directory(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "case-existing"
    output_dir.mkdir()
    (output_dir / "input.json").write_text("{}", encoding="utf-8")

    with pytest.raises(GoldenCreateError, match="not empty"):
        create_golden_case(
            make_raw_capture(),
            output_dir,
            schema_directory=SCHEMA_DIRECTORY,
        )
