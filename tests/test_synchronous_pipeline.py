"""Unit tests for direct synchronous pipeline orchestration."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from backend.app.extractor import (
    Complaint,
    EvidenceField,
    EvidenceSource,
    ExtractionMeta,
    Provenance,
    TextField,
    TriStateField,
)
from backend.app.observability import ObservabilitySettings, Telemetry
from backend.app.pipeline import PipelineResult, SynchronousPipeline
from backend.app.validator import ComplaintValidationError, ComplaintValidator
from tests.test_persistence import make_raw_capture


def make_normalized() -> dict[str, Any]:
    return {
        "id": "bb58d485-5c9e-5aff-aed7-5fdc86b4a77a",
        "platform": "reddit",
        "external_id": "t3_post1",
        "url": "https://www.reddit.com/r/devops/comments/post1/",
        "title": "Certificate rotation is painful",
        "content": "Manual certificate rotation takes hours.",
        "comments": [],
        "author": "operator",
        "score": 42,
        "created_at": "2024-07-19T09:00:00+00:00",
        "fetched_at": "2024-07-19T10:00:00+00:00",
        "community": "devops",
        "metadata": {},
    }


def make_complaint(*, evidence_end: int | None = None) -> Complaint:
    empty = TextField(value=None, evidence=[])
    evidence = (
        []
        if evidence_end is None
        else [
            Provenance(
                source=EvidenceSource.REDDIT,
                field=EvidenceField.BODY,
                comment_id=None,
                character_range=[0, evidence_end],
                confidence=0.9,
            )
        ]
    )
    return Complaint(
        pain_summary=TextField(
            value=None if evidence_end is None else "Rotation takes hours.",
            evidence=evidence,
        ),
        workflow=empty,
        workaround=empty,
        buyer=empty,
        budget_owner=TriStateField(value="unknown", evidence=[]),
        time_cost=empty,
        industry=empty,
        existing_tools=[],
        meta=ExtractionMeta(
            model="test-model",
            prompt_version="extract_v1",
            provider="openai",
            temperature=0.0,
            source_id="t3_post1",
            document_id=UUID("bb58d485-5c9e-5aff-aed7-5fdc86b4a77a"),
            extracted_at=datetime(2026, 7, 19, 12, 30, tzinfo=UTC),
        ),
    )


class FakeCollector:
    def __init__(self, raw: dict[str, Any], events: list[str]) -> None:
        self.raw = raw
        self.events = events
        self.urls: list[str] = []

    def fetch(self, url: str) -> dict[str, Any]:
        self.events.append("collector")
        self.urls.append(url)
        return self.raw


class FakeNormalizer:
    def __init__(self, normalized: dict[str, Any], events: list[str]) -> None:
        self.normalized = normalized
        self.events = events
        self.inputs: list[dict[str, Any]] = []

    def normalize(self, raw: dict[str, Any]) -> dict[str, Any]:
        self.events.append("normalizer")
        self.inputs.append(raw)
        return self.normalized


class FakeExtractor:
    def __init__(self, complaint: Complaint, events: list[str]) -> None:
        self.complaint = complaint
        self.events = events
        self.inputs: list[dict[str, Any]] = []

    def extract(self, normalized: dict[str, Any]) -> Complaint:
        self.events.append("extractor")
        self.inputs.append(normalized)
        return self.complaint


class FakeValidator:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.inputs: list[tuple[Complaint, dict[str, Any]]] = []

    def validate(
        self,
        complaint: Complaint,
        normalized: dict[str, Any],
    ) -> Complaint:
        self.events.append("validator")
        self.inputs.append((complaint, normalized))
        return complaint


def make_pipeline() -> tuple[
    SynchronousPipeline,
    FakeCollector,
    FakeNormalizer,
    FakeExtractor,
    FakeValidator,
    list[str],
]:
    events: list[str] = []
    raw = make_raw_capture()
    normalized = make_normalized()
    complaint = make_complaint()
    collector = FakeCollector(raw, events)
    normalizer = FakeNormalizer(normalized, events)
    extractor = FakeExtractor(complaint, events)
    validator = FakeValidator(events)
    pipeline = SynchronousPipeline(
        collector,
        normalizer,
        extractor,
        validator,
    )
    return pipeline, collector, normalizer, extractor, validator, events


def test_process_url_runs_every_stage_in_order_and_returns_complaint() -> None:
    pipeline, collector, normalizer, extractor, validator, events = make_pipeline()
    url = "https://www.reddit.com/r/devops/comments/post1/"

    result = pipeline.process_url(url)

    assert result.complaint is extractor.complaint
    assert events == ["collector", "normalizer", "extractor", "validator"]
    assert collector.urls == [url]
    assert normalizer.inputs == [collector.raw]
    assert extractor.inputs == [normalizer.normalized]
    assert validator.inputs == [(extractor.complaint, normalizer.normalized)]


def test_process_post_skips_collection_and_returns_deterministic_result() -> None:
    pipeline, collector, _normalizer, extractor, _validator, events = make_pipeline()
    raw = make_raw_capture()
    raw = dict(raw)
    raw["body"] = "already collected body"

    first = pipeline.process_post(raw)
    second = pipeline.process_post(raw)

    assert first.complaint == second.complaint == extractor.complaint
    assert collector.urls == []
    assert events == [
        "normalizer",
        "extractor",
        "validator",
        "normalizer",
        "extractor",
        "validator",
    ]


def test_complaint_validator_returns_valid_complaint_unchanged() -> None:
    complaint = make_complaint()

    validated = ComplaintValidator().validate(complaint, make_normalized())

    assert validated is complaint


def test_complaint_validator_rejects_out_of_range_evidence() -> None:
    complaint = make_complaint(evidence_end=100)
    telemetry = Telemetry(ObservabilitySettings(service_name="validator-tests"))

    with pytest.raises(ComplaintValidationError):
        ComplaintValidator(telemetry=telemetry).validate(
            complaint,
            make_normalized(),
        )

    assert (
        'signalmine_validation_failures_total{gate="provenance"} 1.0'
        in telemetry.render_prometheus().decode()
    )


def test_pipeline_records_run_and_stage_timings() -> None:
    pipeline, collector, normalizer, extractor, validator, _events = make_pipeline()
    telemetry = Telemetry(ObservabilitySettings(service_name="pipeline-tests"))
    instrumented = SynchronousPipeline(
        collector,
        normalizer,
        extractor,
        validator,
        telemetry=telemetry,
    )

    instrumented.process_url("https://www.reddit.com/r/devops/comments/post1/")

    metrics = telemetry.render_prometheus().decode()
    assert 'signalmine_pipeline_runs_total{outcome="success"} 1.0' in metrics
    for stage in ("collect", "normalize", "extract", "validate"):
        assert (
            "signalmine_pipeline_stage_duration_seconds_count"
            f'{{outcome="success",stage="{stage}"}} 1.0' in metrics
        )
