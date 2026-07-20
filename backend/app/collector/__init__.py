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
    GitHubCollectorError,
    GitHubNetworkError,
    GitHubParseError,
    GitHubRateLimitError,
    GitHubResourceUnavailableError,
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
from backend.app.collector.github import GitHubCollector
from backend.app.collector.github_settings import GitHubSettings
from backend.app.collector.reddit import RawRedditCapture, RedditCollector
from backend.app.collector.routing import RoutingCollector, is_github_issue_url, is_reddit_url
from backend.app.collector.settings import RedditSettings
from backend.app.collector.source_collector import SourceCollector
from backend.app.collector.sources import DiscussionSource
from backend.app.collector.types import LegacyRedditCapture, RawDiscussion
from backend.app.collector.url import URLCollector
from backend.app.collector.url_settings import URLCollectorSettings
from backend.app.collector.wiring import build_url_collector

__all__ = [
    "DiscussionSchemaValidator",
    "DiscussionSource",
    "FileCollector",
    "FileCollectorError",
    "FileCollectorInvalidJsonError",
    "FileCollectorNotFoundError",
    "FileCollectorSchemaError",
    "GitHubCollector",
    "GitHubCollectorError",
    "GitHubNetworkError",
    "GitHubParseError",
    "GitHubRateLimitError",
    "GitHubResourceUnavailableError",
    "GitHubSettings",
    "LegacyRedditCapture",
    "RawDiscussion",
    "RawRedditCapture",
    "RedditCollector",
    "RedditCollectorError",
    "RedditNetworkError",
    "RedditRateLimitError",
    "RedditResourceUnavailableError",
    "RedditSettings",
    "RoutingCollector",
    "SourceCollector",
    "URLCollector",
    "URLCollectorError",
    "URLCollectorNetworkError",
    "URLCollectorParseError",
    "URLCollectorSchemaError",
    "URLCollectorSettings",
    "build_url_collector",
    "coerce_to_discussion",
    "is_github_issue_url",
    "is_legacy_reddit_capture",
    "is_raw_discussion",
    "is_reddit_url",
    "legacy_reddit_to_discussion",
]
