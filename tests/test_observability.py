"""Structured logging and trace-correlation tests."""

import json
import logging

from backend.app.observability import ObservabilitySettings, Telemetry
from backend.app.observability.context import reset_request_id, set_request_id
from backend.app.observability.logging import JsonFormatter


def test_json_logs_include_request_and_trace_correlation() -> None:
    telemetry = Telemetry(ObservabilitySettings(service_name="logging-tests"))
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="signalmine.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request completed",
        args=(),
        exc_info=None,
    )
    record.event = "test_event"
    token = set_request_id("request-123")

    try:
        with telemetry.tracer.start_as_current_span("test-span"):
            payload = json.loads(formatter.format(record))
    finally:
        reset_request_id(token)

    assert payload["message"] == "request completed"
    assert payload["event"] == "test_event"
    assert payload["request_id"] == "request-123"
    assert len(payload["trace_id"]) == 32
    assert len(payload["span_id"]) == 16
