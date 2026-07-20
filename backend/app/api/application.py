"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from backend.app.api.dependencies import ApiContainer, build_container
from backend.app.api.middleware import ObservabilityMiddleware
from backend.app.api.routes import router
from backend.app.api.services import ComplaintNotFoundError, ProcessingRunNotFoundError

logger = logging.getLogger(__name__)


def create_app(container: ApiContainer | None = None) -> FastAPI:
    """Create an isolated API application with explicit dependencies."""

    resolved_container = container if container is not None else build_container()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        resolved_container.telemetry.shutdown()

    app = FastAPI(title="SignalMine", version="0.1.0", lifespan=lifespan)
    app.state.container = resolved_container
    app.include_router(router)
    app.add_middleware(
        ObservabilityMiddleware,
        telemetry=resolved_container.telemetry,
        request_id_header=resolved_container.telemetry.settings.request_id_header,
    )

    @app.exception_handler(ComplaintNotFoundError)
    async def complaint_not_found(
        request: Request,
        error: ComplaintNotFoundError,
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": f"complaint {error} not found"},
        )

    @app.exception_handler(ProcessingRunNotFoundError)
    async def processing_run_not_found(
        request: Request,
        error: ProcessingRunNotFoundError,
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": f"processing run {error} not found"},
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_unavailable(
        request: Request,
        error: SQLAlchemyError,
    ) -> JSONResponse:
        del request
        logger.error(
            "database unavailable",
            extra={
                "event": "database_unavailable",
                "error_type": type(error).__name__,
            },
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "database unavailable"},
        )

    resolved_container.telemetry.instrument_app(app)
    return app
