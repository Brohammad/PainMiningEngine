"""Final complaint validation against contracts and source provenance."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NoReturn, cast

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from jsonschema.protocols import Validator
from pydantic import ValidationError as PydanticValidationError

from backend.app.normalizer import NormalizedPost
from backend.app.observability import NoOpTelemetry, TelemetryRecorder
from backend.app.schemas.complaint import (
    Complaint,
    EvidenceField,
    Provenance,
)


class ComplaintValidationError(ValueError):
    """Raised when a complaint fails a final validation boundary."""


class ComplaintValidator:
    """Validate complaint shape and provenance without modifying the input."""

    def __init__(
        self,
        schema_directory: Path | None = None,
        telemetry: TelemetryRecorder | None = None,
    ) -> None:
        schema_path = schema_directory or self._default_schema_directory()
        format_checker = FormatChecker()
        self._normalized_validator: Validator = Draft202012Validator(
            self._load_schema(schema_path / "normalized_document.json"),
            format_checker=format_checker,
        )
        self._complaint_validator: Validator = Draft202012Validator(
            self._load_schema(schema_path / "extraction.json"),
            format_checker=format_checker,
        )
        self._telemetry = telemetry or NoOpTelemetry()

    def validate(
        self,
        complaint: Complaint | Mapping[str, Any],
        normalized: NormalizedPost,
    ) -> Complaint:
        """Return the unchanged complaint after all validation gates pass."""

        try:
            self._normalized_validator.validate(normalized)
        except JsonSchemaValidationError as exc:
            self._fail("normalized_schema", exc)

        try:
            validated = Complaint.model_validate(complaint)
        except (PydanticValidationError, ValueError) as exc:
            self._fail("pydantic", exc)

        try:
            self._complaint_validator.validate(validated.model_dump(mode="json"))
        except JsonSchemaValidationError as exc:
            self._fail("complaint_schema", exc)

        try:
            self._validate_provenance(validated, normalized)
        except ValueError as exc:
            self._fail("provenance", exc)
        return validated

    def _fail(self, gate: str, error: Exception) -> NoReturn:
        self._telemetry.record_validation_failure(gate)
        raise ComplaintValidationError("complaint validation failed") from error

    @staticmethod
    def _validate_provenance(
        complaint: Complaint,
        normalized: NormalizedPost,
    ) -> None:
        comments = {
            str(comment["id"]): str(comment["body"])
            for comment in cast(list[dict[str, Any]], normalized["comments"])
        }
        evidence_groups = [
            complaint.pain_summary.evidence,
            complaint.workflow.evidence,
            complaint.workaround.evidence,
            complaint.buyer.evidence,
            complaint.budget_owner.evidence,
            complaint.time_cost.evidence,
            complaint.industry.evidence,
            *[tool.evidence for tool in complaint.existing_tools],
        ]

        for evidence in (
            item for evidence_group in evidence_groups for item in evidence_group
        ):
            ComplaintValidator._validate_evidence_span(
                evidence,
                normalized,
                comments,
            )

    @staticmethod
    def _validate_evidence_span(
        evidence: Provenance,
        normalized: NormalizedPost,
        comments: dict[str, str],
    ) -> None:
        if evidence.source.value != normalized["platform"]:
            raise ValueError("evidence source does not match normalized platform")

        if evidence.field is EvidenceField.TITLE:
            source_text = str(normalized["title"])
        elif evidence.field is EvidenceField.BODY:
            source_text = str(normalized["content"])
        else:
            if evidence.comment_id not in comments:
                raise ValueError("evidence comment_id does not exist")
            source_text = comments[evidence.comment_id]

        _start, end = evidence.character_range
        if end > len(source_text):
            raise ValueError("evidence character_range exceeds source text")

    @staticmethod
    def _load_schema(path: Path) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _default_schema_directory() -> Path:
        repository_schemas = Path(__file__).resolve().parents[3] / "schemas"
        if repository_schemas.is_dir():
            return repository_schemas
        return Path(__file__).resolve().parents[1] / "schemas" / "contracts"
