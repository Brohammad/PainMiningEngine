"""Golden-dataset evaluation and Markdown reporting."""

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
)

__all__ = [
    "CaseEvaluation",
    "EvaluationResult",
    "EvaluationRunner",
    "FieldMetrics",
    "GoldenCase",
    "GoldenDataset",
    "GoldenDatasetError",
    "MarkdownReport",
]
