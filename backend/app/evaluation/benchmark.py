"""Run golden datasets across multiple extraction models."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter

from backend.app.evaluation.benchmark_models import BenchmarkModel
from backend.app.evaluation.dataset import GoldenCase, GoldenDataset
from backend.app.evaluation.runner import (
    CaseEvaluation,
    EvaluationResult,
    EvaluationRunner,
    FieldMetrics,
)
from backend.app.extractor import ExtractionEngine, ExtractionSettings
from backend.app.extractor.usage import TokenUsage


ExtractorFactory = Callable[
    [ExtractionSettings, list[TokenUsage]],
    EvaluationRunner,
]


@dataclass(frozen=True, slots=True)
class ModelBenchmarkResult:
    """Evaluation and usage metrics for one benchmark model."""

    profile: BenchmarkModel
    evaluation: EvaluationResult
    token_usage: TokenUsage

    @property
    def name(self) -> str:
        return self.profile.name


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """Aggregate output from one multi-model benchmark run."""

    models: tuple[ModelBenchmarkResult, ...]

    @property
    def model_count(self) -> int:
        return len(self.models)


class BenchmarkRunner:
    """Execute one golden dataset against multiple model profiles."""

    def __init__(
        self,
        *,
        defaults: ExtractionSettings,
        extractor_factory: ExtractorFactory | None = None,
    ) -> None:
        self._defaults = defaults
        self._extractor_factory = extractor_factory or self._default_extractor_factory

    def run(
        self,
        dataset: GoldenDataset,
        models: tuple[BenchmarkModel, ...],
    ) -> BenchmarkResult:
        if not models:
            raise ValueError("benchmark requires at least one model profile")

        results = [self._run_model(dataset, profile) for profile in models]
        return BenchmarkResult(tuple(results))

    def _run_model(
        self,
        dataset: GoldenDataset,
        profile: BenchmarkModel,
    ) -> ModelBenchmarkResult:
        usage_records: list[TokenUsage] = []
        settings = profile.to_extraction_settings(self._defaults)
        runner = self._extractor_factory(settings, usage_records)
        started_at = perf_counter()
        evaluation = runner.run(dataset)
        _ = perf_counter() - started_at
        token_usage = sum(usage_records, start=TokenUsage())
        return ModelBenchmarkResult(
            profile=profile,
            evaluation=evaluation,
            token_usage=token_usage,
        )

    @staticmethod
    def _default_extractor_factory(
        settings: ExtractionSettings,
        usage_records: list[TokenUsage],
    ) -> EvaluationRunner:
        engine = ExtractionEngine(settings, usage_records=usage_records)
        return MeteredEvaluationRunner(engine)


class MeteredEvaluationRunner(EvaluationRunner):
    """Evaluation runner that records per-case extraction latency."""

    def _evaluate_case(
        self,
        case: GoldenCase,
        fields: dict[str, FieldMetrics],
    ) -> CaseEvaluation:
        started_at = perf_counter()
        result = super()._evaluate_case(case, fields)
        latency = perf_counter() - started_at
        return CaseEvaluation(
            case_id=result.case_id,
            json_valid=result.json_valid,
            missing_values=result.missing_values,
            hallucinated_values=result.hallucinated_values,
            latency_seconds=latency,
            retry_count=result.retry_count,
            error=result.error,
        )
