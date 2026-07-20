"""Backward-compatible Reddit identity helpers (use source_identity instead)."""

from backend.app.source_identity import (
    DiscussionIdentity,
    DiscussionIdentityResolver,
    RedditDiscussionIdentityResolver,
    canonicalize_reddit_url,
    normalize_lookup_url,
)


def reddit_identity_from_url(url: str) -> tuple[str, str, str]:
    """Return (platform, external_id, canonical_url) for a Reddit URL."""

    identity = RedditDiscussionIdentityResolver().resolve_url(url)
    if identity is None:
        raise ValueError(f"unable to resolve Reddit identity from URL: {url}")
    return identity.source, identity.discussion_id, identity.canonical_url


__all__ = [
    "DiscussionIdentity",
    "DiscussionIdentityResolver",
    "RedditDiscussionIdentityResolver",
    "canonicalize_reddit_url",
    "normalize_lookup_url",
    "reddit_identity_from_url",
]
