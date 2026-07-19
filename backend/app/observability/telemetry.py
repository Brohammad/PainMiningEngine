"""Injected tracing and Prometheus metrics."""

import logging
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from time import perf_counter
from typing import Protocol

from fastapi import FastAPI
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from sqlalchemy import Engine

from backend.app.observability.settings import ObservabilitySettings

logger = logging.getLogger(__name__)


class StageCounts(Protocol):
    """Count values required to refresh persisted-stage gauges."""

    @property
    def raw_posts(self) -> int: ...

    @property
    def normalized_posts(self) -> int: ...

    @property
    def complaints(self) -> int: ...


class TelemetryRecorder(Protocol):
    """Domain-facing telemetry behavior."""

    def pipeline_run(self) -> AbstractContextManager[None]: ...

    def pipeline_stage(self, stage: str) -> AbstractContextManager[None]: ...

    def observe_extraction_latency(
        self,
        started_at: float,
        outcome: str,
    ) -> None: ...

    def record_validation_failure(self, gate: str) -> None: ...

    def record_retry(
        self,
        component: str,
        reason: str,
        delay_seconds: float = 0.0,
    ) -> None: ...


class Telemetry(TelemetryRecorder):
    """Application-owned tracing provider and Prometheus registry."""

    def __init__(self, settings: ObservabilitySettings) -> None:
        self.settings = settings
        self.registry = CollectorRegistry()
        self.tracer_provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": settings.service_name,
                    "service.version": settings.service_version,
                }
            ),
            sampler=ParentBased(TraceIdRatioBased(settings.trace_sample_ratio)),
        )
        if settings.otlp_traces_endpoint is not None:
            exporter = OTLPSpanExporter(endpoint=settings.otlp_traces_endpoint)
            self.tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
        self.tracer = self.tracer_provider.get_tracer(
            "backend.app",
            settings.service_version,
        )

        self._http_requests = Counter(
            "signalmine_http_requests",
            "HTTP requests handled.",
            ("method", "route", "status"),
            registry=self.registry,
        )
        self._http_duration = Histogram(
            "signalmine_http_request_duration_seconds",
            "HTTP request duration.",
            ("method", "route"),
            registry=self.registry,
        )
        self._pipeline_runs = Counter(
            "signalmine_pipeline_runs",
            "Pipeline runs by outcome.",
            ("outcome",),
            registry=self.registry,
        )
        self._pipeline_stage_duration = Histogram(
            "signalmine_pipeline_stage_duration_seconds",
            "Pipeline stage duration.",
            ("stage", "outcome"),
            registry=self.registry,
        )
        self._extraction_latency = Histogram(
            "signalmine_extraction_latency_seconds",
            "Extraction attempt latency.",
            ("outcome",),
            registry=self.registry,
        )
        self._validation_failures = Counter(
            "signalmine_validation_failures",
            "Validation failures by gate.",
            ("gate",),
            registry=self.registry,
        )
        self._retries = Counter(
            "signalmine_retries",
            "Retries by component and reason.",
            ("component", "reason"),
            registry=self.registry,
        )
        self._retry_delay = Histogram(
            "signalmine_retry_delay_seconds",
            "Requested retry delay.",
            ("component", "reason"),
            registry=self.registry,
        )
        self._stage_records = Gauge(
            "signalmine_stage_records",
            "Persisted records by pipeline stage.",
            ("stage",),
            registry=self.registry,
        )

    @contextmanager
    def pipeline_run(self) -> Iterator[None]:
        """Trace and count a complete pipeline invocation."""

        outcome = "success"
        with self.tracer.start_as_current_span("pipeline.run"):
            try:
                yield
            except BaseException:
                outcome = "error"
                raise
            finally:
                self._pipeline_runs.labels(outcome=outcome).inc()

    @contextmanager
    def pipeline_stage(self, stage: str) -> Iterator[None]:
        """Trace and time one bounded pipeline stage."""

        started_at = perf_counter()
        outcome = "success"
        with self.tracer.start_as_current_span(
            f"pipeline.{stage}",
            attributes={"signalmine.pipeline.stage": stage},
        ):
            try:
                yield
            except BaseException as error:
                outcome = "error"
                logger.exception(
                    "pipeline stage failed",
                    extra={
                        "event": "pipeline_stage_failed",
                        "pipeline_stage": stage,
                        "error_type": type(error).__name__,
                    },
                )
                raise
            finally:
                self._pipeline_stage_duration.labels(
                    stage=stage,
                    outcome=outcome,
                ).observe(perf_counter() - started_at)

    def observe_extraction_latency(
        self,
        started_at: float,
        outcome: str,
    ) -> None:
        """Record one extraction attempt."""

        self._extraction_latency.labels(outcome=outcome).observe(
            perf_counter() - started_at
        )

    def record_validation_failure(self, gate: str) -> None:
        """Count and log one bounded validation failure."""

        self._validation_failures.labels(gate=gate).inc()
        logger.warning(
            "validation failed",
            extra={"event": "validation_failed", "validation_gate": gate},
        )

    def record_retry(
        self,
        component: str,
        reason: str,
        delay_seconds: float = 0.0,
    ) -> None:
        """Count a retry and its requested delay."""

        self._retries.labels(component=component, reason=reason).inc()
        self._retry_delay.labels(component=component, reason=reason).observe(
            delay_seconds
        )
        logger.warning(
            "operation retry scheduled",
            extra={
                "event": "retry_scheduled",
                "component": component,
                "retry_reason": reason,
                "duration_seconds": delay_seconds,
            },
        )

    def record_http_request(
        self,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        """Record one completed HTTP request."""

        self._http_requests.labels(
            method=method,
            route=route,
            status=str(status_code),
        ).inc()
        self._http_duration.labels(method=method, route=route).observe(duration_seconds)

    def update_stage_counts(self, counts: StageCounts) -> None:
        """Refresh persisted stage gauges before a scrape."""

        self._stage_records.labels(stage="raw").set(counts.raw_posts)
        self._stage_records.labels(stage="normalized").set(counts.normalized_posts)
        self._stage_records.labels(stage="complaint").set(counts.complaints)

    def render_prometheus(self) -> bytes:
        """Render this application registry in Prometheus format."""

        return generate_latest(self.registry)

    def instrument_app(self, app: FastAPI) -> None:
        """Install OpenTelemetry HTTP tracing on one application."""

        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=self.tracer_provider,
        )

    def instrument_engine(self, engine: Engine) -> None:
        """Install OpenTelemetry SQLAlchemy tracing on one engine."""

        SQLAlchemyInstrumentor().instrument(
            engine=engine,
            tracer_provider=self.tracer_provider,
        )

    def shutdown(self) -> None:
        """Flush and shut down trace processors."""

        self.tracer_provider.shutdown()

    @property
    def prometheus_content_type(self) -> str:
        """Return the canonical Prometheus exposition content type."""

        return CONTENT_TYPE_LATEST


class NoOpTelemetry(TelemetryRecorder):
    """Zero-overhead default for domain components outside a runtime."""

    @contextmanager
    def pipeline_run(self) -> Iterator[None]:
        yield

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
