"""Collector-specific failures exposed to callers."""


class RedditCollectorError(RuntimeError):
    """Base error for Reddit collection failures."""


class RedditNetworkError(RedditCollectorError):
    """Raised after transient network failures exhaust configured retries."""


class RedditRateLimitError(RedditCollectorError):
    """Raised after Reddit rate-limit responses exhaust configured retries."""


class RedditResourceUnavailableError(RedditCollectorError):
    """Raised when Reddit does not expose a requested resource."""
