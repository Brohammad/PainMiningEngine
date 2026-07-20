"""Shared collector type aliases."""

from typing import Any

RawDiscussion = dict[str, Any]

# Deprecated alias retained for Reddit adapter internals during migration.
LegacyRedditCapture = dict[str, Any]
