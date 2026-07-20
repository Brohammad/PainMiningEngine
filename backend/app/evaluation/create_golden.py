"""Create golden evaluation fixtures for manual annotation."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from jsonschema.protocols import Validator

from backend.app.collector.discussion import (
    coerce_to_discussion,
    is_legacy_reddit_capture,
    is_raw_discussion,
)
from backend.app.collector.types import RawDiscussion
from backend.app.schemas import ComplaintCandidate


class GoldenCreateError(ValueError):
    """Raised when a golden fixture cannot be created."""


def blank_expected_extraction() -> dict[str, Any]:
    """Return a schema-shaped extraction template with empty field values."""

    template: dict[str, Any] = {
        "pain_summary": {"value": None, "evidence": []},
        "workflow": {"value": None, "evidence": []},
        "workaround": {"value": None, "evidence": []},
        "buyer": {"value": None, "evidence": []},
        "budget_owner": {"value": "unknown", "evidence": []},
        "time_cost": {"value": None, "evidence": []},
        "industry": {"value": None, "evidence": []},
        "existing_tools": [],
    }
    ComplaintCandidate.model_validate(template)
    return template


def build_metadata(
    raw: dict[str, Any],
    *,
    case_id: str,
    created_at: datetime,
) -> dict[str, Any]:
    """Return annotation metadata derived from one RawDiscussion capture."""

    discussion = _coerce_discussion(raw)
    metadata = cast(dict[str, Any], discussion.get("metadata", {}))
    timestamp = created_at.astimezone(UTC).isoformat()
    return {
        "case_id": case_id,
        "created_at": timestamp,
        "annotation_status": "pending",
        "input_schema": "raw_discussion",
        "source": {
            "platform": str(discussion["source"]),
            "external_id": str(discussion["discussion_id"]),
            "permalink": str(discussion["url"]),
            "subreddit": metadata.get("subreddit"),
        },
        "post": {
            "id": str(discussion["discussion_id"]).removeprefix("t3_"),
            "title": str(discussion["title"]),
            "author": discussion.get("author"),
            "score": metadata.get("score"),
            "created_at": discussion.get("created_at"),
        },
    }


def derive_case_id(raw: dict[str, Any], output_dir: Path) -> str:
    """Return a filesystem-safe case id for the golden fixture directory."""

    if output_dir.name:
        return _sanitize_case_id(output_dir.name)

    discussion = _coerce_discussion(raw)
    post_id = str(discussion["discussion_id"]).removeprefix("t3_")
    return _sanitize_case_id(post_id)


def create_golden_case(
    raw: dict[str, Any],
    output_dir: Path,
    *,
    created_at: datetime | None = None,
    schema_directory: Path | None = None,
) -> Path:
    """Write ``input.json``, ``expected.json``, and ``metadata.json``."""

    discussion = _validate_discussion(raw, schema_directory)
    case_id = derive_case_id(raw, output_dir)
    timestamp = created_at or datetime.now(UTC)
    if output_dir.exists():
        if output_dir.is_file():
            raise GoldenCreateError(f"output path is not a directory: {output_dir}")
        if any(output_dir.iterdir()):
            raise GoldenCreateError(f"output directory is not empty: {output_dir}")
    else:
        output_dir.mkdir(parents=True)

    _write_json(output_dir / "input.json", discussion)
    _write_json(output_dir / "expected.json", blank_expected_extraction())
    _write_json(
        output_dir / "metadata.json",
        build_metadata(discussion, case_id=case_id, created_at=timestamp),
    )
    return output_dir


def _coerce_discussion(raw: dict[str, Any]) -> RawDiscussion:
    if is_raw_discussion(raw):
        return cast(RawDiscussion, raw)
    if is_legacy_reddit_capture(raw):
        return coerce_to_discussion(raw)
    raise GoldenCreateError("input must be a RawDiscussion JSON object")


def _validate_discussion(
    raw: dict[str, Any],
    schema_directory: Path | None,
) -> RawDiscussion:
    discussion = _coerce_discussion(raw)
    schema_path = schema_directory or _default_schema_directory()
    validator: Validator = Draft202012Validator(
        _load_schema(schema_path / "raw_discussion.json"),
        format_checker=FormatChecker(),
    )
    try:
        validator.validate(discussion)
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "<root>"
        raise GoldenCreateError(
            f"input failed RawDiscussion schema validation at {location}: {exc.message}"
        ) from exc
    return discussion


def _sanitize_case_id(value: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-")
    if not sanitized:
        raise GoldenCreateError("case id must not be empty")
    return sanitized


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        f"{json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )


def _load_schema(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _default_schema_directory() -> Path:
    repository_schemas = Path(__file__).resolve().parents[3] / "schemas"
    if repository_schemas.is_dir():
        return repository_schemas
    return Path(__file__).resolve().parents[1] / "schemas" / "contracts"
