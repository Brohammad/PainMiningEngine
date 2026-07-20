"""Deterministic RawDiscussion-to-NormalizedDocument conversion for Reddit."""

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.protocols import Validator
from markdown_it import MarkdownIt
from markdown_it.token import Token

from backend.app.collector.types import RawDiscussion

NormalizedPost = dict[str, Any]


class RedditNormalizer:
    """Normalize Reddit RawDiscussion captures without inference or side effects."""

    def __init__(self, schema_directory: Path | None = None) -> None:
        schema_path = schema_directory or self._default_schema_directory()
        format_checker = FormatChecker()
        self._discussion_validator: Validator = Draft202012Validator(
            self._load_schema(schema_path / "raw_discussion.json"),
            format_checker=format_checker,
        )
        self._normalized_validator: Validator = Draft202012Validator(
            self._load_schema(schema_path / "normalized_document.json"),
            format_checker=format_checker,
        )
        self._markdown = MarkdownIt("commonmark", {"html": False})

    def normalize(self, discussion: RawDiscussion) -> NormalizedPost:
        """Return one schema-valid normalized document."""

        self._discussion_validator.validate(discussion)
        metadata = cast(dict[str, Any], discussion.get("metadata", {}))
        raw_comments = cast(list[Mapping[str, Any]], discussion.get("comments", []))

        comments, original_comments = self._normalize_comments(raw_comments)
        platform = str(discussion["source"])
        external_id = str(discussion["discussion_id"])

        normalized: NormalizedPost = {
            "id": str(uuid5(NAMESPACE_URL, f"{platform}:{external_id}")),
            "platform": platform,
            "external_id": external_id,
            "url": str(discussion["url"]),
            "title": self._clean_text(str(discussion["title"])),
            "content": self._clean_text(str(discussion["body"])),
            "comments": comments,
            "author": self._optional_string(discussion.get("author")),
            "score": int(metadata.get("score", 0) or 0),
            "created_at": self._date_timestamp(str(discussion["created_at"])),
            "fetched_at": self._date_timestamp(str(discussion["fetched_at"])),
            "community": self._optional_string(metadata.get("subreddit")),
            "metadata": {
                "original_text": {
                    "title": str(discussion["title"]),
                    "content": str(discussion["body"]),
                    "comments": original_comments,
                },
                "source_post": {
                    "url": metadata.get("source_post_url"),
                    "upvote_ratio": metadata.get("upvote_ratio"),
                    "num_comments": metadata.get("num_comments"),
                    "link_flair_text": metadata.get("link_flair_text"),
                    "over_18": metadata.get("over_18"),
                    "is_self": metadata.get("is_self"),
                },
                "fetch_meta": metadata.get("fetch_meta", {}),
            },
        }
        self._normalized_validator.validate(normalized)
        return normalized

    def _normalize_comments(
        self,
        comments: list[Mapping[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        normalized: list[dict[str, Any]] = []
        originals: list[dict[str, str]] = []
        seen_ids: set[str] = set()

        for comment in comments:
            comment_id = str(comment["id"])
            originals.append(
                {
                    "id": comment_id,
                    "body": str(comment["body"]),
                }
            )
            if comment_id in seen_ids:
                continue

            seen_ids.add(comment_id)
            normalized.append(
                {
                    "id": comment_id,
                    "body": self._clean_text(str(comment["body"])),
                    "author": self._optional_string(comment.get("author")),
                    "score": int(comment.get("score", 0) or 0),
                    "created_at": self._date_timestamp(str(comment["created_at"])),
                    "parent_id": self._optional_string(comment.get("parent_id")),
                    "depth": int(comment.get("depth", 0) or 0),
                }
            )

        return normalized, originals

    def _clean_text(self, text: str) -> str:
        chunks: list[str] = []
        for token in self._markdown.parse(text):
            if token.type == "inline":
                chunks.append("".join(self._inline_chunks(token.children or [])))
            elif token.type in {"fence", "code_block"}:
                chunks.append(token.content)
        return self._normalize_whitespace(" ".join(chunks))

    @staticmethod
    def _inline_chunks(tokens: list[Token]) -> list[str]:
        chunks: list[str] = []
        for token in tokens:
            if token.type in {"text", "code_inline", "html_inline"}:
                chunks.append(token.content)
            elif token.type in {"softbreak", "hardbreak"}:
                chunks.append(" ")
            elif token.type == "image":
                chunks.append(token.content)
        return chunks

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _date_timestamp(value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat()

    @staticmethod
    def _optional_string(value: Any | None) -> str | None:
        return None if value is None else str(value)

    @staticmethod
    def _load_schema(path: Path) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _default_schema_directory() -> Path:
        repository_schemas = Path(__file__).resolve().parents[3] / "schemas"
        if repository_schemas.is_dir():
            return repository_schemas
        return Path(__file__).resolve().parents[1] / "schemas" / "contracts"
