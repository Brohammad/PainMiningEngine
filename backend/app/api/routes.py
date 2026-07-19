"""Thin REST route adapters."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from backend.app.api.dependencies import (
    get_complaint_service,
    get_health_service,
    get_metrics_service,
    get_processing_service,
)
from backend.app.api.schemas import (
    ComplaintResponse,
    HealthResponse,
    MetricsResponse,
    ProcessRequest,
)
from backend.app.api.services import (
    ComplaintQueryService,
    HealthService,
    MetricsService,
    ProcessingService,
)

router = APIRouter()


@router.post("/process", response_model=ComplaintResponse)
def process(
    payload: ProcessRequest,
    service: Annotated[ProcessingService, Depends(get_processing_service)],
) -> ComplaintResponse:
    """Process and persist one Reddit post."""

    return service.process(str(payload.url))


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


@router.get("/metrics", response_model=MetricsResponse)
def get_metrics(
    service: Annotated[MetricsService, Depends(get_metrics_service)],
) -> MetricsResponse:
    """Return persisted stage counts."""

    return service.get()
