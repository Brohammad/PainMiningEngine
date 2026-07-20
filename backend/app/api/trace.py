"""Convert pipeline trace models into API response schemas."""

from backend.app.api.schemas import PipelineTraceResponse, StageTraceResponse
from backend.app.pipeline.trace import PipelineTrace, StageTrace, StageStatus


def to_trace_response(trace: PipelineTrace) -> PipelineTraceResponse:
    """Serialize one pipeline trace for HTTP responses."""

    return PipelineTraceResponse(
        started_at=trace.started_at,
        ended_at=trace.ended_at,
        duration_seconds=trace.duration_seconds,
        status=trace.status.value,
        stages=[_to_stage_response(stage) for stage in trace.stages],
        error=trace.error,
    )


def _to_stage_response(stage: StageTrace) -> StageTraceResponse:
    return StageTraceResponse(
        stage=stage.stage,
        started_at=stage.started_at,
        ended_at=stage.ended_at,
        duration_seconds=stage.duration_seconds,
        status=stage.status.value,
        error=stage.error,
        operation=stage.operation,
    )
