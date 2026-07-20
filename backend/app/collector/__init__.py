"""Raw discussion collection boundary."""

from backend.app.collector.discussion import (
    DiscussionSchemaValidator,
    coerce_to_discussion,
    is_legacy_reddit_capture,
    is_raw_discussion,
    legacy_reddit_to_discussion,
)
from backend.app.collector.exceptions import (
    FileCollectorError,
    FileCollectorInvalidJsonError,
    FileCollectorNotFoundError,
    FileCollectorSchemaError,
    RedditCollectorError,
    RedditNetworkError,
    RedditRateLimitError,
    RedditResourceUnavailableError,
    URLCollectorError,
    URLCollectorNetworkError,
    URLCollectorParseError,
    URLCollectorSchemaError,
)
from backend.app.collector.file import FileCollector
from backend.app.collector.reddit import RawRedditCapture, RedditCollector
from backend.app.collector.settings import RedditSettings
from backend.app.collector.source_collector import SourceCollector
from backend.app.collector.types import LegacyRedditCapture, RawDiscussion
from backend.app.collector.url import URLCollector
from backend.app.collector.url_settings import URLCollectorSettings

__all__ = [
    "DiscussionSchemaValidator",
    "FileCollector",
    "FileCollectorError",
    "FileCollectorInvalidJsonError",
    "FileCollectorNotFoundError",
    "FileCollectorSchemaError",
    "LegacyRedditCapture",
    "RawDiscussion",
    "RawRedditCapture",
    "RedditCollector",
    "RedditCollectorError",
    "RedditNetworkError",
    "RedditRateLimitError",
    "RedditResourceUnavailableError",
    "RedditSettings",
    "SourceCollector",
    "URLCollector",
    "URLCollectorError",
    "URLCollectorNetworkError",
    "URLCollectorParseError",
    "URLCollectorSchemaError",
    "URLCollectorSettings",
    "coerce_to_discussion",
    "is_legacy_reddit_capture",
    "is_raw_discussion",
    "legacy_reddit_to_discussion",
]
