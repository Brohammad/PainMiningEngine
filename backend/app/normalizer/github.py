"""Deterministic GitHub RawDiscussion-to-NormalizedDocument conversion."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.protocols import Validator
from markdown_it import MarkdownIt

from backend.app.collector.types import RawDiscussion
from backend.app.normalizer.reddit import NormalizedPost
from backend.app.normalizer.text import (
    clean_text,
    date_timestamp,
    normalize_comments,
    optional_string,
)


class GitHubNormalizer:
    """Normalize GitHub RawDiscussion captures without inference or side effects."""

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

        comments, original_comments = normalize_comments(raw_comments)
        for index, comment in enumerate(comments):
            comment["body"] = clean_text(comment["body"], self._markdown)

        platform = str(discussion["source"])
        external_id = str(discussion["discussion_id"])
        reactions = cast(dict[str, Any], metadata.get("reactions", {}))

        normalized: NormalizedPost = {
            "id": str(uuid5(NAMESPACE_URL, f"{platform}:{external_id}")),
            "platform": platform,
            "external_id": external_id,
            "url": str(discussion["url"]),
            "title": clean_text(str(discussion["title"]), self._markdown),
            "content": clean_text(str(discussion["body"]), self._markdown),
            "comments": comments,
            "author": optional_string(discussion.get("author")),
            "score": int(reactions.get("total_count", 0) or 0),
            "created_at": date_timestamp(str(discussion["created_at"])),
            "fetched_at": date_timestamp(str(discussion["fetched_at"])),
            "community": optional_string(metadata.get("repository")),
            "metadata": {
                "original_text": {
                    "title": str(discussion["title"]),
                    "content": str(discussion["body"]),
                    "comments": original_comments,
                },
                "source_issue": {
                    "repository": metadata.get("repository"),
                    "issue_number": metadata.get("issue_number"),
                    "state": metadata.get("state"),
                    "labels": metadata.get("labels", []),
                    "assignees": metadata.get("assignees", []),
                },
                "fetch_meta": metadata.get("fetch_meta", {}),
            },
        }
        self._normalized_validator.validate(normalized)
        return normalized

    @staticmethod
    def _load_schema(path: Path) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _default_schema_directory() -> Path:
        repository_schemas = Path(__file__).resolve().parents[3] / "schemas"
        if repository_schemas.is_dir():
            return repository_schemas
        return Path(__file__).resolve().parents[1] / "schemas" / "contracts"
