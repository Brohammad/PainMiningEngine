"""Run extraction over golden cases and compute deterministic metrics."""

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from jsonschema.protocols import Validator
from pydantic import BaseModel

from backend.app.evaluation.dataset import GoldenCase, GoldenDataset
from backend.app.evaluation.telemetry import EvaluationTelemetry
from backend.app.extractor import ExtractionValidationError
from backend.app.normalizer import NormalizedPost
from backend.app.observability import TelemetryRecorder

TEXT_FIELDS = (
    "pain_summary",
    "workflow",
    "workaround",
    "buyer",
    "time_cost",
    "industry",
)
EVALUATED_FIELDS = (*TEXT_FIELDS, "budget_owner", "existing_tools")


class Extractor(Protocol):
    """Extraction dependency required by the evaluation runner."""

    def extract(self, normalized: NormalizedPost) -> object: ...


class Pipeline(Protocol):
    """Pipeline dependency required by the golden evaluation runner."""

    def process_post(self, post: dict[str, Any]) -> object: ...

    def process_normalized(self, normalized: NormalizedPost) -> object: ...


PipelineFactory = Callable[[TelemetryRecorder], Pipeline]


@dataclass(slots=True)
class FieldMetrics:
    """Classification counts and field-level correctness."""

    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0
    correct: int = 0
    total: int = 0
    missing_values: int = 0
    hallucinated_values: int = 0

    @property
    def precision(self) -> float:
        denominator = self.true_positive + self.false_positive
        return self.true_positive / denominator if denominator else 0.0

    @property
    def recall(self) -> float:
        denominator = self.true_positive + self.false_negative
        return self.true_positive / denominator if denominator else 0.0

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0


