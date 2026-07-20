"""HTML-backed Reddit collection mapped to RawDiscussion."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

from backend.app.collector.discussion import (
    DiscussionSchemaValidator,
    legacy_reddit_to_discussion,
)
from backend.app.collector.exceptions import (
    URLCollectorNetworkError,
    URLCollectorParseError,
    URLCollectorSchemaError,
)
from backend.app.collector.types import LegacyRedditCapture, RawDiscussion
from backend.app.collector.url_parser import (
    ParsedRedditComment,
    ParsedRedditPost,
    parse_reddit_html,
    parse_reddit_url,
)
from backend.app.collector.url_settings import URLCollectorSettings

FetchHtml = Callable[[str, dict[str, str], float], str]


class URLCollector:
    """Collect Reddit posts by scraping public HTML pages."""

    def __init__(
        self,
        settings: URLCollectorSettings | None = None,
        *,
        fetch_html: FetchHtml | None = None,
        clock: Callable[[], datetime] | None = None,
        schema_directory: Path | None = None,
    ) -> None:
        self._settings = settings or URLCollectorSettings()
        self._fetch_html = fetch_html or self._default_fetch_html
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)
        self._discussion_validator = DiscussionSchemaValidator(schema_directory)

    def fetch(self, target: str) -> RawDiscussion:
        """Fetch one Reddit discussion URL and return a RawDiscussion."""

        if not target.strip():
            raise ValueError("target must not be empty")

        parse_reddit_url(target)
        fetch_url = self._normalize_fetch_url(target)
        headers = {"User-Agent": self._settings.user_agent}
        try:
            html = self._fetch_html(
                fetch_url,
                headers,
                self._settings.request_timeout_seconds,
            )
        except HTTPError as exc:
            raise URLCollectorNetworkError(
                f"Reddit returned HTTP {exc.code} for {fetch_url}"
            ) from exc
        except URLError as exc:
            raise URLCollectorNetworkError(
                f"unable to retrieve HTML for {fetch_url}"
            ) from exc

        try:
            parsed = parse_reddit_html(html, target)
        except URLCollectorParseError:
            raise

        discussion = legacy_reddit_to_discussion(self._map_legacy_capture(parsed))
        self._validate(discussion, target)
        return discussion

    def fetch_post(self, target: str) -> RawDiscussion:
        """Backward-compatible alias for :meth:`fetch`."""

        return self.fetch(target)

    def _map_legacy_capture(self, parsed: ParsedRedditPost) -> LegacyRedditCapture:
        external_id = f"t3_{parsed.post_id}"
        permalink_path = urlparse(parsed.permalink).path
        return {
            "fetched_at": self._timestamp(),
            "source": {
                "platform": "reddit",
                "external_id": external_id,
                "permalink": parsed.permalink,
                "subreddit": parsed.subreddit,
                "api": "url_html",
            },
            "post": {
                "id": parsed.post_id,
                "name": external_id,
                "title": parsed.title,
                "selftext": parsed.selftext,
                "author": parsed.author,
                "score": parsed.score,
                "created_utc": parsed.created_utc,
                "url": parsed.url,
                "permalink": permalink_path,
                "subreddit": parsed.subreddit,
                "num_comments": len(parsed.comments) or None,
            },
            "comments": [self._map_comment(comment) for comment in parsed.comments],
            "fetch_meta": {
                "user_agent": self._settings.user_agent,
                "fetcher": "url_html",
            },
        }

    @staticmethod
    def _map_comment(comment: ParsedRedditComment) -> dict[str, Any]:
        return {
            "id": comment.id,
            "name": comment.name,
            "body": comment.body,
            "author": comment.author,
            "score": comment.score,
            "created_utc": comment.created_utc,
            "parent_id": comment.parent_id,
            "depth": comment.depth,
            "permalink": comment.permalink,
        }

    def _validate(self, discussion: RawDiscussion, url: str) -> None:
        try:
            self._discussion_validator.validate(discussion, context=url)
        except ValueError as exc:
            raise URLCollectorSchemaError(str(exc)) from exc

    def _timestamp(self) -> str:
        timestamp = self._clock()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        return timestamp.astimezone(UTC).isoformat()

    @staticmethod
    def _normalize_fetch_url(url: str) -> str:
        parsed = urlparse(url.strip())
        netloc = parsed.netloc.lower()
        modern_hosts = {
            "reddit.com",
            "www.reddit.com",
            "np.reddit.com",
            "new.reddit.com",
        }
        if netloc in modern_hosts:
            return urlunparse(parsed._replace(netloc="old.reddit.com"))
        return url.strip()

    @staticmethod
    def _default_fetch_html(url: str, headers: dict[str, str], timeout: float) -> str:
        request = Request(url, headers=headers)
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return cast(str, response.read().decode(charset))
