"""Structured per-stage traces for pipeline runs."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from time import perf_counter
from typing import Literal

from backend.app.observability import NoOpTelemetry, TelemetryRecorder

StageName = Literal["collector", "normalizer", "extractor", "validator", "storage"]

STAGE_LABELS: dict[str, StageName] = {
    "collect": "collector",
    "normalize": "normalizer",
    "extract": "extractor",
    "validate": "validator",
    "persist_raw": "storage",
    "persist_normalized": "storage",
    "persist_complaint": "storage",
}


class StageStatus(str, Enum):
    """Outcome for one pipeline stage or run."""

    SUCCESS = "success"
    FAILURE = "failure"


@dataclass(frozen=True, slots=True)
class StageTrace:
    """Timing and outcome for one bounded pipeline stage."""

    stage: StageName
    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    status: StageStatus
    error: str | None = None
    operation: str | None = None


@dataclass(frozen=True, slots=True)
class PipelineTrace:
    """Complete stage-by-stage record for one pipeline invocation."""

    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    status: StageStatus
    stages: tuple[StageTrace, ...]
    error: str | None = None


def empty_pipeline_trace() -> PipelineTrace:
    """Return an empty trace before the first pipeline run."""

    now = datetime.now(UTC)
    return PipelineTrace(
        started_at=now,
        ended_at=now,
        duration_seconds=0.0,
        status=StageStatus.SUCCESS,
        stages=(),
    )


class PipelineTracer(TelemetryRecorder):
    """Record structured stage traces while delegating to runtime telemetry."""

    def __init__(self, delegate: TelemetryRecorder | None = None) -> None:
        self._delegate = delegate or NoOpTelemetry()
        self._trace = empty_pipeline_trace()
        self._current_stages: list[StageTrace] = []

    @property
    def trace(self) -> PipelineTrace:
        """Return the trace from the most recent pipeline run."""

        return self._trace

    @contextmanager
    def pipeline_run(self) -> Iterator[None]:
        run_started_at = datetime.now(UTC)
        run_started = perf_counter()
        run_status = StageStatus.SUCCESS
        run_error: str | None = None
        self._current_stages = []

        with self._delegate.pipeline_run():
            try:
                yield
            except BaseException as error:
                run_status = StageStatus.FAILURE
                run_error = f"{type(error).__name__}: {error}"
                raise
            finally:
                run_ended = perf_counter()
                self._trace = PipelineTrace(
                    started_at=run_started_at,
                    ended_at=datetime.now(UTC),
                    duration_seconds=run_ended - run_started,
                    status=run_status,
                    stages=tuple(self._current_stages),
                    error=run_error,
                )

    @contextmanager
    def pipeline_stage(self, stage: str) -> Iterator[None]:
        label = STAGE_LABELS.get(stage, stage)
        operation = stage if label == "storage" else None
        started_at = datetime.now(UTC)
        started = perf_counter()
        status = StageStatus.SUCCESS
        error: str | None = None

        with self._delegate.pipeline_stage(stage):
            try:
                yield
            except BaseException as exc:
                status = StageStatus.FAILURE
                error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                ended = perf_counter()
                self._current_stages.append(
                    StageTrace(
                        stage=label,
                        started_at=started_at,
                        ended_at=datetime.now(UTC),
                        duration_seconds=ended - started,
                        status=status,
                        error=error,
                        operation=operation,
                    )
                )

    def observe_extraction_latency(
        self,
        started_at: float,
        outcome: str,
    ) -> None:
        self._delegate.observe_extraction_latency(started_at, outcome)

    def record_validation_failure(self, gate: str) -> None:
        self._delegate.record_validation_failure(gate)

    def record_retry(
        self,
        component: str,
        reason: str,
        delay_seconds: float = 0.0,
    ) -> None:
        self._delegate.record_retry(component, reason, delay_seconds)
