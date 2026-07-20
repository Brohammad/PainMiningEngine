"""Raw-to-canonical document normalization boundary."""

from typing import Protocol

from backend.app.collector.types import RawDiscussion
from backend.app.normalizer.reddit import NormalizedPost, RedditNormalizer


class DiscussionNormalizer(Protocol):
    """Normalize one RawDiscussion into a canonical document."""

    def normalize(self, discussion: RawDiscussion) -> NormalizedPost: ...


__all__ = [
    "DiscussionNormalizer",
    "NormalizedPost",
    "RedditNormalizer",
]
