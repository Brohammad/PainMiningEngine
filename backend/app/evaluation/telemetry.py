"""Telemetry capture for golden evaluation runs."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter


class EvaluationTelemetry:
    """Record per-case pipeline latency and retry counts."""

    def __init__(self) -> None:
        self.retry_count = 0
        self._run_started_at: float | None = None
        self.latency_seconds = 0.0

    @contextmanager
    def pipeline_run(self) -> Iterator[None]:
        started_at = perf_counter()
        try:
            yield
        finally:
            self.latency_seconds = perf_counter() - started_at

    @contextmanager
    def pipeline_stage(self, stage: str) -> Iterator[None]:
        del stage
        yield

    def observe_extraction_latency(
        self,
        started_at: float,
        outcome: str,
    ) -> None:
        del started_at, outcome

    def record_validation_failure(self, gate: str) -> None:
        del gate

    def record_retry(
        self,
        component: str,
        reason: str,
        delay_seconds: float = 0.0,
    ) -> None:
        del component, reason, delay_seconds
        self.retry_count += 1
