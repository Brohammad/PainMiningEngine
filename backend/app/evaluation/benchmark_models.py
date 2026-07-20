"""Benchmark model definitions loaded from JSON configuration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pydantic import SecretStr

from backend.app.extractor.settings import ExtractionSettings


class BenchmarkConfigError(ValueError):
    """Raised when a benchmark model configuration is invalid."""


@dataclass(frozen=True, slots=True)
class BenchmarkModel:
    """One model profile executed during a benchmark run."""

    name: str
    model: str
    provider: str
    base_url: str | None = None
    api_key_env: str | None = None
    temperature: float | None = None
    prompt_version: str | None = None

    def to_extraction_settings(self, defaults: ExtractionSettings) -> ExtractionSettings:
        """Build extraction settings for this benchmark profile."""

        updates: dict[str, Any] = {
            "model": self.model,
            "provider": self.provider,
            "api_key": self._resolve_api_key(defaults),
        }
        if self.base_url is not None:
            updates["base_url"] = self.base_url
        if self.temperature is not None:
            updates["temperature"] = self.temperature
        if self.prompt_version is not None:
            updates["prompt_version"] = self.prompt_version
        return defaults.model_copy(update=updates)

    def _resolve_api_key(self, defaults: ExtractionSettings) -> SecretStr:
        if self.api_key_env is None:
            return defaults.api_key
        value = os.environ.get(self.api_key_env)
        if not value:
            raise BenchmarkConfigError(
                f"missing API key environment variable: {self.api_key_env}"
            )
        return SecretStr(value)


def load_benchmark_models(path: Path) -> tuple[BenchmarkModel, ...]:
    """Load benchmark model profiles from a JSON array file."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkConfigError(f"unable to read {path}") from exc

    if not isinstance(payload, list) or not payload:
        raise BenchmarkConfigError(f"{path} must contain a non-empty JSON array")

    models: list[BenchmarkModel] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise BenchmarkConfigError(f"model entry {index} must be an object")
        models.append(_parse_model(item, index))
    return tuple(models)


def default_benchmark_models() -> tuple[BenchmarkModel, ...]:
    """Return the repository default multi-provider benchmark set."""

    return (
        BenchmarkModel(name="GPT-4.1-mini", model="gpt-4.1-mini", provider="openai"),
        BenchmarkModel(name="GPT-5-mini", model="gpt-5-mini", provider="openai"),
        BenchmarkModel(
            name="Claude",
            model="claude-sonnet-4-20250514",
            provider="anthropic",
            base_url="https://api.anthropic.com/v1",
            api_key_env="ANTHROPIC_API_KEY",
        ),
        BenchmarkModel(
            name="Gemini",
            model="gemini-2.0-flash",
            provider="google",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            api_key_env="GEMINI_API_KEY",
        ),
    )


def _parse_model(item: dict[str, Any], index: int) -> BenchmarkModel:
    try:
        name = str(item["name"]).strip()
        model = str(item["model"]).strip()
        provider = str(item["provider"]).strip()
    except KeyError as exc:
        raise BenchmarkConfigError(
            f"model entry {index} is missing required field: {exc.args[0]}"
        ) from exc

    if not name or not model or not provider:
        raise BenchmarkConfigError(f"model entry {index} has empty required fields")

    base_url = item.get("base_url")
    api_key_env = item.get("api_key_env")
    temperature = item.get("temperature")
    prompt_version = item.get("prompt_version")

    if base_url is not None and not isinstance(base_url, str):
        raise BenchmarkConfigError(f"model entry {index} base_url must be a string")
    if api_key_env is not None and not isinstance(api_key_env, str):
        raise BenchmarkConfigError(
            f"model entry {index} api_key_env must be a string"
        )
    if temperature is not None and not isinstance(temperature, (int, float)):
        raise BenchmarkConfigError(
            f"model entry {index} temperature must be a number"
        )
    if prompt_version is not None and not isinstance(prompt_version, str):
        raise BenchmarkConfigError(
            f"model entry {index} prompt_version must be a string"
        )

    return BenchmarkModel(
        name=name,
        model=model,
        provider=provider,
        base_url=base_url,
        api_key_env=cast(str | None, api_key_env),
        temperature=float(temperature) if temperature is not None else None,
        prompt_version=cast(str | None, prompt_version),
    )
