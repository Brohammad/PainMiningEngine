"""Unit tests for the HTML-backed URL collector."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from backend.app.collector import (
    URLCollector,
    URLCollectorNetworkError,
    URLCollectorParseError,
    URLCollectorSettings,
)
from backend.app.collector.discussion import DiscussionSchemaValidator, _default_schema_directory
from backend.app.collector.url_parser import parse_reddit_html, parse_reddit_url
from backend.app.normalizer import RedditNormalizer

SCHEMA_DIRECTORY = Path(__file__).resolve().parents[1] / "schemas"
SCHEMA_VALIDATOR = Draft202012Validator(
    json.loads((SCHEMA_DIRECTORY / "raw_discussion.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
FIXED_TIME = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
DISCUSSION_URL = (
    "https://www.reddit.com/r/devops/comments/post1/certificate_rotation_is_painful/"
)

SHREDDIT_HTML = """
<html>
  <body>
    <shreddit-post
      post-id="t3_post1"
      post-title="Certificate rotation is painful"
      score="42"
      author="operator"
      subreddit-prefixed-name="r:devops"
      created-timestamp="2024-07-19T09:00:00.000Z"
      permalink="/r/devops/comments/post1/certificate_rotation_is_painful/"
    >
      <div slot="text-body">
        <div class="md"><p>Manual certificate rotation takes hours.</p></div>
      </div>
    </shreddit-post>
    <shreddit-comment
      thingid="t1_comment1"
      author="commenter"
      score="4"
      created-timestamp="2024-07-19T10:00:00.000Z"
      depth="0"
      comment="Try certbot weekly."
      permalink="/r/devops/comments/post1/thread/comment1/"
    ></shreddit-comment>
  </body>
</html>
"""

OLD_REDDIT_HTML = """
<html>
  <body>
    <div class="thing id-t3_post1 link">
      <p class="title"><a class="title">Certificate rotation is painful</a></p>
      <a class="author">operator</a>
      <div class="score unvoted">42 points</div>
      <time datetime="2024-07-19T09:00:00+00:00">posted</time>
      <div class="usertext-body">
        <div class="md"><p>Manual certificate rotation takes hours.</p></div>
      </div>
    </div>
    <div class="comment thing id-t1_comment1" data-fullname="t1_comment1">
      <div class="entry">
        <a class="author">commenter</a>
        <span class="score">4 points</span>
        <time datetime="2024-07-19T10:00:00+00:00">commented</time>
        <div class="usertext-body">
          <div class="md"><p>Try certbot weekly.</p></div>
        </div>
      </div>
    </div>
    <div class="child"></div>
  </body>
</html>
"""

LD_JSON_HTML = """
<html>
  <head>
    <script type="application/ld+json">
      {
        "@type": "DiscussionForumPosting",
        "headline": "Certificate rotation is painful",
        "articleBody": "Manual certificate rotation takes hours.",
        "author": {"name": "operator"},
        "datePublished": "2024-07-19T09:00:00+00:00",
        "interactionStatistic": {
          "userInteractionCount": 42
        }
      }
    </script>
  </head>
