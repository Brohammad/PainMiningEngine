"""Local JSON file collection mapped to RawDiscussion."""

import json
from pathlib import Path
from typing import Any, cast

from backend.app.collector.discussion import (
    DiscussionSchemaValidator,
    coerce_to_discussion,
)
from backend.app.collector.exceptions import (
    FileCollectorError,
    FileCollectorInvalidJsonError,
    FileCollectorNotFoundError,
    FileCollectorSchemaError,
)
from backend.app.collector.types import RawDiscussion


class FileCollector:
    """Read RawDiscussion captures from local JSON files without mutating them."""

    def __init__(self, schema_directory: Path | None = None) -> None:
        self._discussion_validator = DiscussionSchemaValidator(schema_directory)

    def fetch(self, target: str) -> RawDiscussion:
        """Read and validate one discussion JSON file from disk."""

        if not target.strip():
            raise ValueError("target must not be empty")

        path = Path(target)
        if not path.is_file():
            raise FileCollectorNotFoundError(f"file not found: {path}")

        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise FileCollectorError(f"unable to read file: {path}") from exc

        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise FileCollectorInvalidJsonError(
                f"invalid JSON in {path}: {exc.msg} at line {exc.lineno} "
                f"column {exc.colno}"
            ) from exc

        if not isinstance(payload, dict):
            raise FileCollectorInvalidJsonError(
                f"JSON root must be an object, got {type(payload).__name__}"
            )

        try:
            discussion = coerce_to_discussion(cast(dict[str, Any], payload))
        except ValueError as exc:
            raise FileCollectorInvalidJsonError(str(exc)) from exc

        self._validate(discussion, path)
        return discussion

    def fetch_post(self, target: str) -> RawDiscussion:
        """Backward-compatible alias for :meth:`fetch`."""

        return self.fetch(target)

    def _validate(self, discussion: RawDiscussion, path: Path) -> None:
        try:
            self._discussion_validator.validate(discussion, context=str(path))
        except ValueError as exc:
            raise FileCollectorSchemaError(str(exc)) from exc
