"""Composition helpers for source-aware collectors."""

from typing import Any

from backend.app.collector.github import GitHubCollector
from backend.app.collector.github_settings import GitHubSettings
from backend.app.collector.reddit import RedditCollector
from backend.app.collector.routing import (
    RoutingCollector,
    is_github_issue_url,
    is_reddit_url,
)
from backend.app.collector.settings import RedditSettings
from backend.app.observability import TelemetryRecorder


def build_url_collector(
    *,
    github_settings: GitHubSettings,
    reddit_settings: RedditSettings | None = None,
    telemetry: TelemetryRecorder | None = None,
) -> RoutingCollector:
    """Build a collector that routes URLs to configured source implementations."""

    routes: list[tuple[Any, Any]] = [
        (is_github_issue_url, GitHubCollector(github_settings, telemetry=telemetry)),
    ]
    if reddit_settings is not None:
        routes.append(
            (is_reddit_url, RedditCollector(reddit_settings, telemetry=telemetry)),
        )
    return RoutingCollector(routes)
