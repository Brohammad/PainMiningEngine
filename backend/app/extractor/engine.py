"""Instructor-backed extraction with strict validation boundaries."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol, cast
from uuid import UUID

import instructor
from instructor.core.exceptions import InstructorRetryException
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from jsonschema.protocols import Validator
from openai import OpenAI
from pydantic import ValidationError as PydanticValidationError

from backend.app.extractor.models import (
    Complaint,
    ComplaintCandidate,
    ExtractionMeta,
)
from backend.app.extractor.prompt import ExtractionPrompt
from backend.app.extractor.prompt_registry import PromptRegistry
from backend.app.extractor.settings import ExtractionSettings
from backend.app.extractor.usage import TokenUsage, extract_token_usage
from backend.app.normalizer import NormalizedPost
from backend.app.observability import NoOpTelemetry, TelemetryRecorder
from backend.app.validator.complaint import (
    ComplaintValidationError,
    ComplaintValidator,
)


class ExtractionValidationError(ValueError):
    """Raised when all response validation attempts fail."""


class _Completions(Protocol):
    def create(
        self,
        *,
        model: str,
        response_model: type[ComplaintCandidate],
        messages: list[dict[str, str]],
        max_retries: int,
        temperature: float,
    ) -> object: ...


class _Chat(Protocol):
    completions: _Completions


class InstructorClient(Protocol):
    """Subset of the synchronous Instructor client used by the engine."""

    chat: _Chat


class ExtractionEngine:
    """Extract schema-valid complaints from normalized posts."""

    def __init__(
        self,
        settings: ExtractionSettings,
        client: InstructorClient | None = None,
        *,
        prompt_path: Path | None = None,
        prompt_registry: PromptRegistry | None = None,
        schema_directory: Path | None = None,
        clock: Callable[[], datetime] | None = None,
        telemetry: TelemetryRecorder | None = None,
        usage_records: list[TokenUsage] | None = None,
    ) -> None:
        self._settings = settings
        self._client = client if client is not None else self._build_client(settings)
        if prompt_path is not None:
            self._prompt = ExtractionPrompt.load(prompt_path)
        else:
            registry = prompt_registry or PromptRegistry.default()
            self._prompt = registry.get(settings.prompt_version)
        schema_path = schema_directory or self._default_schema_directory()
        format_checker = FormatChecker()
        self._normalized_validator: Validator = Draft202012Validator(
            self._load_schema(schema_path / "normalized_document.json"),
            format_checker=format_checker,
        )
        self._telemetry = telemetry or NoOpTelemetry()
        self._complaint_validator = ComplaintValidator(
            schema_path,
            telemetry=self._telemetry,
        )
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)
        self._usage_records = usage_records

    def extract(self, normalized: NormalizedPost) -> Complaint:
        """Extract one complaint, retrying response validation failures only."""

        try:
            self._normalized_validator.validate(normalized)
        except JsonSchemaValidationError:
            self._telemetry.record_validation_failure("normalized_schema")
            raise
        messages = [
            {"role": "system", "content": self._prompt.system_prompt},
            {"role": "user", "content": self._prompt.render_user(normalized)},
        ]
        last_error: Exception | None = None

        for attempt in range(self._settings.validation_retries + 1):
            started_at = perf_counter()
            try:
                raw_candidate = self._client.chat.completions.create(
                    model=self._settings.model,
                    response_model=ComplaintCandidate,
                    messages=messages,
                    max_retries=0,
                    temperature=self._settings.temperature,
                )
                if self._usage_records is not None:
                    usage = extract_token_usage(raw_candidate)
                    if usage is not None:
                        self._usage_records.append(usage)
                candidate = ComplaintCandidate.model_validate(raw_candidate)
                complaint = self._complete_complaint(candidate, normalized)
                validated = self._complaint_validator.validate(
                    complaint,
                    normalized,
                )
            except (
                InstructorRetryException,
                PydanticValidationError,
                ComplaintValidationError,
            ) as exc:
                self._telemetry.observe_extraction_latency(
                    started_at,
                    "validation_failure",
                )
                reason = self._validation_failure_reason(exc)
                if not isinstance(exc, ComplaintValidationError):
                    self._telemetry.record_validation_failure(reason)
                last_error = exc
                if attempt < self._settings.validation_retries:
                    self._telemetry.record_retry("extraction", reason)
            except Exception:
                self._telemetry.observe_extraction_latency(started_at, "error")
                raise
            else:
                self._telemetry.observe_extraction_latency(started_at, "success")
                return validated

        raise ExtractionValidationError(
            "extraction response validation retries exhausted"
        ) from last_error

    @staticmethod
    def _validation_failure_reason(error: Exception) -> str:
        if isinstance(error, InstructorRetryException):
            return "instructor_response"
        if isinstance(error, PydanticValidationError):
            return "pydantic_response"
        return "complaint_validation"

    def _complete_complaint(
        self,
        candidate: ComplaintCandidate,
        normalized: NormalizedPost,
    ) -> Complaint:
        timestamp = self._clock()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        meta = ExtractionMeta(
            model=self._settings.model,
            prompt_version=self._prompt.version,
            provider=self._settings.provider,
            temperature=self._settings.temperature,
            source_id=str(normalized["external_id"]),
            document_id=UUID(str(normalized["id"])),
            extracted_at=timestamp.astimezone(UTC),
        )
        return Complaint.model_validate(
            {
                **candidate.model_dump(),
                "meta": meta,
            }
        )

    @staticmethod
    def _build_client(settings: ExtractionSettings) -> InstructorClient:
        openai_client = OpenAI(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
            max_retries=0,
        )
        modes = {
            "tools": instructor.Mode.TOOLS,
            "json": instructor.Mode.JSON,
            "json_schema": instructor.Mode.JSON_SCHEMA,
        }
        return cast(
            InstructorClient,
            instructor.from_openai(
                openai_client,
                mode=modes[settings.instructor_mode],
            ),
        )

    @staticmethod
    def _load_schema(path: Path) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _default_schema_directory() -> Path:
        repository_schemas = Path(__file__).resolve().parents[3] / "schemas"
        if repository_schemas.is_dir():
            return repository_schemas
        return Path(__file__).resolve().parents[1] / "schemas" / "contracts"
