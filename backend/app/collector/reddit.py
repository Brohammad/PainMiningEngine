"""PRAW-backed Reddit collection mapped to RawDiscussion."""

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

from backend.app.collector.discussion import (
    DiscussionSchemaValidator,
    legacy_reddit_to_discussion,
)
from backend.app.collector.exceptions import (
    RedditCollectorError,
    RedditNetworkError,
    RedditRateLimitError,
    RedditResourceUnavailableError,
)
from backend.app.collector.settings import RedditSettings
from backend.app.collector.types import LegacyRedditCapture, RawDiscussion
from backend.app.observability import NoOpTelemetry, TelemetryRecorder

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
        telemetry: TelemetryRecorder | None = None,
        schema_directory: Any | None = None,
    ) -> None:
        self._settings = settings
        self._reddit = reddit if reddit is not None else self._build_client(settings)
        self._sleep = sleeper
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)
        self._telemetry = telemetry or NoOpTelemetry()
        self._discussion_validator = DiscussionSchemaValidator(schema_directory)

    def fetch(self, target: str) -> RawDiscussion:
        """Fetch one Reddit submission by URL."""

        if not target.strip():
            raise ValueError("target must not be empty")
        return self._to_discussion(
            self._execute(
                lambda: self._map_legacy_capture(
                    self._reddit.submission(url=target)
                )
            ),
            context=target,
        )

    def fetch_post(self, target: str) -> RawDiscussion:
        """Backward-compatible alias for :meth:`fetch`."""

        return self.fetch(target)

    def fetch_subreddit(
        self,
        subreddit: str,
        limit: int,
    ) -> list[RawDiscussion]:
        """Fetch hot submissions from a subreddit."""

        self._validate_listing_arguments(subreddit, limit)
        return self._execute(
            lambda: [
                self._to_discussion(self._map_legacy_capture(submission))
                for submission in self._reddit.subreddit(subreddit).hot(limit=limit)
            ]
        )

    def fetch_search(
        self,
        query: str,
        subreddit: str,
        limit: int,
    ) -> list[RawDiscussion]:
        """Search a subreddit and fetch matching submissions."""

        if not query.strip():
            raise ValueError("query must not be empty")
        self._validate_listing_arguments(subreddit, limit)
        return self._execute(
            lambda: [
                self._to_discussion(self._map_legacy_capture(submission))
                for submission in self._reddit.subreddit(subreddit).search(
                    query,
                    sort="relevance",
                    limit=limit,
                )
            ]
        )

    def _to_discussion(
        self,
        capture: LegacyRedditCapture,
        *,
        context: str = "reddit capture",
    ) -> RawDiscussion:
        discussion = legacy_reddit_to_discussion(capture)
        self._discussion_validator.validate(discussion, context=context)
        return discussion

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
                delay = self._retry_delay(attempt, exc)
                self._telemetry.record_retry("reddit", "rate_limit", delay)
                self._sleep(delay)
            except (RequestException, ServerError) as exc:
                if attempt + 1 >= self._settings.retry_attempts:
                    raise RedditNetworkError(
                        "Reddit network retries exhausted"
                    ) from exc
                delay = self._retry_delay(attempt)
                self._telemetry.record_retry("reddit", "network", delay)
                self._sleep(delay)
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

    def _map_legacy_capture(self, submission: Submission) -> LegacyRedditCapture:
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


# Deprecated alias for legacy imports.
RawRedditCapture = RawDiscussion
