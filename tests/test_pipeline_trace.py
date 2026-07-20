"""Pipeline stage tracing tests."""

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
from backend.app.observability import NoOpTelemetry, ObservabilitySettings, Telemetry
from backend.app.pipeline import PipelineTracer, SynchronousPipeline, StageStatus
from backend.app.validator import ComplaintValidationError, ComplaintValidator
from tests.test_persistence import make_raw_capture
from tests.test_synchronous_pipeline import (
    FakeCollector,
    FakeExtractor,
    FakeNormalizer,
    FakeValidator,
    make_complaint,
    make_normalized,
)


class FakeStorage:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def find_duplicate(self, **_kwargs: object) -> None:
        return None

    def record_processing_run(self, **_kwargs: object) -> UUID:
        return UUID("44444444-4444-4444-8444-444444444444")

    def save_raw(self, post: dict[str, Any]) -> UUID:
        self.events.append("save_raw")
        return UUID("11111111-1111-4111-8111-111111111111")

    def save_normalized(
        self,
        post: dict[str, Any],
        raw_post_id: UUID,
    ) -> UUID:
        self.events.append("save_normalized")
        return UUID("22222222-2222-4222-8222-222222222222")

    def save_complaint(
        self,
        complaint: Complaint,
        normalized_post_id: UUID,
    ) -> UUID:
        self.events.append("save_complaint")
        return UUID("33333333-3333-4333-8333-333333333333")


def make_traced_pipeline(
    *,
    with_storage: bool = False,
    delegate: object | None = None,
) -> tuple[SynchronousPipeline, PipelineTracer, list[str]]:
    events: list[str] = []
    raw = make_raw_capture()
    normalized = make_normalized()
    complaint = make_complaint()
    collector = FakeCollector(raw, events)
    normalizer = FakeNormalizer(normalized, events)
    extractor = FakeExtractor(complaint, events)
    validator = FakeValidator(events)
    tracer = PipelineTracer(delegate or NoOpTelemetry())
    storage = FakeStorage(events) if with_storage else None
    pipeline = SynchronousPipeline(
        collector,
        normalizer,
        extractor,
        validator,
        storage=storage,
        telemetry=tracer,
    )
    return pipeline, tracer, events


def test_pipeline_tracer_records_stage_order_and_timing() -> None:
    pipeline, tracer, _events = make_traced_pipeline()

    pipeline.process_url("https://www.reddit.com/r/devops/comments/post1/")

    trace = tracer.trace
    assert trace.status is StageStatus.SUCCESS
    assert trace.error is None
    assert trace.duration_seconds >= 0
    assert trace.started_at.tzinfo == UTC
    assert [stage.stage for stage in trace.stages] == [
        "collector",
        "normalizer",
        "extractor",
        "validator",
    ]
    for stage in trace.stages:
        assert stage.status is StageStatus.SUCCESS
        assert stage.error is None
        assert stage.duration_seconds >= 0
        assert stage.ended_at >= stage.started_at


def test_pipeline_tracer_records_storage_stages() -> None:
    pipeline, tracer, _events = make_traced_pipeline(with_storage=True)

    pipeline.process_url("https://www.reddit.com/r/devops/comments/post1/")

    storage_stages = [stage for stage in tracer.trace.stages if stage.stage == "storage"]
    assert [stage.operation for stage in storage_stages] == [
        "persist_raw",
        "persist_normalized",
        "persist_complaint",
    ]


def test_pipeline_tracer_records_failure_and_still_delegates_metrics() -> None:
    events: list[str] = []
    raw = make_raw_capture()
    normalized = make_normalized()
    complaint = make_complaint(evidence_end=100)
    collector = FakeCollector(raw, events)
    normalizer = FakeNormalizer(normalized, events)
    extractor = FakeExtractor(complaint, events)
    telemetry = Telemetry(ObservabilitySettings(service_name="trace-tests"))
    tracer = PipelineTracer(telemetry)
    pipeline = SynchronousPipeline(
        collector,
        normalizer,
        extractor,
        ComplaintValidator(telemetry=telemetry),
        telemetry=tracer,
    )

    with pytest.raises(ComplaintValidationError):
        pipeline.process_url("https://www.reddit.com/r/devops/comments/post1/")

    trace = tracer.trace
    assert trace.status is StageStatus.FAILURE
    assert trace.error is not None
    assert trace.stages[-1].stage == "validator"
    assert trace.stages[-1].status is StageStatus.FAILURE
    assert trace.stages[-1].error is not None
    metrics = telemetry.render_prometheus().decode()
    assert 'signalmine_pipeline_runs_total{outcome="error"} 1.0' in metrics
    assert (
        'signalmine_pipeline_stage_duration_seconds_count'
        '{outcome="error",stage="validate"} 1.0' in metrics
    )


def test_to_trace_response_serializes_pipeline_trace() -> None:
    from backend.app.api.trace import to_trace_response
    from backend.app.pipeline.trace import PipelineTrace, StageTrace

    started = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
    ended = datetime(2026, 7, 20, 12, 0, 1, tzinfo=UTC)
    trace = PipelineTrace(
        started_at=started,
        ended_at=ended,
        duration_seconds=1.0,
        status=StageStatus.SUCCESS,
        stages=(
            StageTrace(
                stage="collector",
                started_at=started,
                ended_at=ended,
                duration_seconds=0.5,
                status=StageStatus.SUCCESS,
            ),
        ),
    )

    response = to_trace_response(trace)

    assert response.status == "success"
    assert response.stages[0].stage == "collector"
    assert response.stages[0].duration_seconds == 0.5
