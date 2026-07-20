"""Application services used by HTTP routes."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from backend.app.api.schemas import (
    ComplaintResponse,
    HealthResponse,
    ProcessResponse,
    ProcessingRunResponse,
)
from backend.app.api.processing_history import to_processing_run_response
from backend.app.api.trace import to_trace_response
from backend.app.observability import Telemetry
from backend.app.pipeline.result import PipelineResult
from backend.app.pipeline.trace import PipelineTracer
from backend.app.schemas import Complaint
from backend.app.storage import StageCounts


class ComplaintNotFoundError(LookupError):
    """Raised when a requested persisted complaint does not exist."""


class ProcessingRunNotFoundError(LookupError):
    """Raised when a requested processing history record does not exist."""


@dataclass(frozen=True, slots=True)
class PrometheusMetrics:
    """Rendered Prometheus response owned by the transport adapter."""

    body: bytes
    content_type: str


class Pipeline(Protocol):
    """Pipeline behavior required by processing."""

    def process_url(self, url: str) -> PipelineResult: ...


class ComplaintStore(Protocol):
    """Persistence behavior required by API services."""

    def save_complaint(
        self,
        complaint: Complaint,
        normalized_post_id: UUID,
    ) -> UUID: ...

    def get_complaint(self, complaint_id: UUID) -> Complaint | None: ...

    def get_processing_run(self, run_id: UUID) -> object | None: ...

    def count_stages(self) -> StageCounts: ...

    def check_health(self) -> None: ...


class ProcessingService:
    """Process and identify one persisted complaint."""

    def __init__(
        self,
        pipeline: Pipeline,
        store: ComplaintStore,
        tracer: PipelineTracer,
    ) -> None:
        self._pipeline = pipeline
        self._store = store
        self._tracer = tracer

    def process(self, url: str) -> ProcessResponse:
        """Run the pipeline and return the idempotent extraction identifier."""

        result = self._pipeline.process_url(url)
        complaint_id = result.complaint_id or self._store.save_complaint(
            result.complaint,
            result.complaint.meta.document_id,
        )
        return ProcessResponse(
            id=complaint_id,
            complaint=result.complaint,
            trace=to_trace_response(self._tracer.trace),
            duplicate=result.duplicate,
            duplicate_match=result.duplicate_match,
            processing_run_id=result.processing_run_id,
            status=result.status,
        )


class ComplaintQueryService:
    """Read persisted complaints."""

    def __init__(self, store: ComplaintStore) -> None:
        self._store = store

    def get(self, complaint_id: UUID) -> ComplaintResponse:
        """Return one complaint or raise a transport-independent miss."""

        complaint = self._store.get_complaint(complaint_id)
        if complaint is None:
            raise ComplaintNotFoundError(str(complaint_id))
        return ComplaintResponse(id=complaint_id, complaint=complaint)


class ProcessingHistoryService:
    """Read persisted processing history."""

    def __init__(self, store: ComplaintStore) -> None:
        self._store = store

    def get(self, run_id: UUID) -> ProcessingRunResponse:
        """Return one processing run or raise a transport-independent miss."""

        from backend.app.storage.models import ProcessingRun

        run = self._store.get_processing_run(run_id)
        if run is None or not isinstance(run, ProcessingRun):
            raise ProcessingRunNotFoundError(str(run_id))
        return to_processing_run_response(run)


class HealthService:
    """Check required infrastructure."""

    def __init__(self, store: ComplaintStore) -> None:
        self._store = store

    def get(self) -> HealthResponse:
        """Return healthy only after a successful database query."""

        self._store.check_health()
        return HealthResponse(status="ok")


class MetricsService:
    """Expose persisted stage counts."""

    def __init__(self, store: ComplaintStore, telemetry: Telemetry) -> None:
        self._store = store
        self._telemetry = telemetry

    def get(self) -> PrometheusMetrics:
        """Refresh stage gauges and render Prometheus exposition."""

        counts = self._store.count_stages()
        self._telemetry.update_stage_counts(counts)
        return PrometheusMetrics(
            body=self._telemetry.render_prometheus(),
            content_type=self._telemetry.prometheus_content_type,
        )
