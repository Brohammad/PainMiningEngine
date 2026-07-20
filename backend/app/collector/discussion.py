"""RawDiscussion validation and legacy capture conversion."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, cast

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from jsonschema.protocols import Validator

from backend.app.collector.sources import DiscussionSource
from backend.app.collector.types import LegacyRedditCapture, RawDiscussion


def is_raw_discussion(payload: Mapping[str, Any]) -> bool:
    """Return whether a payload already matches the RawDiscussion shape."""

    required = {
        "fetched_at",
        "source",
        "discussion_id",
        "title",
        "body",
        "comments",
        "author",
        "created_at",
        "updated_at",
        "url",
        "metadata",
    }
    return required.issubset(payload.keys())


def is_legacy_reddit_capture(payload: Mapping[str, Any]) -> bool:
    """Return whether a payload matches the legacy Reddit envelope."""

    return {"fetched_at", "source", "post"}.issubset(payload.keys())


def coerce_to_discussion(payload: dict[str, Any]) -> RawDiscussion:
    """Normalize legacy or current payloads into one RawDiscussion."""

    if is_raw_discussion(payload):
        return cast(RawDiscussion, payload)
    if is_legacy_reddit_capture(payload):
        return legacy_reddit_to_discussion(cast(LegacyRedditCapture, payload))
    raise ValueError("payload is neither RawDiscussion nor legacy Reddit capture")


def legacy_reddit_to_discussion(capture: LegacyRedditCapture) -> RawDiscussion:
    """Convert one legacy Reddit envelope into a RawDiscussion."""

    source = cast(dict[str, Any], capture["source"])
    post = cast(dict[str, Any], capture["post"])
    created_at = _epoch_timestamp(post["created_utc"])
    updated_value = post.get("edited_utc", post["created_utc"])
    updated_at = _epoch_timestamp(updated_value)
    comments = [
        _legacy_reddit_comment_to_discussion(comment)
        for comment in cast(list[dict[str, Any]], capture.get("comments", []))
    ]
    metadata = {
        "subreddit": source.get("subreddit"),
        "score": post.get("score", 0),
        "upvote_ratio": post.get("upvote_ratio"),
        "num_comments": post.get("num_comments"),
        "link_flair_text": post.get("link_flair_text"),
        "over_18": post.get("over_18"),
        "is_self": post.get("is_self"),
        "source_post_url": post.get("url"),
        "api": source.get("api"),
        "fetch_meta": capture.get("fetch_meta", {}),
    }
    return {
        "fetched_at": str(capture["fetched_at"]),
        "source": DiscussionSource.REDDIT.value,
        "discussion_id": str(source["external_id"]),
        "title": str(post.get("title", "")),
        "body": str(post.get("selftext", "")),
        "comments": comments,
        "author": post.get("author"),
        "created_at": created_at,
        "updated_at": updated_at,
        "url": str(source["permalink"]),
        "metadata": metadata,
    }


def _legacy_reddit_comment_to_discussion(comment: dict[str, Any]) -> dict[str, Any]:
    created_at = _epoch_timestamp(comment["created_utc"])
    return {
        "id": str(comment["id"]),
        "body": str(comment.get("body", "")),
        "author": comment.get("author"),
        "created_at": created_at,
        "updated_at": created_at,
        "score": int(comment.get("score", 0) or 0),
        "parent_id": comment.get("parent_id"),
        "depth": int(comment.get("depth", 0) or 0),
        "metadata": {
            "name": comment.get("name"),
            "permalink": comment.get("permalink"),
        },
    }


def _epoch_timestamp(value: Any) -> str:
    return datetime.fromtimestamp(float(value), tz=UTC).isoformat()


class DiscussionSchemaValidator:
    """Validate payloads against the RawDiscussion JSON Schema."""

    def __init__(self, schema_directory: Path | None = None) -> None:
        schema_path = schema_directory or _default_schema_directory()
        self._validator: Validator = Draft202012Validator(
            _load_schema(schema_path / "raw_discussion.json"),
            format_checker=FormatChecker(),
        )

    def validate(self, discussion: RawDiscussion, *, context: str = "discussion") -> None:
        try:
            self._validator.validate(discussion)
        except ValidationError as exc:
            location = ".".join(str(part) for part in exc.absolute_path) or "<root>"
            raise ValueError(
                f"schema validation failed for {context}: {location}: {exc.message}"
            ) from exc


def _default_schema_directory() -> Path:
    repository_schemas = Path(__file__).resolve().parents[3] / "schemas"
    if repository_schemas.is_dir():
        return repository_schemas
    return Path(__file__).resolve().parents[1] / "schemas" / "contracts"


def _load_schema(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
