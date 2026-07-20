"""Multi-model benchmark runner and Markdown report tests."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from backend.app.evaluation import (
    BenchmarkConfigError,
    BenchmarkReport,
    BenchmarkRunner,
    EvaluationRunner,
    GoldenDataset,
    default_benchmark_models,
    load_benchmark_models,
)
from backend.app.evaluation.benchmark_models import BenchmarkModel
from backend.app.extractor import ExtractionSettings
from backend.app.extractor.usage import TokenUsage, extract_token_usage
from tests.test_evaluation import (
    SequenceExtractor,
    build_dataset,
    make_complaint,
)


class UsageExtractor:
    """Return predetermined outputs and record token usage per call."""

    def __init__(
        self,
        outputs: list[object],
        usage_records: list[TokenUsage],
        *,
        prompt_tokens: int = 10,
        completion_tokens: int = 5,
    ) -> None:
        self._outputs: Iterator[object] = iter(outputs)
        self._usage_records = usage_records
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens

    def extract(self, normalized: dict[str, Any]) -> object:
        output = next(self._outputs)
        if isinstance(output, Exception):
            raise output
        self._usage_records.append(
            TokenUsage(
                prompt_tokens=self._prompt_tokens,
                completion_tokens=self._completion_tokens,
                total_tokens=self._prompt_tokens + self._completion_tokens,
            )
        )
        return output


def test_extract_token_usage_reads_object_attributes() -> None:
    class Usage:
        prompt_tokens = 12
        completion_tokens = 7
        total_tokens = 19

    class Response:
        usage = Usage()

    usage = extract_token_usage(Response())
    assert usage == TokenUsage(12, 7, 19)


def test_extract_token_usage_reads_dict_payload() -> None:
    usage = extract_token_usage(
        {"usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}
    )
    assert usage == TokenUsage(3, 2, 5)


def test_extract_token_usage_returns_none_when_missing() -> None:
    assert extract_token_usage(object()) is None


def test_default_benchmark_models_lists_four_providers() -> None:
    models = default_benchmark_models()
    assert [model.name for model in models] == [
        "GPT-4.1-mini",
        "GPT-5-mini",
        "Claude",
        "Gemini",
    ]
    assert models[2].api_key_env == "ANTHROPIC_API_KEY"
    assert models[3].api_key_env == "GEMINI_API_KEY"


def test_load_benchmark_models_reads_json_file(tmp_path: Path) -> None:
    config_path = tmp_path / "models.json"
    config_path.write_text(
        json.dumps(
            [
                {
                    "name": "Test model",
                    "model": "test-model",
                    "provider": "openai",
                    "temperature": 0.1,
                    "prompt_version": "extract_v2",
                }
            ]
        ),
        encoding="utf-8",
    )

    models = load_benchmark_models(config_path)

    assert len(models) == 1
    assert models[0].name == "Test model"
    assert models[0].temperature == pytest.approx(0.1)
    assert models[0].prompt_version == "extract_v2"


def test_load_benchmark_models_rejects_invalid_payload(tmp_path: Path) -> None:
    config_path = tmp_path / "models.json"
    config_path.write_text("{}", encoding="utf-8")

    with pytest.raises(BenchmarkConfigError, match="non-empty JSON array"):
        load_benchmark_models(config_path)


def test_benchmark_model_resolves_api_key_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_BENCH_KEY", "secret-key")
    defaults = ExtractionSettings(
        api_key="default-key",
        model="gpt-4.1-mini",
    )
    profile = BenchmarkModel(
        name="Claude",
        model="claude-sonnet-4-20250514",
        provider="anthropic",
        api_key_env="TEST_BENCH_KEY",
    )

    settings = profile.to_extraction_settings(defaults)

    assert settings.api_key.get_secret_value() == "secret-key"
    assert settings.model == "claude-sonnet-4-20250514"


def test_benchmark_model_requires_configured_api_key_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISSING_BENCH_KEY", raising=False)
    defaults = ExtractionSettings(
        api_key="default-key",
        model="gpt-4.1-mini",
    )
    profile = BenchmarkModel(
        name="Claude",
        model="claude-sonnet-4-20250514",
        provider="anthropic",
        api_key_env="MISSING_BENCH_KEY",
    )

    with pytest.raises(BenchmarkConfigError, match="MISSING_BENCH_KEY"):
        profile.to_extraction_settings(defaults)


def test_benchmark_runner_compares_models(tmp_path: Path) -> None:
    dataset, normalized, gold = build_dataset(tmp_path)
    defaults = ExtractionSettings(
        api_key="test-key",
        model="gpt-4.1-mini",
    )
    models = (
        BenchmarkModel(name="Model A", model="model-a", provider="openai"),
        BenchmarkModel(name="Model B", model="model-b", provider="openai"),
    )

    def extractor_factory(
        settings: ExtractionSettings,
        usage_records: list[TokenUsage],
    ) -> EvaluationRunner:
        outputs = [
            make_complaint(gold[0], normalized[0]),
            make_complaint(gold[1], normalized[1]),
            make_complaint(gold[2], normalized[2]),
        ]
        return EvaluationRunner(
            UsageExtractor(
                outputs,
                usage_records,
                prompt_tokens=20 if settings.model == "model-a" else 5,
                completion_tokens=10 if settings.model == "model-a" else 2,
            )
        )

    result = BenchmarkRunner(
        defaults=defaults,
        extractor_factory=extractor_factory,
    ).run(dataset, models)

    assert result.model_count == 2
    assert result.models[0].name == "Model A"
    assert result.models[0].evaluation.field_accuracy == 1.0
    assert result.models[0].token_usage.total_tokens == 90
    assert result.models[1].token_usage.total_tokens == 21


def test_benchmark_runner_requires_at_least_one_model(tmp_path: Path) -> None:
    dataset = GoldenDataset.load(Path("tests/golden"))
    defaults = ExtractionSettings(
        api_key="test-key",
        model="gpt-4.1-mini",
    )

    with pytest.raises(ValueError, match="at least one model"):
        BenchmarkRunner(defaults=defaults).run(dataset, ())


def test_benchmark_report_renders_comparison_table(tmp_path: Path) -> None:
    dataset, normalized, gold = build_dataset(tmp_path)
    defaults = ExtractionSettings(
        api_key="test-key",
        model="gpt-4.1-mini",
    )
    models = (BenchmarkModel(name="Model A", model="model-a", provider="openai"),)

    def extractor_factory(
        _settings: ExtractionSettings,
        usage_records: list[TokenUsage],
    ) -> EvaluationRunner:
        outputs = [
            make_complaint(gold[0], normalized[0]),
            make_complaint(gold[1], normalized[1]),
            make_complaint(gold[2], normalized[2]),
        ]
        return EvaluationRunner(UsageExtractor(outputs, usage_records))

    result = BenchmarkRunner(
        defaults=defaults,
        extractor_factory=extractor_factory,
    ).run(dataset, models)
    report_path = tmp_path / "benchmark.md"

    BenchmarkReport.write(result, report_path)
    report = report_path.read_text(encoding="utf-8")

    assert "# SignalMine Benchmark Report" in report
    assert "## Model comparison" in report
    assert "| Model | Provider | Latency (avg) | Tokens (total) |" in report
    assert "| Model A | `openai` |" in report
    assert "100.00%" in report
    assert "### Model A" in report
    assert "Token usage:" in report
