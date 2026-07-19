"""FastAPI application factory."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from backend.app.api.dependencies import ApiContainer, build_container
from backend.app.api.routes import router
from backend.app.api.services import ComplaintNotFoundError


def create_app(container: ApiContainer | None = None) -> FastAPI:
    """Create an isolated API application with explicit dependencies."""

    app = FastAPI(title="SignalMine", version="0.1.0")
    app.state.container = container if container is not None else build_container()
    app.include_router(router)

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

    @app.exception_handler(SQLAlchemyError)
    async def database_unavailable(
        request: Request,
        error: SQLAlchemyError,
    ) -> JSONResponse:
        del request, error
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "database unavailable"},
        )

    return app
