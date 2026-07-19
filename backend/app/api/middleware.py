"""HTTP correlation, structured access logs, and request metrics."""

import logging
import re
from time import perf_counter
from uuid import uuid4

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.app.observability import Telemetry
from backend.app.observability.context import (
    reset_request_id,
    set_request_id,
)

logger = logging.getLogger(__name__)
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class ObservabilityMiddleware:
    """Correlate, time, count, and log every HTTP request."""

    def __init__(
        self,
        app: ASGIApp,
        telemetry: Telemetry,
        request_id_header: str,
    ) -> None:
        self._app = app
        self._telemetry = telemetry
        self._header_name = request_id_header.lower().encode("ascii")

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = self._request_id(scope)
        token = set_request_id(request_id)
        started_at = perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((self._header_name, request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self._app(scope, receive, send_with_request_id)
        except Exception as error:
            logger.exception(
                "HTTP request failed",
                extra={
                    "event": "http_request_failed",
                    "http_method": scope["method"],
                    "error_type": type(error).__name__,
                },
            )
            response = JSONResponse(
                status_code=500,
                content={"detail": "internal server error"},
            )
            await response(scope, receive, send_with_request_id)
        finally:
            duration = perf_counter() - started_at
            route = getattr(scope.get("route"), "path", "unmatched")
            self._telemetry.record_http_request(
                scope["method"],
                route,
                status_code,
                duration,
            )
            logger.info(
                "HTTP request completed",
                extra={
                    "event": "http_request_completed",
                    "http_method": scope["method"],
                    "http_route": route,
                    "http_status_code": status_code,
                    "duration_seconds": duration,
                },
            )
            reset_request_id(token)

    def _request_id(self, scope: Scope) -> str:
        for name, value in scope["headers"]:
            if name == self._header_name:
                candidate = str(value.decode("ascii", errors="ignore"))
                if _SAFE_REQUEST_ID.fullmatch(candidate):
                    return candidate
                break
        return str(uuid4())
