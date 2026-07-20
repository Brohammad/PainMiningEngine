"""Unit tests for the PRAW-backed Reddit collector."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import requests
from jsonschema import Draft202012Validator, FormatChecker
from prawcore.exceptions import RequestException, TooManyRequests

from backend.app.collector import (
    RedditCollector,
    RedditNetworkError,
    RedditSettings,
)
from backend.app.observability import (
    ObservabilitySettings,
    Telemetry,
    TelemetryRecorder,
)

SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "raw_discussion.json"
RAW_DISCUSSION_SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
SCHEMA_VALIDATOR = Draft202012Validator(
    RAW_DISCUSSION_SCHEMA,
    format_checker=FormatChecker(),
)
FIXED_TIME = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)


class FakeCommentForest:
    """Minimal PRAW comment-forest test double."""

    def __init__(self, comments: list[SimpleNamespace]) -> None:
        self._comments = comments
        self.replace_more_calls: list[int] = []

    def replace_more(self, *, limit: int) -> None:
        self.replace_more_calls.append(limit)

    def list(self) -> list[SimpleNamespace]:
        return self._comments


class FakeSubreddit:
    """Minimal PRAW subreddit test double."""

    def __init__(self, submissions: list[SimpleNamespace]) -> None:
        self._submissions = submissions
        self.hot_limits: list[int] = []
        self.search_calls: list[tuple[str, str, int]] = []

    def hot(self, *, limit: int) -> Iterator[SimpleNamespace]:
        self.hot_limits.append(limit)
        return iter(self._submissions[:limit])

    def search(
        self,
        query: str,
        *,
        sort: str,
        limit: int,
    ) -> Iterator[SimpleNamespace]:
        self.search_calls.append((query, sort, limit))
        return iter(self._submissions[:limit])


class FakeReddit:
    """Minimal injectable PRAW client test double."""

    def __init__(
        self,
        submissions: list[SimpleNamespace],
        submission_effects: list[object] | None = None,
    ) -> None:
        self.submissions = submissions
        self.submission_effects = list(submission_effects or submissions[:1])
        self.subreddit_object = FakeSubreddit(submissions)
        self.submission_urls: list[str] = []
        self.subreddit_names: list[str] = []

    def submission(self, *, url: str) -> SimpleNamespace:
        self.submission_urls.append(url)
        effect = self.submission_effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return cast(SimpleNamespace, effect)

    def subreddit(self, name: str) -> FakeSubreddit:
        self.subreddit_names.append(name)
        return self.subreddit_object


def make_settings(**overrides: Any) -> RedditSettings:
    values: dict[str, Any] = {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "user_agent": "signalmine-tests/1.0",
        "retry_backoff_seconds": 0.25,
        "comment_limit": 2,
        "comment_max_depth": 3,
    }
    values.update(overrides)
    return RedditSettings(**values)


def make_comment(
    comment_id: str,
    *,
    score: int,
    depth: int = 0,
    author: str | None = "commenter",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=comment_id,
        name=f"t1_{comment_id}",
        body=f"Comment body {comment_id}",
        author=author,
        score=score,
        created_utc=1_721_380_000.0,
        parent_id="t3_post1",
        depth=depth,
        permalink=f"/r/devops/comments/post1/thread/{comment_id}/",
    )


def make_submission(
    submission_id: str = "post1",
    *,
    selftext: str = "Manual certificate rotation takes hours.",
    author: str | None = "operator",
) -> SimpleNamespace:
    comments = FakeCommentForest(
        [
            make_comment("low", score=2),
            make_comment("high", score=10, author=None),
            make_comment("deep", score=50, depth=4),
        ]
    )
    return SimpleNamespace(
        id=submission_id,
        name=f"t3_{submission_id}",
        title="Certificate rotation is painful",
        selftext=selftext,
        author=author,
        score=42,
        upvote_ratio=0.95,
        num_comments=3,
        created_utc=1_721_379_600.0,
        url=f"https://www.reddit.com/r/devops/comments/{submission_id}/",
        permalink=f"/r/devops/comments/{submission_id}/certificate_rotation/",
        subreddit="devops",
        link_flair_text="Discussion",
        over_18=False,
        is_self=True,
        comments=comments,
    )


def make_collector(
    reddit: FakeReddit,
    *,
    settings: RedditSettings | None = None,
    delays: list[float] | None = None,
    telemetry: TelemetryRecorder | None = None,
) -> RedditCollector:
    recorded_delays = delays if delays is not None else []
    return RedditCollector(
        settings or make_settings(),
        reddit=cast(Any, reddit),
        sleeper=recorded_delays.append,
        clock=lambda: FIXED_TIME,
        telemetry=telemetry,
    )


def assert_valid_capture(capture: dict[str, Any]) -> None:
    SCHEMA_VALIDATOR.validate(capture)


def test_reddit_settings_loads_credentials_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REDDIT_CLIENT_ID", "environment-client")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "environment-secret")
    monkeypatch.setenv("REDDIT_USER_AGENT", "signalmine-environment/1.0")

    settings = RedditSettings(_env_file=None)

    assert settings.client_id == "environment-client"
    assert settings.client_secret.get_secret_value() == "environment-secret"
    assert settings.user_agent == "signalmine-environment/1.0"


@pytest.mark.parametrize("marker", ["[deleted]", "[removed]"])
def test_fetch_post_maps_deleted_and_removed_posts(marker: str) -> None:
    submission = make_submission(selftext=marker, author=None)
    reddit = FakeReddit([submission])
    collector = make_collector(reddit)

    capture = collector.fetch_post(submission.url)

    assert_valid_capture(capture)
    assert capture["body"] == marker
    assert capture["author"] is None
    assert capture["discussion_id"] == "t3_post1"
    assert [comment["id"] for comment in capture["comments"]] == ["high", "low"]
    assert capture["comments"][0]["author"] is None
    assert reddit.submission_urls == [submission.url]


def test_fetch_subreddit_maps_each_post_to_raw_schema() -> None:
    submissions = [make_submission("first"), make_submission("second")]
    reddit = FakeReddit(submissions)
    collector = make_collector(reddit)

    captures = collector.fetch_subreddit("devops", limit=2)

    assert len(captures) == 2
    assert all(not list(SCHEMA_VALIDATOR.iter_errors(item)) for item in captures)
    assert [item["discussion_id"] for item in captures] == ["t3_first", "t3_second"]
    assert reddit.subreddit_names == ["devops"]
    assert reddit.subreddit_object.hot_limits == [2]


def test_fetch_search_maps_results_and_forwards_search_options() -> None:
    submission = make_submission()
    reddit = FakeReddit([submission])
    collector = make_collector(reddit)

    captures = collector.fetch_search(
        "certificate rotation",
        subreddit="devops",
        limit=1,
    )

    assert len(captures) == 1
    assert_valid_capture(captures[0])
    assert reddit.subreddit_object.search_calls == [
        ("certificate rotation", "relevance", 1)
    ]


def test_fetch_post_retries_rate_limit_using_retry_after() -> None:
    response = requests.Response()
    response.status_code = 429
    response.headers["Retry-After"] = "2"
    rate_limit = TooManyRequests(response)
    submission = make_submission()
    reddit = FakeReddit(
        [submission],
        submission_effects=[rate_limit, submission],
    )
    delays: list[float] = []
    telemetry = Telemetry(ObservabilitySettings(service_name="collector-tests"))
    collector = make_collector(reddit, delays=delays, telemetry=telemetry)

    capture = collector.fetch_post(submission.url)

    assert_valid_capture(capture)
    assert delays == [2.0]
    assert reddit.submission_urls == [submission.url, submission.url]
    assert (
        'signalmine_retries_total{component="reddit",reason="rate_limit"} 1.0'
        in telemetry.render_prometheus().decode()
    )


def test_fetch_post_wraps_exhausted_network_failures() -> None:
    failures = [
        RequestException(OSError("offline"), (), {}),
        RequestException(OSError("still offline"), (), {}),
    ]
    submission = make_submission()
    reddit = FakeReddit([submission], submission_effects=failures)
    delays: list[float] = []
    collector = make_collector(
        reddit,
        settings=make_settings(retry_attempts=2),
        delays=delays,
    )

    with pytest.raises(RedditNetworkError):
        collector.fetch_post(submission.url)

    assert delays == [0.25]
