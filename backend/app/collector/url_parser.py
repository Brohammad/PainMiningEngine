"""Parse Reddit discussion pages from HTML into structured post data."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from backend.app.collector.exceptions import URLCollectorParseError

REDDIT_POST_URL_RE = re.compile(
    r"^https?://(?:(?:www|old|np|new)\.)?reddit\.com/r/(?P<subreddit>[^/]+)/comments/(?P<post_id>[^/]+)",
    re.IGNORECASE,
)
SHREDDIT_POST_RE = re.compile(r"<shreddit-post\b([^>]*)>", re.IGNORECASE)
SHREDDIT_COMMENT_RE = re.compile(r"<shreddit-comment\b([^>]*)>", re.IGNORECASE)
LD_JSON_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
OLD_REDDIT_TITLE_RE = re.compile(
    r'<a[^>]*class="[^"]*\btitle\b[^"]*"[^>]*>([^<]+)</a>',
    re.IGNORECASE,
)
OLD_REDDIT_AUTHOR_RE = re.compile(
    r'<a[^>]*class="[^"]*\bauthor\b[^"]*"[^>]*>([^<]+)</a>',
    re.IGNORECASE,
)
OLD_REDDIT_SCORE_RE = re.compile(
    r'<div[^>]*class="[^"]*\bscore\b[^"]*"[^>]*>\s*([-\d]+)',
    re.IGNORECASE,
)
OLD_REDDIT_TIME_RE = re.compile(
    r'<time[^>]*datetime="([^"]+)"',
    re.IGNORECASE,
)
OLD_REDDIT_BODY_RE = re.compile(
    r'<div[^>]*class="[^"]*\busertext-body\b[^"]*"[^>]*>.*?<div[^>]*class="[^"]*\bmd\b[^"]*"[^>]*>(.*?)</div>',
    re.DOTALL | re.IGNORECASE,
)
OLD_REDDIT_COMMENT_RE = re.compile(
    r'<div[^>]*class="[^"]*\bcomment\b[^"]*thing\b[^"]*"[^>]*data-fullname="(?P<fullname>[^"]+)"[^>]*>(?P<body>.*?)</div>\s*(?=<div[^>]*class="[^"]*\bchild\b|$)',
    re.DOTALL | re.IGNORECASE,
)
ATTR_RE = re.compile(r'([\w-]+)=["\']([^"\']*)["\']')


@dataclass(frozen=True)
class ParsedRedditComment:
    id: str
    name: str
    body: str
    author: str | None
    score: int
    created_utc: float
    parent_id: str | None = None
    depth: int | None = None
    permalink: str | None = None


@dataclass
class ParsedRedditPost:
    post_id: str
    subreddit: str
    title: str
    selftext: str
    author: str | None
    score: int
    created_utc: float
    permalink: str
    url: str
    comments: list[ParsedRedditComment] = field(default_factory=list)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self._parts)).strip()


def parse_reddit_url(url: str) -> tuple[str, str]:
    """Return subreddit and post id parsed from a Reddit discussion URL."""

    match = REDDIT_POST_URL_RE.match(url.strip())
    if match is None:
        raise URLCollectorParseError(f"unsupported Reddit URL: {url}")
    return match.group("subreddit"), match.group("post_id")


def parse_reddit_html(html: str, url: str) -> ParsedRedditPost:
    """Extract post fields from Reddit HTML."""

    subreddit, post_id = parse_reddit_url(url)
    parsers = (
        _parse_shreddit_html,
        _parse_old_reddit_html,
        _parse_ld_json_html,
    )
    errors: list[str] = []
    for parser in parsers:
        try:
            parsed = parser(html, url, subreddit, post_id)
        except URLCollectorParseError as exc:
            errors.append(str(exc))
            continue
        if parsed.title:
            return parsed
        errors.append(f"{parser.__name__} did not find a title")

    detail = "; ".join(errors) if errors else "no parser matched"
    raise URLCollectorParseError(f"unable to extract Reddit post from HTML: {detail}")


def _parse_shreddit_html(
    html: str,
    url: str,
    subreddit: str,
    post_id: str,
) -> ParsedRedditPost:
    post_match = SHREDDIT_POST_RE.search(html)
    if post_match is None:
        raise URLCollectorParseError("shreddit-post element not found")

    attrs = _parse_attributes(post_match.group(1))
    title = attrs.get("post-title", "").strip()
    if not title:
        raise URLCollectorParseError("shreddit-post is missing post-title")

    external_id = attrs.get("post-id") or f"t3_{post_id}"
    permalink_path = attrs.get("permalink") or f"/r/{subreddit}/comments/{post_id}/"
    selftext = _extract_shreddit_body(html)
    comments = _parse_shreddit_comments(html, external_id)

    return ParsedRedditPost(
        post_id=post_id,
        subreddit=_normalize_subreddit(attrs.get("subreddit-prefixed-name"), subreddit),
        title=title,
        selftext=selftext,
        author=_optional_string(attrs.get("author")),
        score=_parse_int(attrs.get("score")),
        created_utc=_parse_timestamp(attrs.get("created-timestamp")),
        permalink=_absolute_permalink(permalink_path, url),
        url=url,
        comments=comments,
    )


def _parse_old_reddit_html(
    html: str,
    url: str,
    subreddit: str,
    post_id: str,
) -> ParsedRedditPost:
    title_match = OLD_REDDIT_TITLE_RE.search(html)
    if title_match is None:
        raise URLCollectorParseError("old reddit title not found")

    author_match = OLD_REDDIT_AUTHOR_RE.search(html)
    score_match = OLD_REDDIT_SCORE_RE.search(html)
    time_match = OLD_REDDIT_TIME_RE.search(html)
    body_match = OLD_REDDIT_BODY_RE.search(html)
    comments = _parse_old_reddit_comments(html, f"t3_{post_id}")

    return ParsedRedditPost(
        post_id=post_id,
        subreddit=subreddit,
        title=_strip_html(title_match.group(1)),
        selftext=_strip_html(body_match.group(1)) if body_match else "",
        author=_optional_string(
            _strip_html(author_match.group(1)) if author_match else None
        ),
        score=_parse_int(score_match.group(1) if score_match else None),
        created_utc=_parse_timestamp(time_match.group(1) if time_match else None),
        permalink=_absolute_permalink(f"/r/{subreddit}/comments/{post_id}/", url),
        url=url,
        comments=comments,
    )


def _parse_ld_json_html(
    html: str,
    url: str,
    subreddit: str,
    post_id: str,
) -> ParsedRedditPost:
    for match in LD_JSON_RE.finditer(html):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        parsed = _parse_ld_json_payload(payload, url, subreddit, post_id)
        if parsed is not None:
            return parsed
    raise URLCollectorParseError("application/ld+json post data not found")


def _parse_ld_json_payload(
    payload: object,
    url: str,
    subreddit: str,
    post_id: str,
) -> ParsedRedditPost | None:
    items: list[dict[str, Any]]
    if isinstance(payload, list):
        items = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        items = [payload]
    else:
        return None

    for item in items:
        item_type = item.get("@type")
        if item_type not in {"DiscussionForumPosting", "SocialMediaPosting"}:
            continue
        author = item.get("author")
        author_name = None
        if isinstance(author, dict):
            author_name = _optional_string(author.get("name"))
        interaction = item.get("interactionStatistic")
        score = 0
        if isinstance(interaction, dict):
            score = _parse_int(interaction.get("userInteractionCount"))
        return ParsedRedditPost(
            post_id=post_id,
            subreddit=subreddit,
            title=str(item.get("headline") or ""),
            selftext=str(item.get("articleBody") or ""),
            author=author_name,
            score=score,
            created_utc=_parse_timestamp(str(item.get("datePublished") or "")),
            permalink=_absolute_permalink(
                f"/r/{subreddit}/comments/{post_id}/",
                url,
            ),
            url=url,
            comments=[],
        )
    return None


def _parse_shreddit_comments(
    html: str,
    parent_id: str,
) -> list[ParsedRedditComment]:
    comments: list[ParsedRedditComment] = []
    for match in SHREDDIT_COMMENT_RE.finditer(html):
        attrs = _parse_attributes(match.group(1))
        thing_id = attrs.get("thingid", "").removeprefix("t1_")
        comment_id = thing_id or attrs.get("comment-id", "")
        if not comment_id:
            continue
        comments.append(
            ParsedRedditComment(
                id=comment_id,
                name=attrs.get("thingid") or f"t1_{comment_id}",
                body=attrs.get("comment") or attrs.get("body") or "",
                author=_optional_string(attrs.get("author")),
                score=_parse_int(attrs.get("score")),
                created_utc=_parse_timestamp(attrs.get("created-timestamp")),
                parent_id=parent_id,
                depth=_parse_optional_int(attrs.get("depth")),
                permalink=attrs.get("permalink"),
            )
        )
    return comments


def _parse_old_reddit_comments(
    html: str,
    parent_id: str,
) -> list[ParsedRedditComment]:
    comments: list[ParsedRedditComment] = []
    for match in OLD_REDDIT_COMMENT_RE.finditer(html):
        fullname = match.group("fullname")
        comment_id = fullname.removeprefix("t1_")
        fragment = match.group("body")
        author_match = OLD_REDDIT_AUTHOR_RE.search(fragment)
        score_match = OLD_REDDIT_SCORE_RE.search(fragment)
        time_match = OLD_REDDIT_TIME_RE.search(fragment)
        body_match = OLD_REDDIT_BODY_RE.search(fragment)
        created_at = time_match.group(1) if time_match else None
        comments.append(
            ParsedRedditComment(
                id=comment_id,
                name=fullname,
                body=_strip_html(body_match.group(1)) if body_match else "",
                author=_optional_string(
                    _strip_html(author_match.group(1)) if author_match else None
                ),
                score=_parse_int(score_match.group(1) if score_match else None),
                created_utc=_parse_timestamp(created_at),
                parent_id=parent_id,
                depth=0,
            )
        )
    return comments


def _extract_shreddit_body(html: str) -> str:
    body_match = re.search(
        r'<div[^>]*slot="text-body"[^>]*>(.*?)</div>\s*</shreddit-post>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if body_match is None:
        return ""
    return _strip_html(body_match.group(1))


def _parse_attributes(fragment: str) -> dict[str, str]:
    return {name: value for name, value in ATTR_RE.findall(fragment)}


def _normalize_subreddit(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    text = value.strip()
    if text.startswith("r:"):
        return text[2:]
    return text.removeprefix("r/").removeprefix("/r/")


def _absolute_permalink(permalink: str, source_url: str) -> str:
    if permalink.startswith(("https://", "http://")):
        return permalink
    path = permalink if permalink.startswith("/") else f"/{permalink}"
    parsed = urlparse(source_url)
    netloc = parsed.netloc or "www.reddit.com"
    return f"{parsed.scheme or 'https'}://{netloc}{path}"


def _strip_html(fragment: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(fragment)
    extractor.close()
    return extractor.text()


def _optional_string(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_int(value: object | None) -> int:
    if value is None:
        return 0
    try:
        return int(str(value).split()[0])
    except ValueError:
        return 0


def _parse_optional_int(value: object | None) -> int | None:
    if value is None:
        return None
    return _parse_int(value)


def _parse_timestamp(value: str | None) -> float:
    if not value:
        return 0.0
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).timestamp()
