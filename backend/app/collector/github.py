"""GitHub REST issue collection mapped to RawDiscussion."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from time import sleep
from typing import Any, TypeVar, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app.collector.discussion import DiscussionSchemaValidator
from backend.app.collector.exceptions import (
    GitHubNetworkError,
    GitHubParseError,
    GitHubRateLimitError,
    GitHubResourceUnavailableError,
)
from backend.app.collector.github_parser import (
    canonicalize_github_issue_url,
    discussion_id_for_issue,
    parse_github_issue_url,
)
from backend.app.collector.github_settings import GitHubSettings
from backend.app.collector.sources import DiscussionSource
from backend.app.collector.types import RawDiscussion
from backend.app.observability import NoOpTelemetry, TelemetryRecorder

T = TypeVar("T")


class GitHubCollector:
    """Collect GitHub issues and comments without normalizing or persisting them."""

    def __init__(
        self,
        settings: GitHubSettings,
        *,
        fetch_json: Callable[[str, dict[str, str], float], Any] | None = None,
        sleeper: Callable[[float], None] = sleep,
        clock: Callable[[], datetime] | None = None,
        telemetry: TelemetryRecorder | None = None,
        schema_directory: Any | None = None,
    ) -> None:
        self._settings = settings
        self._fetch_json = fetch_json or self._default_fetch_json
        self._sleep = sleeper
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)
        self._telemetry = telemetry or NoOpTelemetry()
        self._discussion_validator = DiscussionSchemaValidator(schema_directory)

    def fetch(self, target: str) -> RawDiscussion:
        """Fetch one GitHub issue by URL."""

        if not target.strip():
            raise ValueError("target must not be empty")

        owner, repo, number = parse_github_issue_url(target)
        issue = self._execute(
            lambda: self._fetch_issue(owner, repo, number),
            context=f"{owner}/{repo}#{number}",
        )
        comments = self._execute(
            lambda: self._fetch_comments(owner, repo, number),
            context=f"{owner}/{repo}#{number}/comments",
        )
        discussion = self._map_to_discussion(
            issue,
            comments,
            owner=owner,
            repo=repo,
            number=number,
        )
        self._discussion_validator.validate(discussion, context=target)
        return discussion

    def fetch_post(self, target: str) -> RawDiscussion:
        """Backward-compatible alias for :meth:`fetch`."""

        return self.fetch(target)

    def _fetch_issue(self, owner: str, repo: str, number: int) -> dict[str, Any]:
        url = (
            f"{self._settings.api_base_url.rstrip('/')}/repos/"
            f"{owner}/{repo}/issues/{number}"
        )
        payload = self._fetch_json(
            url,
            self._headers(),
            self._settings.request_timeout_seconds,
        )
        if not isinstance(payload, dict):
            raise GitHubNetworkError("GitHub issue response was not a JSON object")
        return cast(dict[str, Any], payload)

    def _fetch_comments(self, owner: str, repo: str, number: int) -> list[dict[str, Any]]:
        url = (
            f"{self._settings.api_base_url.rstrip('/')}/repos/"
            f"{owner}/{repo}/issues/{number}/comments"
        )
        payload = self._fetch_json(
            url,
            self._headers(),
            self._settings.request_timeout_seconds,
        )
        if not isinstance(payload, list):
            raise GitHubNetworkError("GitHub comments response was not a JSON array")
        return [cast(dict[str, Any], item) for item in payload]

    def _map_to_discussion(
        self,
        issue: Mapping[str, Any],
        comments: list[Mapping[str, Any]],
        *,
        owner: str,
        repo: str,
        number: int,
    ) -> RawDiscussion:
        repository = f"{owner}/{repo}"
        mapped_comments = [
            self._map_comment(comment)
            for comment in comments[: self._settings.comment_limit]
        ]
        return {
            "fetched_at": self._timestamp(),
            "source": DiscussionSource.GITHUB.value,
            "discussion_id": discussion_id_for_issue(owner, repo, number),
            "title": str(issue.get("title", "")),
            "body": str(issue.get("body") or ""),
            "comments": mapped_comments,
            "author": self._login(issue.get("user")),
            "created_at": str(issue["created_at"]),
            "updated_at": str(issue["updated_at"]),
            "url": canonicalize_github_issue_url(owner, repo, number),
            "metadata": {
                "repository": repository,
                "owner": owner,
                "repo": repo,
                "issue_number": number,
                "state": issue.get("state"),
                "labels": [
                    str(label.get("name"))
                    for label in cast(list[dict[str, Any]], issue.get("labels", []))
                    if label.get("name") is not None
                ],
                "assignees": [
                    login
                    for login in (
                        self._login(assignee)
                        for assignee in cast(
                            list[dict[str, Any]], issue.get("assignees", [])
                        )
                    )
                    if login is not None
                ],
                "reactions": issue.get("reactions"),
                "api": "github_rest",
                "fetch_meta": {
                    "comment_limit": self._settings.comment_limit,
                },
            },
        }

    @staticmethod
    def _map_comment(comment: Mapping[str, Any]) -> dict[str, Any]:
        created_at = str(comment["created_at"])
        updated_at = str(comment.get("updated_at") or created_at)
        reactions = cast(dict[str, Any], comment.get("reactions", {}))
        score = int(reactions.get("total_count", 0) or 0)
        return {
            "id": str(comment["id"]),
            "body": str(comment.get("body") or ""),
            "author": GitHubCollector._login(comment.get("user")),
            "created_at": created_at,
            "updated_at": updated_at,
            "score": score,
            "parent_id": None,
            "depth": 0,
            "metadata": {
                "node_id": comment.get("node_id"),
                "html_url": comment.get("html_url"),
            },
        }

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": self._settings.user_agent,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._settings.token is not None:
            headers["Authorization"] = (
                f"Bearer {self._settings.token.get_secret_value()}"
            )
        return headers

    def _execute(self, operation: Callable[[], T], *, context: str) -> T:
        for attempt in range(self._settings.retry_attempts):
            try:
                return operation()
            except HTTPError as exc:
                if exc.code in {403, 429}:
                    if attempt + 1 >= self._settings.retry_attempts:
                        raise GitHubRateLimitError(
                            f"GitHub rate limit retries exhausted for {context}"
                        ) from exc
                    delay = self._retry_delay(attempt, exc)
                    self._telemetry.record_retry("github", "rate_limit", delay)
                    self._sleep(delay)
                    continue
                if exc.code in {404, 410}:
                    raise GitHubResourceUnavailableError(
                        f"GitHub resource is unavailable: {context}"
                    ) from exc
                if exc.code >= 500:
                    if attempt + 1 >= self._settings.retry_attempts:
                        raise GitHubNetworkError(
                            f"GitHub server error retries exhausted for {context}"
                        ) from exc
                    delay = self._retry_delay(attempt)
                    self._telemetry.record_retry("github", "network", delay)
                    self._sleep(delay)
                    continue
                raise GitHubNetworkError(
                    f"GitHub returned HTTP {exc.code} for {context}"
                ) from exc
            except URLError as exc:
                if attempt + 1 >= self._settings.retry_attempts:
                    raise GitHubNetworkError(
                        f"GitHub network retries exhausted for {context}"
                    ) from exc
                delay = self._retry_delay(attempt)
                self._telemetry.record_retry("github", "network", delay)
                self._sleep(delay)
            except GitHubParseError:
                raise
            except GitHubResourceUnavailableError:
                raise
        raise GitHubNetworkError(f"GitHub retries exhausted for {context}")

    def _retry_delay(self, attempt: int, exc: HTTPError | None = None) -> float:
        if exc is not None and exc.headers is not None:
            retry_after = exc.headers.get("Retry-After")
            if retry_after is not None:
                try:
                    return float(retry_after)
                except ValueError:
                    pass
        return self._settings.retry_backoff_seconds * (2**attempt)

    def _timestamp(self) -> str:
        timestamp = self._clock()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        return timestamp.astimezone(UTC).isoformat()

    @staticmethod
    def _login(user: object | None) -> str | None:
        if not isinstance(user, dict):
            return None
        login = user.get("login")
        return None if login is None else str(login)

    @staticmethod
    def _default_fetch_json(
        url: str,
        headers: dict[str, str],
        timeout: float,
    ) -> Any:
        request = Request(url, headers=headers)
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset))
