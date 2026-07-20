"""Unit tests for the local JSON file collector."""

import json
from pathlib import Path
from typing import Any

import pytest

from backend.app.collector import (
    FileCollector,
    FileCollectorError,
    FileCollectorInvalidJsonError,
    FileCollectorNotFoundError,
    FileCollectorSchemaError,
)
from backend.app.collector.discussion import (
    DiscussionSchemaValidator,
    _default_schema_directory,
    coerce_to_discussion,
)
from backend.app.normalizer import RedditNormalizer

SCHEMA_DIRECTORY = Path(__file__).resolve().parents[1] / "schemas"


def make_valid_capture() -> dict[str, Any]:
    return {
        "fetched_at": "2024-07-19T15:30:00+05:30",
        "source": {
            "platform": "reddit",
            "external_id": "t3_post1",
            "permalink": "https://www.reddit.com/r/devops/comments/post1/",
            "subreddit": "devops",
            "api": "file",
        },
        "post": {
            "id": "post1",
            "name": "t3_post1",
            "title": "Certificate rotation is painful",
            "selftext": "Manual certificate rotation takes hours.",
            "author": "operator",
            "score": 42,
            "upvote_ratio": 0.95,
            "num_comments": 1,
            "created_utc": 1_721_379_600.0,
            "url": "https://example.com/source-link",
            "permalink": "/r/devops/comments/post1/",
            "subreddit": "devops",
            "link_flair_text": "Discussion",
            "over_18": False,
            "is_self": True,
        },
        "comments": [
            {
                "id": "comment1",
                "name": "t1_comment1",
                "body": "Try certbot weekly.",
                "author": "commenter",
                "score": 4,
                "created_utc": 1_721_380_000.0,
                "parent_id": "t3_post1",
                "depth": 0,
                "permalink": "/r/devops/comments/post1/thread/comment1/",
            }
        ],
        "fetch_meta": {
            "comment_limit": 20,
            "comment_sort": "top",
        },
    }


def write_capture(path: Path, payload: dict[str, Any] | list[Any] | str) -> None:
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
        return
    path.write_text(json.dumps(payload), encoding="utf-8")


def make_collector(**kwargs: Any) -> FileCollector:
    return FileCollector(schema_directory=SCHEMA_DIRECTORY, **kwargs)


def test_fetch_post_returns_schema_valid_raw_discussion(tmp_path: Path) -> None:
    raw = make_valid_capture()
    file_path = tmp_path / "capture.json"
    write_capture(file_path, raw)

    capture = make_collector().fetch_post(str(file_path))

    assert capture == coerce_to_discussion(raw)


def test_fetch_post_runs_through_normalizer(tmp_path: Path) -> None:
    raw = make_valid_capture()
    file_path = tmp_path / "capture.json"
    write_capture(file_path, raw)

    capture = make_collector().fetch_post(str(file_path))
    normalized = RedditNormalizer(schema_directory=SCHEMA_DIRECTORY).normalize(
        capture
    )

    assert normalized["title"] == "Certificate rotation is painful"
    assert normalized["external_id"] == "t3_post1"


def test_fetch_post_does_not_modify_input_file(tmp_path: Path) -> None:
    raw = make_valid_capture()
    file_path = tmp_path / "capture.json"
    write_capture(file_path, raw)
    before = file_path.read_text(encoding="utf-8")
    mtime_before = file_path.stat().st_mtime_ns

    make_collector().fetch_post(str(file_path))

    after = file_path.read_text(encoding="utf-8")
    mtime_after = file_path.stat().st_mtime_ns
    assert before == after
    assert mtime_before == mtime_after


def test_fetch_post_rejects_empty_path() -> None:
    with pytest.raises(ValueError, match="target must not be empty"):
        make_collector().fetch_post("   ")


def test_fetch_post_rejects_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"

    with pytest.raises(FileCollectorNotFoundError, match="file not found"):
        make_collector().fetch_post(str(missing))


def test_fetch_post_rejects_directory_path(tmp_path: Path) -> None:
    with pytest.raises(FileCollectorNotFoundError, match="file not found"):
        make_collector().fetch_post(str(tmp_path))


def test_fetch_post_rejects_invalid_json(tmp_path: Path) -> None:
    file_path = tmp_path / "invalid.json"
    write_capture(file_path, "{not json")

    with pytest.raises(FileCollectorInvalidJsonError, match="invalid JSON"):
        make_collector().fetch_post(str(file_path))


def test_fetch_post_rejects_non_object_json_root(tmp_path: Path) -> None:
    file_path = tmp_path / "array.json"
    write_capture(file_path, [])

    with pytest.raises(
        FileCollectorInvalidJsonError,
        match="JSON root must be an object",
    ):
        make_collector().fetch_post(str(file_path))


def test_fetch_post_rejects_schema_violations_with_descriptive_error(
    tmp_path: Path,
) -> None:
    raw = coerce_to_discussion(make_valid_capture())
    raw["title"] = None
    file_path = tmp_path / "invalid-schema.json"
    write_capture(file_path, raw)

    with pytest.raises(FileCollectorSchemaError) as exc_info:
        make_collector().fetch_post(str(file_path))

    message = str(exc_info.value)
    assert "schema validation failed" in message
    assert "post" in message
    assert "title" in message
    assert str(file_path) in message


def test_fetch_post_rejects_invalid_fetched_at_type(tmp_path: Path) -> None:
    discussion = coerce_to_discussion(make_valid_capture())
    discussion = dict(discussion)
    discussion["fetched_at"] = 1_721_379_600
    file_path = tmp_path / "bad-timestamp.json"
    write_capture(file_path, discussion)

    with pytest.raises(FileCollectorSchemaError, match="fetched_at"):
        make_collector().fetch_post(str(file_path))


def test_fetch_post_wraps_read_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = make_collector()
    file_path = tmp_path / "capture.json"
    write_capture(file_path, make_valid_capture())
    original_read_text = Path.read_text

    def selective_read(self: Path, *args: object, **kwargs: object) -> str:
        if self == file_path:
            raise OSError("permission denied")
        return original_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", selective_read)

    with pytest.raises(FileCollectorError, match="unable to read file"):
        collector.fetch_post(str(file_path))


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


def test_format_validation_error_uses_root_when_path_is_empty() -> None:
    from jsonschema import ValidationError

    error = ValidationError("missing required property")
    location = ".".join(str(part) for part in error.absolute_path) or "<root>"
    message = f"schema validation failed for capture.json: {location}: {error.message}"

    assert message == (
        "schema validation failed for capture.json: <root>: missing required property"
    )
