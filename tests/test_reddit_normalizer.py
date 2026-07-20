"""Unit tests for deterministic Reddit normalization."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from backend.app.normalizer import RedditNormalizer

SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "normalized_document.json"
NORMALIZED_SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
NORMALIZED_VALIDATOR = Draft202012Validator(
    NORMALIZED_SCHEMA,
    format_checker=FormatChecker(),
)


def make_comment(
    comment_id: str,
    body: str,
    *,
    author: str | None = "commenter",
    score: int = 1,
    depth: int | None = 0,
) -> dict[str, Any]:
    return {
        "id": comment_id,
        "body": body,
        "author": author,
        "created_at": "2024-07-19T09:46:40+00:00",
        "updated_at": "2024-07-19T09:46:40+00:00",
        "score": score,
        "parent_id": "t3_post1",
        "depth": depth if depth is not None else 1,
        "metadata": {
            "name": f"t1_{comment_id}",
            "permalink": f"/r/devops/comments/post1/thread/{comment_id}/",
        },
    }


def make_raw_capture() -> dict[str, Any]:
    first = make_comment(
        "duplicate",
        "**Use Terraform**\t now.",
        score=10,
        depth=0,
    )
    nested = make_comment(
        "nested",
        "Try   `certbot`\n\nweekly.",
        author=None,
        score=4,
        depth=1,
    )
    duplicate = make_comment(
        "duplicate",
        "This duplicate must not replace the first.",
        score=2,
        depth=0,
    )
    return {
        "fetched_at": "2024-07-19T15:30:00+05:30",
        "source": "reddit",
        "discussion_id": "t3_post1",
        "title": "# **Certificate** [rotation](https://example.com) failure",
        "body": (
            "Manual   rotation\n\n takes *hours*." "\n\n```sh\ncertbot renew\n```"
        ),
        "author": "operator",
        "created_at": "2024-07-19T09:00:00+00:00",
        "updated_at": "2024-07-19T09:00:00+00:00",
        "url": "https://www.reddit.com/r/devops/comments/post1/",
        "metadata": {
            "subreddit": "devops",
            "score": 42,
            "upvote_ratio": 0.95,
            "num_comments": 3,
            "link_flair_text": "Discussion",
            "over_18": False,
            "is_self": True,
            "source_post_url": "https://example.com/source-link",
            "api": "praw",
            "fetch_meta": {
                "comment_limit": 20,
                "comment_sort": "top",
            },
        },
        "comments": [first, nested, duplicate],
    }


def test_normalize_cleans_flattens_deduplicates_and_preserves_originals() -> None:
    raw = make_raw_capture()
    normalizer = RedditNormalizer()

    normalized = normalizer.normalize(raw)

    NORMALIZED_VALIDATOR.validate(normalized)
    assert normalized["title"] == "Certificate rotation failure"
    assert normalized["content"] == "Manual rotation takes hours. certbot renew"
    assert normalized["created_at"] == "2024-07-19T09:00:00+00:00"
    assert normalized["fetched_at"] == "2024-07-19T10:00:00+00:00"
    assert [comment["id"] for comment in normalized["comments"]] == [
        "duplicate",
        "nested",
    ]
    assert normalized["comments"][0]["body"] == "Use Terraform now."
    assert normalized["comments"][1]["body"] == "Try certbot weekly."
    assert normalized["comments"][1]["author"] is None
    assert normalized["comments"][1]["depth"] == 1

    originals = normalized["metadata"]["original_text"]
    assert originals["title"] == raw["title"]
    assert originals["content"] == raw["body"]
    assert originals["comments"] == [
        {"id": "duplicate", "body": "**Use Terraform**\t now."},
        {"id": "nested", "body": "Try   `certbot`\n\nweekly."},
        {
            "id": "duplicate",
            "body": "This duplicate must not replace the first.",
        },
    ]


def test_normalize_is_deterministic() -> None:
    raw = make_raw_capture()
    normalizer = RedditNormalizer()

    first = normalizer.normalize(raw)
    second = normalizer.normalize(deepcopy(raw))

    assert first == second


def test_normalize_rejects_input_outside_raw_schema() -> None:
    raw = make_raw_capture()
    del raw["title"]

    with pytest.raises(ValidationError):
        RedditNormalizer().normalize(raw)


def test_normalize_rejects_output_outside_normalized_schema() -> None:
    raw = make_raw_capture()
    raw["comments"][0]["depth"] = -1

    with pytest.raises(ValidationError):
        RedditNormalizer().normalize(raw)
