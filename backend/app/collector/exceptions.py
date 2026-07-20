"""Collector-specific failures exposed to callers."""


class FileCollectorError(RuntimeError):
    """Base error for local file collection failures."""


class FileCollectorNotFoundError(FileCollectorError):
    """Raised when the requested JSON file does not exist."""


class FileCollectorInvalidJsonError(FileCollectorError):
    """Raised when a file does not contain valid discussion JSON."""


class FileCollectorSchemaError(FileCollectorError):
    """Raised when JSON content violates the RawDiscussion schema."""


class URLCollectorError(RuntimeError):
    """Base error for URL HTML collection failures."""


class URLCollectorNetworkError(URLCollectorError):
    """Raised when Reddit HTML cannot be retrieved."""


class URLCollectorParseError(URLCollectorError):
    """Raised when required fields cannot be extracted from HTML."""


class URLCollectorSchemaError(URLCollectorError):
    """Raised when mapped capture violates the RawDiscussion schema."""


class RedditCollectorError(RuntimeError):
    """Base error for Reddit collection failures."""


class RedditNetworkError(RedditCollectorError):
    """Raised after transient network failures exhaust configured retries."""


class RedditRateLimitError(RedditCollectorError):
    """Raised after Reddit rate-limit responses exhaust configured retries."""


class RedditResourceUnavailableError(RedditCollectorError):
    """Raised when Reddit does not expose a requested resource."""


class GitHubCollectorError(RuntimeError):
    """Base error for GitHub collection failures."""


class GitHubNetworkError(GitHubCollectorError):
    """Raised after transient GitHub network failures exhaust configured retries."""


class GitHubRateLimitError(GitHubCollectorError):
    """Raised after GitHub rate-limit responses exhaust configured retries."""


class GitHubResourceUnavailableError(GitHubCollectorError):
    """Raised when GitHub does not expose a requested resource."""


class GitHubParseError(GitHubCollectorError):
    """Raised when a GitHub URL cannot be parsed."""
