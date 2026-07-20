"""Discover and resolve versioned extraction prompts from disk."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.app.extractor.prompt import ExtractionPrompt, PromptContractError


class PromptRegistryError(ValueError):
    """Raised when a prompt version cannot be resolved."""


@dataclass(frozen=True, slots=True)
class PromptRegistry:
    """Load extraction prompts from ``extract_*.md`` files without code changes."""

    directory: Path

    @classmethod
    def default(cls) -> PromptRegistry:
        return cls(cls._default_directory())

    def list_versions(self) -> tuple[str, ...]:
        """Return sorted prompt ids discovered in the registry directory."""

        return tuple(
            sorted(path.stem for path in self.directory.glob("extract_*.md"))
        )

    def get(self, version: str) -> ExtractionPrompt:
        """Load one registered prompt version."""

        path = self.directory / f"{version}.md"
        if not path.is_file():
            available = ", ".join(self.list_versions()) or "none"
            raise PromptRegistryError(
                f"unknown prompt version {version!r}; available: {available}"
            )
        try:
            prompt = ExtractionPrompt.load(path)
        except PromptContractError as exc:
            raise PromptRegistryError(
                f"invalid prompt contract for {version!r}: {exc}"
            ) from exc
        if prompt.version != version:
            raise PromptRegistryError(
                f"prompt file {path.name} declares {prompt.version!r}, "
                f"expected {version!r}"
            )
        return prompt

    @staticmethod
    def _default_directory() -> Path:
        repository_prompts = Path(__file__).resolve().parents[3] / "prompts"
        if repository_prompts.is_dir():
            return repository_prompts
        return Path(__file__).resolve().parent / "prompt_contracts"
