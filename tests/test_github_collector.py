"""Unit tests for the GitHub REST issue collector."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from backend.app.collector import (
    GitHubCollector,
    GitHubNetworkError,
    GitHubParseError,
    GitHubResourceUnavailableError,
    GitHubSettings,
)
from backend.app.collector.sources import DiscussionSource
from backend.app.normalizer import GitHubNormalizer

SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "raw_discussion.json"
SCHEMA_VALIDATOR = Draft202012Validator(
    json.loads(SCHEMA_PATH.read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
FIXED_TIME = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
ISSUE_URL = "https://github.com/acme/platform/issues/42"
ISSUE_API = "https://api.github.com/repos/acme/platform/issues/42"
COMMENTS_API = "https://api.github.com/repos/acme/platform/issues/42/comments"


def make_issue_payload() -> dict[str, Any]:
    return {
        "id": 42,
        "number": 42,
        "title": "Certificate rotation is painful",
        "body": "Manual certificate rotation takes hours.",
        "state": "open",
        "html_url": ISSUE_URL,
        "created_at": "2024-07-19T09:00:00Z",
        "updated_at": "2024-07-19T10:00:00Z",
        "user": {"login": "operator"},
        "labels": [{"name": "bug"}],
        "assignees": [{"login": "oncall"}],
        "reactions": {"total_count": 7},
    }


def make_comment_payload() -> dict[str, Any]:
    return {
        "id": 9001,
        "body": "Try certbot weekly.",
        "created_at": "2024-07-19T11:00:00Z",
        "updated_at": "2024-07-19T11:00:00Z",
        "user": {"login": "commenter"},
        "reactions": {"total_count": 2},
        "node_id": "IC_kwDO",
        "html_url": f"{ISSUE_URL}#issuecomment-9001",
    }


def make_collector(
    *,
    responses: dict[str, Any] | None = None,
    delays: list[float] | None = None,
    retry_attempts: int = 3,
) -> GitHubCollector:
    mapping = responses or {
        ISSUE_API: make_issue_payload(),
        COMMENTS_API: [make_comment_payload()],
    }
    delay_log = delays if delays is not None else []

    def fetch_json(url: str, _headers: dict[str, str], _timeout: float) -> Any:
        effect = mapping[url]
        if isinstance(effect, Exception):
            raise effect
        return effect

    return GitHubCollector(
        GitHubSettings(token="test-token", retry_attempts=retry_attempts),
        fetch_json=fetch_json,
        sleeper=delay_log.append,
        clock=lambda: FIXED_TIME,
    )


def test_fetch_maps_issue_and_comments_to_raw_discussion() -> None:
    capture = make_collector().fetch(ISSUE_URL)

    SCHEMA_VALIDATOR.validate(capture)
    assert capture["source"] == DiscussionSource.GITHUB.value
    assert capture["discussion_id"] == "acme/platform#issue-42"
    assert capture["title"] == "Certificate rotation is painful"
    assert capture["body"] == "Manual certificate rotation takes hours."
    assert capture["author"] == "operator"
    assert capture["comments"][0]["body"] == "Try certbot weekly."
    assert capture["metadata"]["repository"] == "acme/platform"
    assert capture["metadata"]["labels"] == ["bug"]
    assert capture["fetched_at"] == FIXED_TIME.isoformat()


def test_fetch_runs_through_github_normalizer() -> None:
    capture = make_collector().fetch(ISSUE_URL)

    normalized = GitHubNormalizer().normalize(capture)

    assert normalized["platform"] == "github"
    assert normalized["external_id"] == "acme/platform#issue-42"
    assert normalized["community"] == "acme/platform"
    assert normalized["score"] == 7


def test_fetch_rejects_non_github_urls() -> None:
    with pytest.raises(GitHubParseError):
        make_collector().fetch("https://example.com/acme/platform/issues/42")


def test_fetch_retries_rate_limit_using_retry_after() -> None:
    response = HTTPError(ISSUE_URL, 429, "rate limit", hdrs={"Retry-After": "2"}, fp=None)  # type: ignore[arg-type]
    calls = {"count": 0}
    delays: list[float] = []

    def fetch_json(url: str, _headers: dict[str, str], _timeout: float) -> Any:
        if url == ISSUE_API:
            calls["count"] += 1
            if calls["count"] == 1:
                raise response
            return make_issue_payload()
        if url == COMMENTS_API:
            return [make_comment_payload()]
        raise AssertionError(url)

    collector = GitHubCollector(
        GitHubSettings(token="test-token", retry_attempts=2),
        fetch_json=fetch_json,
        sleeper=delays.append,
        clock=lambda: FIXED_TIME,
    )

    capture = collector.fetch(ISSUE_URL)

    SCHEMA_VALIDATOR.validate(capture)
    assert delays == [2.0]


def test_fetch_wraps_missing_issue_as_unavailable() -> None:
    response = HTTPError(ISSUE_URL, 404, "not found", hdrs={}, fp=None)  # type: ignore[arg-type]
    collector = make_collector(
        responses={ISSUE_API: response},
        retry_attempts=1,
    )

    with pytest.raises(GitHubResourceUnavailableError):
        collector.fetch(ISSUE_URL)


def test_fetch_wraps_exhausted_network_failures() -> None:
    collector = make_collector(
        responses={ISSUE_API: GitHubNetworkError("offline")},
        retry_attempts=1,
    )

    with pytest.raises(GitHubNetworkError):
        collector.fetch(ISSUE_URL)
