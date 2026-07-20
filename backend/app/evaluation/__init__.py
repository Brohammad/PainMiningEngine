"""Golden-dataset evaluation and Markdown reporting."""

from backend.app.evaluation.benchmark import (
    BenchmarkResult,
    BenchmarkRunner,
    ModelBenchmarkResult,
)
from backend.app.evaluation.benchmark_models import (
    BenchmarkConfigError,
    BenchmarkModel,
    default_benchmark_models,
    load_benchmark_models,
)
from backend.app.evaluation.benchmark_report import BenchmarkReport
from backend.app.evaluation.create_golden import (
    GoldenCreateError,
    blank_expected_extraction,
    create_golden_case,
)
from backend.app.evaluation.dataset import (
    GoldenCase,
    GoldenDataset,
    GoldenDatasetError,
)
from backend.app.evaluation.report import MarkdownReport
from backend.app.evaluation.runner import (
    CaseEvaluation,
    EvaluationResult,
    EvaluationRunner,
    FieldMetrics,
    PipelineEvaluationRunner,
)

__all__ = [
    "BenchmarkConfigError",
    "BenchmarkModel",
    "BenchmarkReport",
    "BenchmarkResult",
    "BenchmarkRunner",
    "CaseEvaluation",
    "EvaluationResult",
    "EvaluationRunner",
    "FieldMetrics",
    "GoldenCase",
    "GoldenCreateError",
    "GoldenDataset",
    "GoldenDatasetError",
    "MarkdownReport",
    "ModelBenchmarkResult",
    "PipelineEvaluationRunner",
    "blank_expected_extraction",
    "create_golden_case",
    "default_benchmark_models",
    "load_benchmark_models",
]