</html>
"""


def make_collector(
    html: str,
    *,
    settings: URLCollectorSettings | None = None,
) -> URLCollector:
    def fetch_html(url: str, headers: dict[str, str], timeout: float) -> str:
        assert headers["User-Agent"]
        assert timeout > 0
        assert "old.reddit.com" in url
        return html

    return URLCollector(
        settings or URLCollectorSettings(),
        fetch_html=fetch_html,
        clock=lambda: FIXED_TIME,
        schema_directory=SCHEMA_DIRECTORY,
    )


def assert_valid_capture(capture: dict[str, Any]) -> None:
    SCHEMA_VALIDATOR.validate(capture)


def test_parse_reddit_url_extracts_subreddit_and_post_id() -> None:
    subreddit, post_id = parse_reddit_url(DISCUSSION_URL)

    assert subreddit == "devops"
    assert post_id == "post1"


def test_parse_reddit_url_rejects_non_reddit_urls() -> None:
    with pytest.raises(URLCollectorParseError, match="unsupported Reddit URL"):
        parse_reddit_url("https://example.com/r/devops/comments/post1/")


def test_parse_reddit_html_from_shreddit_page() -> None:
    parsed = parse_reddit_html(SHREDDIT_HTML, DISCUSSION_URL)

    assert parsed.title == "Certificate rotation is painful"
    assert parsed.selftext == "Manual certificate rotation takes hours."
    assert parsed.author == "operator"
    assert parsed.score == 42
    assert parsed.subreddit == "devops"
    assert len(parsed.comments) == 1
    assert parsed.comments[0].body == "Try certbot weekly."


def test_parse_reddit_html_from_old_reddit_page() -> None:
    parsed = parse_reddit_html(OLD_REDDIT_HTML, DISCUSSION_URL)

    assert parsed.title == "Certificate rotation is painful"
    assert parsed.selftext == "Manual certificate rotation takes hours."
    assert parsed.author == "operator"
    assert parsed.score == 42
    assert len(parsed.comments) == 1
    assert parsed.comments[0].author == "commenter"


def test_parse_reddit_html_from_ld_json() -> None:
    parsed = parse_reddit_html(LD_JSON_HTML, DISCUSSION_URL)

    assert parsed.title == "Certificate rotation is painful"
    assert parsed.selftext == "Manual certificate rotation takes hours."
    assert parsed.author == "operator"
    assert parsed.score == 42
    assert parsed.comments == []


def test_fetch_post_returns_schema_valid_raw_discussion() -> None:
    capture = make_collector(SHREDDIT_HTML).fetch_post(DISCUSSION_URL)

    assert_valid_capture(capture)
    assert capture["source"] == "reddit"
    assert capture["metadata"]["api"] == "url_html"
    assert capture["title"] == "Certificate rotation is painful"
    assert capture["body"] == "Manual certificate rotation takes hours."
    assert capture["comments"][0]["body"] == "Try certbot weekly."
    assert capture["fetched_at"] == FIXED_TIME.isoformat()


def test_fetch_post_runs_through_normalizer() -> None:
    capture = make_collector(SHREDDIT_HTML).fetch_post(DISCUSSION_URL)

    normalized = RedditNormalizer(schema_directory=SCHEMA_DIRECTORY).normalize(capture)

    assert normalized["title"] == "Certificate rotation is painful"
    assert normalized["external_id"] == "t3_post1"


def test_fetch_post_rewrites_www_to_old_reddit(monkeypatch: pytest.MonkeyPatch) -> None:
    requested: list[str] = []

    def fetch_html(url: str, headers: dict[str, str], timeout: float) -> str:
        requested.append(url)
        return SHREDDIT_HTML

    collector = URLCollector(
        URLCollectorSettings(),
        fetch_html=fetch_html,
        clock=lambda: FIXED_TIME,
        schema_directory=SCHEMA_DIRECTORY,
    )
    collector.fetch_post(DISCUSSION_URL)

    assert requested == [
        "https://old.reddit.com/r/devops/comments/post1/certificate_rotation_is_painful/"
    ]


def test_fetch_post_rejects_non_reddit_url_before_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fetch_html(url: str, headers: dict[str, str], timeout: float) -> str:
        calls.append(url)
        return SHREDDIT_HTML

    collector = URLCollector(
        URLCollectorSettings(),
        fetch_html=fetch_html,
        schema_directory=SCHEMA_DIRECTORY,
    )

    with pytest.raises(URLCollectorParseError, match="unsupported Reddit URL"):
        collector.fetch_post("https://example.com/private")

    assert calls == []


def test_fetch_post_rejects_empty_url() -> None:
    with pytest.raises(ValueError, match="target must not be empty"):
        make_collector(SHREDDIT_HTML).fetch_post("  ")


def test_fetch_post_wraps_http_errors() -> None:
    def fetch_html(url: str, headers: dict[str, str], timeout: float) -> str:
        raise HTTPError(url, 404, "not found", hdrs=None, fp=None)

    collector = URLCollector(
        URLCollectorSettings(),
        fetch_html=fetch_html,
        schema_directory=SCHEMA_DIRECTORY,
    )

    with pytest.raises(URLCollectorNetworkError, match="HTTP 404"):
        collector.fetch_post(DISCUSSION_URL)


def test_fetch_post_wraps_network_errors() -> None:
    def fetch_html(url: str, headers: dict[str, str], timeout: float) -> str:
        raise URLError("offline")

    collector = URLCollector(
        URLCollectorSettings(),
        fetch_html=fetch_html,
        schema_directory=SCHEMA_DIRECTORY,
    )

    with pytest.raises(URLCollectorNetworkError, match="unable to retrieve HTML"):
        collector.fetch_post(DISCUSSION_URL)


def test_fetch_post_rejects_unparseable_html() -> None:
    with pytest.raises(URLCollectorParseError, match="unable to extract Reddit post"):
        make_collector("<html><body>nothing here</body></html>").fetch_post(
            DISCUSSION_URL
        )


def test_url_collector_settings_load_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("URL_COLLECTOR_USER_AGENT", "custom-agent/2.0")
    monkeypatch.setenv("URL_COLLECTOR_REQUEST_TIMEOUT_SECONDS", "30")

    settings = URLCollectorSettings(_env_file=None)

    assert settings.user_agent == "custom-agent/2.0"
    assert settings.request_timeout_seconds == 30.0


def test_default_schema_directory_prefers_repository_schemas() -> None:
    directory = _default_schema_directory()

    assert directory.name == "schemas"
    assert (directory / "raw_discussion.json").is_file()


def test_default_schema_directory_falls_back_to_packaged_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_schemas = Path(__file__).resolve().parents[1] / "schemas"
    expected = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "app"
        / "schemas"
        / "contracts"
    )
    original_is_dir = Path.is_dir

    def selective_is_dir(self: Path) -> bool:
        if self == repo_schemas:
            return False
        return original_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", selective_is_dir)

    directory = _default_schema_directory()

    assert directory == expected
