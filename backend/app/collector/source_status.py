"""Runtime availability of configured discussion sources."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pydantic import ValidationError

from backend.app.collector.github_settings import GitHubSettings
from backend.app.collector.settings import RedditSettings
from backend.app.collector.sources import DiscussionSource


class SourceAvailability(str, Enum):
    """How ready a source is for collection."""

    READY = "ready"
    NOT_CONFIGURED = "not_configured"
    PLANNED = "planned"


@dataclass(frozen=True, slots=True)
class SourceStatus:
    """One source and its runtime availability."""

    source: DiscussionSource
    availability: SourceAvailability
    detail: str | None = None


def reddit_configured() -> bool:
    """Return whether Reddit API credentials are present."""

    try:
        RedditSettings()
    except ValidationError:
        return False
    return True


def github_token_configured() -> bool:
    """Return whether a GitHub token is configured."""

    settings = GitHubSettings()
    token = settings.token
    if token is None:
        return False
    return bool(token.get_secret_value().strip())


def list_source_statuses() -> tuple[SourceStatus, ...]:
    """Return configured and planned sources in display order."""

    github_detail = None
    if not github_token_configured():
        github_detail = "set GITHUB_TOKEN to avoid rate limits"

    reddit_availability = (
        SourceAvailability.READY
        if reddit_configured()
        else SourceAvailability.NOT_CONFIGURED
    )
    reddit_detail = (
        None if reddit_availability is SourceAvailability.READY else "not configured"
    )

    return (
        SourceStatus(DiscussionSource.GITHUB, SourceAvailability.READY, github_detail),
        SourceStatus(DiscussionSource.FILE, SourceAvailability.READY),
        SourceStatus(DiscussionSource.REDDIT, reddit_availability, reddit_detail),
        SourceStatus(DiscussionSource.HACKERNEWS, SourceAvailability.PLANNED, "planned"),
    )


def format_sources_report() -> str:
    """Render a human-readable source availability report."""

    lines = ["Available Sources", ""]
    for status in list_source_statuses():
        label = status.source.value.replace("_", " ").title()
        if status.source is DiscussionSource.GITHUB:
            label = "GitHub"
        elif status.source is DiscussionSource.HACKERNEWS:
            label = "Hacker News"

        if status.availability is SourceAvailability.READY:
            prefix = "✓"
        elif status.availability is SourceAvailability.NOT_CONFIGURED:
            prefix = "○"
        else:
            prefix = "○"

        suffix = ""
        if status.detail:
            suffix = f" ({status.detail})"
        lines.append(f"{prefix} {label}{suffix}")

    return "\n".join(lines)
