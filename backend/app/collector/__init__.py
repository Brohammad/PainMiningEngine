"""Raw discussion collection boundary."""

from backend.app.collector.exceptions import (
    RedditCollectorError,
    RedditNetworkError,
    RedditRateLimitError,
    RedditResourceUnavailableError,
)
from backend.app.collector.reddit import RawRedditCapture, RedditCollector
from backend.app.collector.settings import RedditSettings

__all__ = [
    "RawRedditCapture",
    "RedditCollector",
    "RedditCollectorError",
    "RedditNetworkError",
    "RedditRateLimitError",
    "RedditResourceUnavailableError",
    "RedditSettings",
]
