"""Unit tests for the versioned extraction prompt registry."""

from pathlib import Path

import pytest

from backend.app.extractor.prompt_registry import PromptRegistry, PromptRegistryError

PROMPTS_DIRECTORY = Path(__file__).resolve().parents[1] / "prompts"


def test_prompt_registry_lists_registered_versions() -> None:
    registry = PromptRegistry(PROMPTS_DIRECTORY)

    assert registry.list_versions() == ("extract_v1", "extract_v2")


def test_prompt_registry_loads_extract_v1() -> None:
    prompt = PromptRegistry(PROMPTS_DIRECTORY).get("extract_v1")

    assert prompt.version == "extract_v1"
    assert "span-level provenance" in prompt.system_prompt


def test_prompt_registry_loads_extract_v2() -> None:
    prompt = PromptRegistry(PROMPTS_DIRECTORY).get("extract_v2")

    assert prompt.version == "extract_v2"
    assert "incident response" in prompt.system_prompt.lower()


def test_prompt_registry_rejects_unknown_version() -> None:
    with pytest.raises(PromptRegistryError, match="unknown prompt version"):
        PromptRegistry(PROMPTS_DIRECTORY).get("extract_v99")
