"""Application services used by HTTP routes."""

from typing import Protocol
from uuid import UUID

from backend.app.api.schemas import (
    ComplaintResponse,
    HealthResponse,
    MetricsResponse,
)
from backend.app.schemas import Complaint
from backend.app.storage import StageCounts


class ComplaintNotFoundError(LookupError):
    """Raised when a requested persisted complaint does not exist."""


class Pipeline(Protocol):
    """Pipeline behavior required by processing."""

    def process_url(self, url: str) -> Complaint: ...


class ComplaintStore(Protocol):
    """Persistence behavior required by API services."""

    def save_complaint(
        self,
        complaint: Complaint,
        normalized_post_id: UUID,
    ) -> UUID: ...

    def get_complaint(self, complaint_id: UUID) -> Complaint | None: ...

    def count_stages(self) -> StageCounts: ...

    def check_health(self) -> None: ...


class ProcessingService:
    """Process and identify one persisted complaint."""

    def __init__(self, pipeline: Pipeline, store: ComplaintStore) -> None:
        self._pipeline = pipeline
        self._store = store

    def process(self, url: str) -> ComplaintResponse:
        """Run the pipeline and return the idempotent extraction identifier."""

        complaint = self._pipeline.process_url(url)
        complaint_id = self._store.save_complaint(
            complaint,
            complaint.meta.document_id,
        )
        return ComplaintResponse(id=complaint_id, complaint=complaint)


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

    def __init__(self, store: ComplaintStore) -> None:
        self._store = store

    def get(self) -> MetricsResponse:
        """Return current raw, normalized, and complaint counts."""

        counts = self._store.count_stages()
        return MetricsResponse(
            raw_posts=counts.raw_posts,
            normalized_posts=counts.normalized_posts,
            complaints=counts.complaints,
        )
