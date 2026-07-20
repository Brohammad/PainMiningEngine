"""Serialize processing history for HTTP responses."""

from backend.app.api.schemas import ProcessingRunResponse
from backend.app.storage.models import ProcessingRun


def to_processing_run_response(run: ProcessingRun) -> ProcessingRunResponse:
    """Serialize one processing history row."""

    return ProcessingRunResponse(
        id=run.id,
        input_url=run.input_url,
        platform=run.platform,
        external_id=run.external_id,
        normalized_content_hash=run.normalized_content_hash,
        normalized_document_id=run.normalized_document_id,
        complaint_id=run.complaint_id,
        status=run.status,  # type: ignore[arg-type]
        duplicate_match=run.duplicate_match,  # type: ignore[arg-type]
        started_at=run.started_at,
        completed_at=run.completed_at,
    )
