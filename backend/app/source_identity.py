"""Source-agnostic discussion identity resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from backend.app.collector.github_parser import (
    canonicalize_github_issue_url,
    discussion_id_for_issue,
    parse_github_issue_url,
)
from backend.app.collector.url_parser import parse_reddit_url
from backend.app.collector.sources import DiscussionSource


@dataclass(frozen=True, slots=True)
class DiscussionIdentity:
    """Canonical identity for duplicate detection."""

    source: str
    discussion_id: str
    canonical_url: str


class DiscussionIdentityResolver(Protocol):
    """Resolve a user-supplied locator into canonical discussion identity."""

    def resolve_url(self, url: str) -> DiscussionIdentity | None: ...


class RedditDiscussionIdentityResolver:
    """Resolve Reddit discussion URLs."""

    def resolve_url(self, url: str) -> DiscussionIdentity | None:
        try:
            _subreddit, post_id = parse_reddit_url(url.strip())
        except Exception:
            return None
        discussion_id = post_id if post_id.startswith("t3_") else f"t3_{post_id}"
        canonical_url = canonicalize_reddit_url(url)
        return DiscussionIdentity(
            source=DiscussionSource.REDDIT.value,
            discussion_id=discussion_id,
            canonical_url=canonical_url,
        )


class GitHubDiscussionIdentityResolver:
    """Resolve GitHub issue URLs."""

    def resolve_url(self, url: str) -> DiscussionIdentity | None:
        try:
            owner, repo, number = parse_github_issue_url(url.strip())
        except Exception:
            return None
        return DiscussionIdentity(
            source=DiscussionSource.GITHUB.value,
            discussion_id=discussion_id_for_issue(owner, repo, number),
            canonical_url=canonicalize_github_issue_url(owner, repo, number),
        )


class CompositeIdentityResolver:
    """Try each resolver until one recognizes the URL."""

    def __init__(self, resolvers: list[DiscussionIdentityResolver]) -> None:
        self._resolvers = resolvers

    def resolve_url(self, url: str) -> DiscussionIdentity | None:
        for resolver in self._resolvers:
            identity = resolver.resolve_url(url)
            if identity is not None:
                return identity
        return None


def canonicalize_reddit_url(url: str) -> str:
    """Normalize a Reddit discussion URL for duplicate lookups."""

    subreddit, post_id = parse_reddit_url(url.strip())
    bare_post_id = post_id.removeprefix("t3_")
    return f"https://www.reddit.com/r/{subreddit}/comments/{bare_post_id}/"


def normalize_lookup_url(url: str) -> str:
    """Normalize stored or submitted URLs for duplicate comparison."""

    parsed = urlparse(url.strip())
    if parsed.netloc:
        try:
            return canonicalize_reddit_url(url)
        except Exception:
            pass
        try:
            owner, repo, number = parse_github_issue_url(url)
            return canonicalize_github_issue_url(owner, repo, number)
        except Exception:
            pass
        return url.strip().rstrip("/")
    return url.strip().rstrip("/")