@dataclass(frozen=True, slots=True)
class CaseEvaluation:
    """Validity and discrepancy details for one golden case."""

    case_id: str
    json_valid: bool
    missing_values: tuple[str, ...]
    hallucinated_values: tuple[str, ...]
    latency_seconds: float = 0.0
    retry_count: int = 0
    error: str | None = None

    @property
    def unexpected_fields(self) -> tuple[str, ...]:
        return self.hallucinated_values


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Aggregate output from one frozen evaluation run."""

    cases: tuple[CaseEvaluation, ...]
    fields: dict[str, FieldMetrics]

    @property
    def total_cases(self) -> int:
        return len(self.cases)

    @property
    def valid_json_cases(self) -> int:
        return sum(case.json_valid for case in self.cases)

    @property
    def json_validity(self) -> float:
        return self.valid_json_cases / self.total_cases if self.total_cases else 0.0

    @property
    def precision(self) -> float:
        true_positive = sum(item.true_positive for item in self.fields.values())
        false_positive = sum(item.false_positive for item in self.fields.values())
        denominator = true_positive + false_positive
        return true_positive / denominator if denominator else 0.0

    @property
    def recall(self) -> float:
        true_positive = sum(item.true_positive for item in self.fields.values())
        false_negative = sum(item.false_negative for item in self.fields.values())
        denominator = true_positive + false_negative
        return true_positive / denominator if denominator else 0.0

    @property
    def field_accuracy(self) -> float:
        correct = sum(item.correct for item in self.fields.values())
        total = sum(item.total for item in self.fields.values())
        return correct / total if total else 0.0

    @property
    def missing_values(self) -> int:
        return sum(item.missing_values for item in self.fields.values())

    @property
    def hallucinated_values(self) -> int:
        return sum(item.hallucinated_values for item in self.fields.values())

    @property
    def unexpected_fields(self) -> int:
        return self.hallucinated_values

    @property
    def retry_count(self) -> int:
        return sum(case.retry_count for case in self.cases)

    @property
    def average_latency(self) -> float:
        if not self.cases:
            return 0.0
        return sum(case.latency_seconds for case in self.cases) / len(self.cases)


class EvaluationRunner:
    """Execute extraction and compare values to a golden dataset."""

    def __init__(
        self,
        extractor: Extractor,
        *,
        schema_directory: Path | None = None,
    ) -> None:
        self._extractor = extractor
        schema_path = schema_directory or self._default_schema_directory()
        self._validator: Validator = Draft202012Validator(
            self._load_schema(schema_path / "extraction.json"),
            format_checker=FormatChecker(),
        )

    def run(self, dataset: GoldenDataset) -> EvaluationResult:
        """Evaluate every case without suppressing provider failures."""

        fields = {name: FieldMetrics() for name in EVALUATED_FIELDS}
        case_results = [self._evaluate_case(case, fields) for case in dataset]
        return EvaluationResult(tuple(case_results), fields)

    def _evaluate_case(
        self,
        case: GoldenCase,
        fields: dict[str, FieldMetrics],
    ) -> CaseEvaluation:
        try:
            extracted = self._extractor.extract(case.normalized)
            prediction = self._json_payload(extracted)
            self._validator.validate(prediction)
        except (
            ExtractionValidationError,
            JsonSchemaValidationError,
            TypeError,
        ) as exc:
            missing = self._score_invalid_case(case, fields)
            return CaseEvaluation(
                case_id=case.case_id,
                json_valid=False,
                missing_values=tuple(missing),
                hallucinated_values=(),
                error=str(exc),
            )

        missing, hallucinated = self._score_case(case, prediction, fields)
        return CaseEvaluation(
            case_id=case.case_id,
            json_valid=True,
            missing_values=tuple(missing),
            hallucinated_values=tuple(hallucinated),
        )

    @staticmethod
    def _score_invalid_case(
        case: GoldenCase,
        fields: dict[str, FieldMetrics],
    ) -> list[str]:
        """Count an invalid output as incorrect for every evaluated field."""

        missing: list[str] = []
        gold_payload = case.gold.model_dump(mode="json")
        for field_name in TEXT_FIELDS:
            metrics = fields[field_name]
            metrics.total += 1
            expected = cast(
                str | None,
                cast(dict[str, Any], gold_payload[field_name])["value"],
            )
            if expected is not None:
                metrics.false_negative += 1
                metrics.missing_values += 1
                missing.append(f"{field_name}={expected}")

        budget_metrics = fields["budget_owner"]
        budget_metrics.total += 1
        expected_budget = cast(
            str,
            cast(dict[str, Any], gold_payload["budget_owner"])["value"],
        )
        if expected_budget != "unknown":
            budget_metrics.false_negative += 1
            budget_metrics.missing_values += 1
            missing.append(f"budget_owner={expected_budget}")

        tool_metrics = fields["existing_tools"]
        tool_metrics.total += 1
        expected_tools = {
            EvaluationRunner._normalize_value(str(tool["name"]))
            for tool in cast(
                list[dict[str, Any]],
                gold_payload["existing_tools"],
            )
        }
        tool_metrics.false_negative += len(expected_tools)
        tool_metrics.missing_values += len(expected_tools)
        missing.extend(f"existing_tools={value}" for value in sorted(expected_tools))
        return missing

    def _score_case(
        self,
        case: GoldenCase,
        prediction: dict[str, Any] | None,
        fields: dict[str, FieldMetrics],
    ) -> tuple[list[str], list[str]]:
        missing: list[str] = []
        hallucinated: list[str] = []
        gold_payload = case.gold.model_dump(mode="json")

        for field_name in TEXT_FIELDS:
            expected = cast(
                str | None,
                cast(dict[str, Any], gold_payload[field_name])["value"],
            )
            predicted = (
                None
                if prediction is None
                else cast(
                    str | None,
                    cast(dict[str, Any], prediction[field_name])["value"],
                )
            )
            accepted = case.acceptable_values.get(field_name, ())
            self._score_value(
                field_name,
                expected,
                predicted,
                accepted,
                fields[field_name],
                missing,
                hallucinated,
            )

        expected_budget = cast(
            str,
            cast(dict[str, Any], gold_payload["budget_owner"])["value"],
        )
        predicted_budget = (
            "unknown"
            if prediction is None
            else cast(
                str,
                cast(dict[str, Any], prediction["budget_owner"])["value"],
            )
        )
        self._score_value(
            "budget_owner",
            None if expected_budget == "unknown" else expected_budget,
            None if predicted_budget == "unknown" else predicted_budget,
            (),
            fields["budget_owner"],
            missing,
            hallucinated,
        )

        expected_tools = {
            self._normalize_value(str(tool["name"]))
            for tool in cast(list[dict[str, Any]], gold_payload["existing_tools"])
        }
        predicted_tools = (
            set()
            if prediction is None
            else {
                self._normalize_value(str(tool["name"]))
                for tool in cast(
                    list[dict[str, Any]],
                    prediction["existing_tools"],
                )
            }
        )
        self._score_tools(
            expected_tools,
            predicted_tools,
            fields["existing_tools"],
            missing,
            hallucinated,
        )
        return missing, hallucinated

    @classmethod
    def _score_value(
        cls,
        field_name: str,
        expected: str | None,
        predicted: str | None,
        acceptable: tuple[str, ...],
        metrics: FieldMetrics,
        missing: list[str],
        hallucinated: list[str],
    ) -> None:
        metrics.total += 1
        if expected is None and predicted is None:
            metrics.correct += 1
            return
        if expected is None:
            metrics.false_positive += 1
            metrics.hallucinated_values += 1
            hallucinated.append(f"{field_name}={predicted}")
            return
        if predicted is None:
            metrics.false_negative += 1
            metrics.missing_values += 1
            missing.append(f"{field_name}={expected}")
            return

        accepted_values = {
            cls._normalize_value(value) for value in (expected, *acceptable)
        }
        if cls._normalize_value(predicted) in accepted_values:
            metrics.true_positive += 1
            metrics.correct += 1
            return

        metrics.false_positive += 1
        metrics.false_negative += 1
        metrics.missing_values += 1
        metrics.hallucinated_values += 1
        missing.append(f"{field_name}={expected}")
        hallucinated.append(f"{field_name}={predicted}")

    @staticmethod
    def _score_tools(
        expected: set[str],
        predicted: set[str],
        metrics: FieldMetrics,
        missing: list[str],
        hallucinated: list[str],
    ) -> None:
        true_positive = expected & predicted
        false_negative = expected - predicted
        false_positive = predicted - expected
        metrics.total += 1
        metrics.true_positive += len(true_positive)
        metrics.false_negative += len(false_negative)
        metrics.false_positive += len(false_positive)
        metrics.missing_values += len(false_negative)
        metrics.hallucinated_values += len(false_positive)
        if expected == predicted:
            metrics.correct += 1
        missing.extend(f"existing_tools={value}" for value in sorted(false_negative))
        hallucinated.extend(
            f"existing_tools={value}" for value in sorted(false_positive)
        )

    @staticmethod
    def _normalize_value(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip().casefold()

    @staticmethod
    def _json_payload(extracted: object) -> dict[str, Any]:
        if isinstance(extracted, BaseModel):
            return extracted.model_dump(mode="json")
        if isinstance(extracted, Mapping):
            return dict(extracted)
        raise TypeError("extractor output must be a Pydantic model or mapping")

    @staticmethod
    def _load_schema(path: Path) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _default_schema_directory() -> Path:
        repository_schemas = Path(__file__).resolve().parents[3] / "schemas"
        if repository_schemas.is_dir():
            return repository_schemas
        return Path(__file__).resolve().parents[1] / "schemas" / "contracts"


class PipelineEvaluationRunner:
    """Run the synchronous pipeline over golden cases and compare outputs."""

    def __init__(
        self,
        pipeline_factory: PipelineFactory,
        *,
        schema_directory: Path | None = None,
    ) -> None:
        self._pipeline_factory = pipeline_factory
        self._scorer = EvaluationRunner(
            _UnusedExtractor(),
            schema_directory=schema_directory,
        )

    def run(self, dataset: GoldenDataset) -> EvaluationResult:
        """Evaluate every case through the full pipeline."""

        fields = {name: FieldMetrics() for name in EVALUATED_FIELDS}
        case_results = [
            self._evaluate_pipeline_case(case, fields) for case in dataset
        ]
        return EvaluationResult(tuple(case_results), fields)

    def _evaluate_pipeline_case(
        self,
        case: GoldenCase,
        fields: dict[str, FieldMetrics],
    ) -> CaseEvaluation:
        telemetry = EvaluationTelemetry()
        pipeline = self._pipeline_factory(telemetry)
        try:
            if case.raw is not None:
                extracted = pipeline.process_post(case.raw).complaint
            else:
                extracted = pipeline.process_normalized(case.normalized).complaint
            prediction = EvaluationRunner._json_payload(extracted)
            self._scorer._validator.validate(prediction)
        except (
            ExtractionValidationError,
            JsonSchemaValidationError,
            TypeError,
        ) as exc:
            missing = self._scorer._score_invalid_case(case, fields)
            return CaseEvaluation(
                case_id=case.case_id,
                json_valid=False,
                missing_values=tuple(missing),
                hallucinated_values=(),
                latency_seconds=telemetry.latency_seconds,
                retry_count=telemetry.retry_count,
                error=str(exc),
            )

        missing, hallucinated = self._scorer._score_case(case, prediction, fields)
        return CaseEvaluation(
            case_id=case.case_id,
            json_valid=True,
            missing_values=tuple(missing),
            hallucinated_values=tuple(hallucinated),
            latency_seconds=telemetry.latency_seconds,
            retry_count=telemetry.retry_count,
        )


class _UnusedExtractor:
    def extract(self, normalized: NormalizedPost) -> object:
        raise RuntimeError("extractor must not be used by PipelineEvaluationRunner")
