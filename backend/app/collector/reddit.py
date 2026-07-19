"""PRAW-backed collection mapped to the Phase 0 raw Reddit contract."""

from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from time import sleep
from typing import Any, TypeVar

import praw
from praw.models import Comment, MoreComments, Submission
from prawcore.exceptions import (
    Forbidden,
    NotFound,
    RequestException,
    ResponseException,
    ServerError,
    TooManyRequests,
)

from backend.app.collector.exceptions import (
    RedditCollectorError,
    RedditNetworkError,
    RedditRateLimitError,
    RedditResourceUnavailableError,
)
from backend.app.collector.settings import RedditSettings

RawRedditCapture = dict[str, Any]
T = TypeVar("T")


class RedditCollector:
    """Collect Reddit submissions without normalizing or persisting them."""

    def __init__(
        self,
        settings: RedditSettings,
        reddit: praw.Reddit | None = None,
        *,
        sleeper: Callable[[float], None] = sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._reddit = reddit if reddit is not None else self._build_client(settings)
        self._sleep = sleeper
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)

    def fetch_post(self, url: str) -> RawRedditCapture:
        """Fetch one Reddit submission by URL."""

        if not url.strip():
            raise ValueError("url must not be empty")
        return self._execute(
            lambda: self._map_submission(self._reddit.submission(url=url))
        )

    def fetch_subreddit(
        self,
        subreddit: str,
        limit: int,
    ) -> list[RawRedditCapture]:
        """Fetch hot submissions from a subreddit."""

        self._validate_listing_arguments(subreddit, limit)
        return self._execute(
            lambda: [
                self._map_submission(submission)
                for submission in self._reddit.subreddit(subreddit).hot(limit=limit)
            ]
        )

    def fetch_search(
        self,
        query: str,
        subreddit: str,
        limit: int,
    ) -> list[RawRedditCapture]:
        """Search a subreddit and fetch matching submissions."""

        if not query.strip():
            raise ValueError("query must not be empty")
        self._validate_listing_arguments(subreddit, limit)
        return self._execute(
            lambda: [
                self._map_submission(submission)
                for submission in self._reddit.subreddit(subreddit).search(
                    query,
                    sort="relevance",
                    limit=limit,
                )
            ]
        )

    @staticmethod
    def _build_client(settings: RedditSettings) -> praw.Reddit:
        reddit = praw.Reddit(
            client_id=settings.client_id,
            client_secret=settings.client_secret.get_secret_value(),
            user_agent=settings.user_agent,
            timeout=settings.request_timeout_seconds,
            ratelimit_seconds=settings.rate_limit_wait_seconds,
        )
        reddit.read_only = True
        return reddit

    def _execute(self, operation: Callable[[], T]) -> T:
        for attempt in range(self._settings.retry_attempts):
            try:
                return operation()
            except TooManyRequests as exc:
                if attempt + 1 >= self._settings.retry_attempts:
                    raise RedditRateLimitError(
                        "Reddit rate limit retries exhausted"
                    ) from exc
                self._sleep(self._retry_delay(attempt, exc))
            except (RequestException, ServerError) as exc:
                if attempt + 1 >= self._settings.retry_attempts:
                    raise RedditNetworkError(
                        "Reddit network retries exhausted"
                    ) from exc
                self._sleep(self._retry_delay(attempt))
            except (Forbidden, NotFound) as exc:
                raise RedditResourceUnavailableError(
                    "Reddit resource is unavailable"
                ) from exc
            except ResponseException as exc:
                raise RedditCollectorError("Reddit rejected the request") from exc

        raise RedditCollectorError("Reddit operation ended without a result")

    def _retry_delay(
        self,
        attempt: int,
        rate_limit_error: TooManyRequests | None = None,
    ) -> float:
        configured_max = float(self._settings.rate_limit_wait_seconds)
        delay = self._settings.retry_backoff_seconds * (2**attempt)

        if rate_limit_error is not None:
            retry_after = rate_limit_error.response.headers.get("Retry-After")
            if retry_after is not None:
                with suppress(ValueError):
                    delay = float(str(retry_after))

        return float(min(max(delay, 0.0), configured_max))

    def _map_submission(self, submission: Submission) -> RawRedditCapture:
        external_id = str(
            getattr(submission, "name", None) or f"t3_{str(submission.id)}"
        )
        permalink = self._absolute_permalink(str(submission.permalink))
        comments = self._map_comments(submission)

        return {
            "fetched_at": self._timestamp(),
            "source": {
                "platform": "reddit",
                "external_id": external_id,
                "permalink": permalink,
                "subreddit": str(submission.subreddit),
                "api": "praw",
            },
            "post": {
                "id": str(submission.id),
                "name": external_id,
                "title": str(submission.title),
                "selftext": str(submission.selftext or ""),
                "author": self._author_name(submission.author),
                "score": self._integer(submission.score),
                "upvote_ratio": self._optional_float(
                    getattr(submission, "upvote_ratio", None)
                ),
                "num_comments": self._optional_integer(
                    getattr(submission, "num_comments", None)
                ),
                "created_utc": float(submission.created_utc),
                "url": str(submission.url),
                "permalink": permalink,
                "subreddit": str(submission.subreddit),
                "link_flair_text": getattr(submission, "link_flair_text", None),
                "over_18": getattr(submission, "over_18", None),
                "is_self": getattr(submission, "is_self", None),
            },
            "comments": comments,
            "fetch_meta": {
                "comment_limit": self._settings.comment_limit,
                "comment_sort": "top",
                "comment_max_depth": self._settings.comment_max_depth,
                "user_agent": self._settings.user_agent,
            },
        }

    def _map_comments(self, submission: Submission) -> list[dict[str, Any]]:
        submission.comment_sort = "top"
        submission.comments.replace_more(limit=0)
        comments = [
            comment
            for comment in submission.comments.list()
            if not isinstance(comment, MoreComments)
            and self._integer(getattr(comment, "depth", 0))
            <= self._settings.comment_max_depth
        ]
        comments.sort(
            key=lambda comment: self._integer(getattr(comment, "score", 0)),
            reverse=True,
        )

        return [
            self._map_comment(comment)
            for comment in comments[: self._settings.comment_limit]
        ]

    def _map_comment(self, comment: Comment) -> dict[str, Any]:
        permalink_value = getattr(comment, "permalink", None)
        permalink = (
            self._absolute_permalink(str(permalink_value)) if permalink_value else None
        )
        return {
            "id": str(comment.id),
            "name": str(getattr(comment, "name", f"t1_{comment.id}")),
            "body": str(comment.body or ""),
            "author": self._author_name(comment.author),
            "score": self._integer(comment.score),
            "created_utc": float(comment.created_utc),
            "parent_id": self._optional_string(getattr(comment, "parent_id", None)),
            "depth": self._integer(getattr(comment, "depth", 0)),
            "permalink": permalink,
        }

    def _timestamp(self) -> str:
        timestamp = self._clock()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        return timestamp.astimezone(UTC).isoformat()

    @staticmethod
    def _absolute_permalink(permalink: str) -> str:
        if permalink.startswith(("https://", "http://")):
            return permalink
        path = permalink if permalink.startswith("/") else f"/{permalink}"
        return f"https://www.reddit.com{path}"

    @staticmethod
    def _author_name(author: object | None) -> str | None:
        return None if author is None else str(author)

    @staticmethod
    def _integer(value: Any) -> int:
        return int(value) if value is not None else 0

    @staticmethod
    def _optional_integer(value: Any | None) -> int | None:
        return None if value is None else int(value)

    @staticmethod
    def _optional_float(value: Any | None) -> float | None:
        return None if value is None else float(value)

    @staticmethod
    def _optional_string(value: object | None) -> str | None:
        return None if value is None else str(value)

    @staticmethod
    def _validate_listing_arguments(subreddit: str, limit: int) -> None:
        if not subreddit.strip():
            raise ValueError("subreddit must not be empty")
        if limit < 0:
            raise ValueError("limit must be non-negative")
