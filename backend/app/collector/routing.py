"""URL-based collector routing."""

from __future__ import annotations

from collections.abc import Callable

from backend.app.collector.exceptions import GitHubParseError
from backend.app.collector.github_parser import parse_github_issue_url
from backend.app.collector.source_collector import SourceCollector
from backend.app.collector.types import RawDiscussion
from backend.app.collector.url_parser import parse_reddit_url


class RoutingCollector:
    """Dispatch fetch requests to the first matching source collector."""

    def __init__(
        self,
        routes: list[tuple[Callable[[str], bool], SourceCollector]],
    ) -> None:
        if not routes:
            raise ValueError("routes must not be empty")
        self._routes = routes

    def fetch(self, target: str) -> RawDiscussion:
        """Fetch one discussion using the first route that matches the target."""

        if not target.strip():
            raise ValueError("target must not be empty")

        for matches, collector in self._routes:
            if matches(target):
                return collector.fetch(target)
        raise ValueError(f"no collector registered for target: {target}")

    def fetch_post(self, target: str) -> RawDiscussion:
        """Backward-compatible alias for :meth:`fetch`."""

        return self.fetch(target)


def is_github_issue_url(target: str) -> bool:
    try:
        parse_github_issue_url(target)
    except GitHubParseError:
        return False
    return True


def is_reddit_url(target: str) -> bool:
    try:
        parse_reddit_url(target)
    except Exception:
        return False
    return True
