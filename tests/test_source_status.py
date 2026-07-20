"""Tests for source availability reporting."""

from typing import Any

from backend.app.collector.source_status import (
    format_sources_report,
    github_token_configured,
    list_source_statuses,
    reddit_configured,
)
from backend.app.collector.sources import DiscussionSource


def test_list_source_statuses_includes_github_file_reddit_and_hackernews() -> None:
    statuses = list_source_statuses()

    assert [status.source for status in statuses] == [
        DiscussionSource.GITHUB,
        DiscussionSource.FILE,
        DiscussionSource.REDDIT,
        DiscussionSource.HACKERNEWS,
    ]


def test_format_sources_report_contains_expected_labels() -> None:
    report = format_sources_report()

    assert "✓ GitHub" in report
    assert "✓ File" in report
    assert "Reddit" in report
    assert "Hacker News (planned)" in report


def test_reddit_configured_reflects_environment(monkeypatch: Any) -> None:
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("REDDIT_USER_AGENT", raising=False)

    assert reddit_configured() is False


def test_github_token_configured_reflects_environment(monkeypatch: Any) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    assert github_token_configured() is False

    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")

    assert github_token_configured() is True
