"""JSON logging with request and trace correlation."""

import json
import logging
from datetime import UTC, datetime

from opentelemetry import trace

from backend.app.observability.context import get_request_id

_EXTRA_FIELDS = (
    "event",
    "http_method",
    "http_route",
    "http_status_code",
    "duration_seconds",
    "error_type",
    "pipeline_stage",
    "validation_gate",
    "component",
    "retry_reason",
)


class JsonFormatter(logging.Formatter):
    """Serialize stable log fields as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = get_request_id()
        if request_id is not None:
            payload["request_id"] = request_id

        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            payload["trace_id"] = format(span_context.trace_id, "032x")
            payload["span_id"] = format(span_context.span_id, "016x")

        for field in _EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        if record.exc_info is not None:
            exception_type = record.exc_info[0]
            if exception_type is not None:
                payload["exception_type"] = exception_type.__name__
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
