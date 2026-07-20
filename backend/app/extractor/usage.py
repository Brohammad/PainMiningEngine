"""Token usage captured from provider extraction responses."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Provider token accounting for one extraction request."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


def extract_token_usage(response: object) -> TokenUsage | None:
    """Read token usage metadata when the provider exposes it."""

    raw_response = getattr(response, "_raw_response", response)
    usage = getattr(raw_response, "usage", None)
    if usage is None and isinstance(raw_response, dict):
        usage = raw_response.get("usage")
    if usage is None:
        return None

    if isinstance(usage, dict):
        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        total_tokens = int(usage.get("total_tokens", 0) or 0)
    else:
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or 0)

    if total_tokens == 0 and prompt_tokens == 0 and completion_tokens == 0:
        return None
    if total_tokens == 0:
        total_tokens = prompt_tokens + completion_tokens
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )
