"""Thin REST route adapters."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from backend.app.api.dependencies import (
    get_complaint_service,
    get_health_service,
    get_metrics_service,
    get_processing_service,
    get_processing_history_service,
)
from backend.app.api.schemas import (
    ComplaintResponse,
    HealthResponse,
    ProcessRequest,
    ProcessResponse,
    ProcessingRunResponse,
)
from backend.app.api.services import (
    ComplaintQueryService,
    HealthService,
    MetricsService,
    ProcessingHistoryService,
    ProcessingService,
)

router = APIRouter()


@router.post("/process", response_model=ProcessResponse)
def process(
    payload: ProcessRequest,
    service: Annotated[ProcessingService, Depends(get_processing_service)],
) -> ProcessResponse:
    """Process and persist one Reddit post."""

    return service.process(str(payload.url))


@router.get("/processing-runs/{run_id}", response_model=ProcessingRunResponse)
def get_processing_run(
    run_id: UUID,
    service: Annotated[
        ProcessingHistoryService,
        Depends(get_processing_history_service),
    ],
) -> ProcessingRunResponse:
    """Return one persisted processing history record."""

    return service.get(run_id)


@router.get("/complaints/{complaint_id}", response_model=ComplaintResponse)
def get_complaint(
    complaint_id: UUID,
    service: Annotated[
        ComplaintQueryService,
        Depends(get_complaint_service),
    ],
) -> ComplaintResponse:
    """Return one persisted complaint."""

    return service.get(complaint_id)


@router.get("/health", response_model=HealthResponse)
def get_health(
    service: Annotated[HealthService, Depends(get_health_service)],
) -> HealthResponse:
    """Report database-backed service health."""

    return service.get()


@router.get("/metrics", response_class=Response)
def get_metrics(
    service: Annotated[MetricsService, Depends(get_metrics_service)],
) -> Response:
    """Return Prometheus metrics."""

    metrics = service.get()
    return Response(
        content=metrics.body,
        headers={"Content-Type": metrics.content_type},
    )
