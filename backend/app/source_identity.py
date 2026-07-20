"""Source-agnostic discussion identity resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from backend.app.collector.url_parser import parse_reddit_url


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
            source="reddit",
            discussion_id=discussion_id,
            canonical_url=canonical_url,
        )


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
            return url.strip().rstrip("/")
    return url.strip().rstrip("/")
