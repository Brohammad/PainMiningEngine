"""Source-agnostic collector interface."""

from typing import Protocol

from backend.app.collector.types import RawDiscussion


class SourceCollector(Protocol):
    """Collect one online discussion from any supported source."""

    def fetch(self, target: str) -> RawDiscussion:
        """Fetch one discussion by URL, file path, or source-specific locator."""
