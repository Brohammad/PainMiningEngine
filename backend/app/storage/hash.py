"""Content hashing for normalized documents and pipeline artifacts."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from backend.app.normalizer import NormalizedPost


def content_hash(payload: dict[str, Any]) -> str:
    """Return a stable SHA-256 hash for one JSON-serializable object."""

    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def normalized_content_hash(normalized: NormalizedPost) -> str:
    """Hash the normalized body used for duplicate detection."""

    comments = normalized.get("comments", [])
    payload = {
        "title": normalized["title"],
        "content": normalized["content"],
        "comments": comments,
    }
    return content_hash(payload)
