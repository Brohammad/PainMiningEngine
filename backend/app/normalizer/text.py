"""Shared normalizer helpers."""

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.token import Token


def clean_text(text: str, markdown: MarkdownIt) -> str:
    chunks: list[str] = []
    for token in markdown.parse(text):
        if token.type == "inline":
            chunks.append("".join(_inline_chunks(token.children or [])))
        elif token.type in {"fence", "code_block"}:
            chunks.append(token.content)
    return normalize_whitespace(" ".join(chunks))


def normalize_comments(
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
                "body": str(comment["body"]),
                "author": optional_string(comment.get("author")),
                "score": int(comment.get("score", 0) or 0),
                "created_at": date_timestamp(str(comment["created_at"])),
                "parent_id": optional_string(comment.get("parent_id")),
                "depth": int(comment.get("depth", 0) or 0),
            }
        )

    return normalized, originals


def date_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def optional_string(value: Any | None) -> str | None:
    return None if value is None else str(value)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


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
