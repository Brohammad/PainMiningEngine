"""API composition root and FastAPI dependency providers."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar, cast

from fastapi import Request

from backend.app.api.services import (
    ComplaintQueryService,
    HealthService,
    MetricsService,
    ProcessingHistoryService,
    ProcessingService,
)
from backend.app.collector import GitHubSettings, RedditSettings, build_url_collector
from backend.app.collector.source_status import reddit_configured
from backend.app.config import (
    DatabaseSettings,
    Settings,
    configure_logging,
    create_database_engine,
    create_session_factory,
)
from backend.app.extractor import ExtractionEngine, ExtractionSettings
from backend.app.normalizer import DispatchingNormalizer
from backend.app.observability import ObservabilitySettings, Telemetry
from backend.app.pipeline import PipelineTracer, SynchronousPipeline
from backend.app.source_identity import (
    CompositeIdentityResolver,
    GitHubDiscussionIdentityResolver,
    RedditDiscussionIdentityResolver,
)
from backend.app.storage import SQLAlchemyStageStore
from backend.app.validator import ComplaintValidator

SettingsT = TypeVar("SettingsT")


@dataclass(frozen=True, slots=True)
class ApiContainer:
    """Explicit dependencies owned by one FastAPI application."""

    processing: ProcessingService
    complaints: ComplaintQueryService
    processing_history: ProcessingHistoryService
    health: HealthService
    metrics: MetricsService
    telemetry: Telemetry


def build_container() -> ApiContainer:
    """Build production dependencies from environment-backed settings."""

    configure_logging(_environment_settings(Settings))
    telemetry = Telemetry(_environment_settings(ObservabilitySettings))
    tracer = PipelineTracer(telemetry)
    database_settings = _environment_settings(DatabaseSettings)
    engine = create_database_engine(database_settings)
    telemetry.instrument_engine(engine)
    store = SQLAlchemyStageStore(create_session_factory(engine))
    reddit_settings = (
        _environment_settings(RedditSettings) if reddit_configured() else None
    )
    pipeline = SynchronousPipeline(
        collector=build_url_collector(
            reddit_settings=reddit_settings,
            github_settings=_environment_settings(GitHubSettings),
            telemetry=telemetry,
        ),
        normalizer=DispatchingNormalizer(),
        extractor=ExtractionEngine(
            _environment_settings(ExtractionSettings),
            telemetry=telemetry,
        ),
        validator=ComplaintValidator(telemetry=telemetry),
        storage=store,
        telemetry=tracer,
        identity_resolver=CompositeIdentityResolver(
            [
                GitHubDiscussionIdentityResolver(),
                RedditDiscussionIdentityResolver(),
            ]
        ),
    )
    return ApiContainer(
        processing=ProcessingService(pipeline, store, tracer),
        complaints=ComplaintQueryService(store),
        processing_history=ProcessingHistoryService(store),
        health=HealthService(store),
        metrics=MetricsService(store, telemetry),
        telemetry=telemetry,
    )


def _environment_settings(settings_type: type[SettingsT]) -> SettingsT:
    factory = cast(Callable[[], SettingsT], settings_type)
    return factory()


def get_container(request: Request) -> ApiContainer:
    """Read dependencies from the current application instance."""

    return cast(ApiContainer, request.app.state.container)


def get_processing_service(request: Request) -> ProcessingService:
    """Provide processing behavior to a route."""

    return get_container(request).processing


def get_complaint_service(request: Request) -> ComplaintQueryService:
    """Provide complaint reads to a route."""

    return get_container(request).complaints


def get_processing_history_service(request: Request) -> ProcessingHistoryService:
    """Provide processing history reads to a route."""

    return get_container(request).processing_history


def get_health_service(request: Request) -> HealthService:
    """Provide health checks to a route."""

    return get_container(request).health


def get_metrics_service(request: Request) -> MetricsService:
    """Provide operational metrics to a route."""

    return get_container(request).metrics
