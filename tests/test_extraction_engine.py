"""Unit tests for Instructor-backed complaint extraction."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from backend.app.extractor import (
    ComplaintCandidate,
    EvidenceField,
    EvidenceSource,
    ExtractionEngine,
    ExtractionSettings,
    ExtractionValidationError,
    Provenance,
    TextField,
    ToolMention,
    TriStateField,
)
from backend.app.extractor.engine import InstructorClient
from backend.app.observability import (
    ObservabilitySettings,
    Telemetry,
    TelemetryRecorder,
)

ROOT = Path(__file__).parents[1]
PROMPT_PATH = ROOT / "prompts" / "extract_v1.md"
EXTRACTION_SCHEMA = json.loads(
    (ROOT / "schemas" / "extraction.json").read_text(encoding="utf-8")
)
EXTRACTION_VALIDATOR = Draft202012Validator(
    EXTRACTION_SCHEMA,
    format_checker=FormatChecker(),
)
FIXED_TIME = datetime(2026, 7, 19, 12, 30, tzinfo=UTC)


class FakeCompletions:
    """Deterministic Instructor completions test double."""

    def __init__(self, responses: list[object]) -> None:
        self._responses: Iterator[object] = iter(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


class FakeChat:
    def __init__(self, completions: FakeCompletions) -> None:
        self.completions = completions


class FakeInstructorClient:
    def __init__(self, responses: list[object]) -> None:
        self.completions = FakeCompletions(responses)
        self.chat = FakeChat(self.completions)


def make_settings(**overrides: Any) -> ExtractionSettings:
    values: dict[str, Any] = {
        "api_key": "test-key",
        "model": "compatible-model",
        "base_url": "https://models.example.test/v1",
        "validation_retries": 2,
    }
    values.update(overrides)
    return ExtractionSettings(**values)


def make_normalized() -> dict[str, Any]:
    return {
        "id": "bb58d485-5c9e-5aff-aed7-5fdc86b4a77a",
        "platform": "reddit",
        "external_id": "t3_post1",
        "url": "https://www.reddit.com/r/devops/comments/post1/",
        "title": "Certificate rotation is painful",
        "content": (
            "Manual certificate rotation with certbot takes three hours weekly."
        ),
        "comments": [
            {
                "id": "comment1",
                "body": "We run the same process every Friday.",
                "author": None,
                "score": 8,
                "created_at": "2024-07-19T09:06:40+00:00",
                "parent_id": "t3_post1",
                "depth": 0,
            }
        ],
        "author": "operator",
        "score": 42,
        "created_at": "2024-07-19T09:00:00+00:00",
        "fetched_at": "2024-07-19T10:00:00+00:00",
        "community": "devops",
        "metadata": {},
    }


def make_candidate(*, range_end: int | None = None) -> ComplaintCandidate:
    normalized = make_normalized()
    body = cast(str, normalized["content"])
    evidence = Provenance(
        source=EvidenceSource.REDDIT,
        field=EvidenceField.BODY,
        comment_id=None,
        character_range=[0, range_end or len(body)],
        confidence=0.96,
    )
    tool_start = body.index("certbot")
    tool_evidence = Provenance(
        source=EvidenceSource.REDDIT,
        field=EvidenceField.BODY,
        comment_id=None,
        character_range=[tool_start, tool_start + len("certbot")],
        confidence=0.99,
    )
    empty = TextField(value=None, evidence=[])
    return ComplaintCandidate(
        pain_summary=TextField(
            value="Manual certificate rotation consumes three hours weekly.",
            evidence=[evidence],
        ),
        workflow=empty,
        workaround=empty,
        buyer=empty,
        budget_owner=TriStateField(value="unknown", evidence=[]),
        time_cost=TextField(
            value="Three hours weekly.",
            evidence=[evidence],
        ),
        industry=empty,
        existing_tools=[
            ToolMention(name="certbot", evidence=[tool_evidence]),
        ],
    )


def make_engine(
    client: FakeInstructorClient,
    *,
    settings: ExtractionSettings | None = None,
    telemetry: TelemetryRecorder | None = None,
) -> ExtractionEngine:
    return ExtractionEngine(
        settings or make_settings(),
        client=cast(InstructorClient, client),
        clock=lambda: FIXED_TIME,
        telemetry=telemetry,
    )


def test_extract_returns_pydantic_and_json_schema_valid_complaint() -> None:
    client = FakeInstructorClient([make_candidate()])
    engine = make_engine(client)

    complaint = engine.extract(make_normalized())
    payload = complaint.model_dump(mode="json")

    EXTRACTION_VALIDATOR.validate(payload)
    assert complaint.meta.model == "compatible-model"
    assert complaint.meta.prompt_version == "extract_v1"
    assert complaint.meta.source_id == "t3_post1"
    assert complaint.existing_tools[0].evidence[0].character_range == [33, 40]

    call = client.completions.calls[0]
    assert call["response_model"] is ComplaintCandidate
    assert call["max_retries"] == 0
    assert call["temperature"] == 0.0
    assert call["messages"][0]["content"] == PROMPT_PATH.read_text(encoding="utf-8")
    assert "Certificate rotation is painful" in call["messages"][1]["content"]
    assert "[comment id=comment1" in call["messages"][1]["content"]


def test_extract_retries_only_invalid_responses() -> None:
    valid = make_candidate()
    client = FakeInstructorClient([{"unexpected": "shape"}, valid])
    telemetry = Telemetry(ObservabilitySettings(service_name="extraction-tests"))
    engine = make_engine(
        client,
        settings=make_settings(validation_retries=1),
        telemetry=telemetry,
    )

    complaint = engine.extract(make_normalized())

    assert complaint.pain_summary.value is not None
    assert len(client.completions.calls) == 2
    assert (
        client.completions.calls[0]["messages"]
        == client.completions.calls[1]["messages"]
    )
    metrics = telemetry.render_prometheus().decode()
    assert (
        'signalmine_retries_total{component="extraction",'
        'reason="pydantic_response"} 1.0' in metrics
    )
    assert (
        'signalmine_extraction_latency_seconds_count{outcome="success"} 1.0' in metrics
    )
    assert (
        "signalmine_extraction_latency_seconds_count"
        '{outcome="validation_failure"} 1.0' in metrics
    )


def test_extract_does_not_retry_non_validation_failures() -> None:
    client = FakeInstructorClient([RuntimeError("provider unavailable")])
    engine = make_engine(
        client,
        settings=make_settings(validation_retries=3),
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        engine.extract(make_normalized())

    assert len(client.completions.calls) == 1


def test_extract_rejects_unresolvable_provenance() -> None:
    body = cast(str, make_normalized()["content"])
    client = FakeInstructorClient([make_candidate(range_end=len(body) + 1)])
    engine = make_engine(
        client,
        settings=make_settings(validation_retries=0),
    )

    with pytest.raises(ExtractionValidationError):
        engine.extract(make_normalized())

    assert len(client.completions.calls) == 1


def test_extraction_settings_support_openai_compatible_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXTRACTION_API_KEY", "environment-key")
    monkeypatch.setenv("EXTRACTION_MODEL", "custom/model")
    monkeypatch.setenv(
        "EXTRACTION_BASE_URL",
        "https://compatible.example.test/v1",
    )
    monkeypatch.setenv("EXTRACTION_INSTRUCTOR_MODE", "json")

    settings = ExtractionSettings(_env_file=None)

    assert settings.api_key.get_secret_value() == "environment-key"
    assert settings.model == "custom/model"
    assert settings.base_url == "https://compatible.example.test/v1"
    assert settings.instructor_mode == "json"
