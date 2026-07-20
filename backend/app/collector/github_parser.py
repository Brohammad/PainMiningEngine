"""GitHub issue URL parsing."""

from __future__ import annotations

import re

from backend.app.collector.exceptions import GitHubParseError

GITHUB_ISSUE_URL_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<number>\d+)",
    re.IGNORECASE,
)


def parse_github_issue_url(url: str) -> tuple[str, str, int]:
    """Return (owner, repo, issue_number) for a GitHub issue URL."""

    match = GITHUB_ISSUE_URL_RE.match(url.strip())
    if match is None:
        raise GitHubParseError(f"unsupported GitHub issue URL: {url}")
    return match.group("owner"), match.group("repo"), int(match.group("number"))


def canonicalize_github_issue_url(owner: str, repo: str, number: int) -> str:
    """Normalize a GitHub issue URL for duplicate lookups."""

    return f"https://github.com/{owner}/{repo}/issues/{number}"


def discussion_id_for_issue(owner: str, repo: str, number: int) -> str:
    """Return the stable discussion id for one GitHub issue."""

    return f"{owner}/{repo}#issue-{number}"
