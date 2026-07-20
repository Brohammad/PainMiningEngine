"""Known discussion source identifiers."""

from enum import Enum


class DiscussionSource(str, Enum):
    """Canonical source platform identifiers for RawDiscussion captures."""

    REDDIT = "reddit"
    GITHUB = "github"
    HACKERNEWS = "hackernews"
    FILE = "file"
