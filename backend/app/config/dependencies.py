"""Explicit dependency container owned by a future composition root."""

from dataclasses import dataclass

from backend.app.config.settings import Settings


@dataclass(frozen=True, slots=True)
class ApplicationDependencies:
    """Runtime dependencies passed into entry points instead of global singletons."""

    settings: Settings
