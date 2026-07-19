"""Loading and validating frozen golden extraction datasets."""

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.protocols import Validator

from backend.app.normalizer import NormalizedPost, RedditNormalizer
from backend.app.schemas import ComplaintCandidate


class GoldenDatasetError(ValueError):
    """Raised when a golden fixture set is missing or malformed."""


class Normalizer(Protocol):
    """Normalizer subset used when a fixture has only raw JSON."""

    def normalize(self, raw: dict[str, Any]) -> NormalizedPost: ...


@dataclass(frozen=True, slots=True)
class GoldenCase:
    """One normalized input and its human-authored expected extraction."""

    case_id: str
    normalized: NormalizedPost
    gold: ComplaintCandidate
    acceptable_values: dict[str, tuple[str, ...]]


class GoldenDataset:
    """Frozen, deterministically ordered collection of golden cases."""

    def __init__(self, cases: Sequence[GoldenCase]) -> None:
        if not cases:
            raise GoldenDatasetError("golden dataset contains no cases")
        self._cases = tuple(cases)

    def __getitem__(self, index: int) -> GoldenCase:
        return self._cases[index]

    def __len__(self) -> int:
        return len(self._cases)

    def __iter__(self) -> Iterator[GoldenCase]:
        return iter(self._cases)

    @classmethod
    def load(
        cls,
        directory: Path,
        *,
        normalizer: Normalizer | None = None,
        schema_directory: Path | None = None,
    ) -> "GoldenDataset":
        """Load `<case>/gold.json` plus normalized or raw input fixtures."""

        if not directory.is_dir():
            raise GoldenDatasetError(
                f"golden dataset directory does not exist: {directory}"
            )

        schema_path = schema_directory or cls._default_schema_directory()
        normalized_validator: Validator = Draft202012Validator(
            cls._read_json(schema_path / "normalized_document.json"),
            format_checker=FormatChecker(),
        )
        fixture_normalizer = normalizer or RedditNormalizer(schema_path)
        cases = [
            cls._load_case(
                case_directory,
                fixture_normalizer,
                normalized_validator,
            )
            for case_directory in sorted(directory.iterdir())
            if case_directory.is_dir()
        ]
        return cls(cases)

    @classmethod
    def _load_case(
        cls,
        directory: Path,
        normalizer: Normalizer,
        normalized_validator: Validator,
    ) -> GoldenCase:
        gold_path = directory / "gold.json"
        if not gold_path.is_file():
            raise GoldenDatasetError(f"missing gold.json for {directory.name}")

        normalized_path = directory / "normalized.json"
        if normalized_path.is_file():
            normalized = cls._read_json(normalized_path)
        else:
            raw_path = directory / "raw.json"
            if not raw_path.is_file():
                raise GoldenDatasetError(
                    f"{directory.name} requires normalized.json or raw.json"
                )
            normalized = normalizer.normalize(cls._read_json(raw_path))

        normalized_validator.validate(normalized)
        gold_payload = cls._read_json(gold_path)
        acceptable_values = cls._acceptable_values(
            gold_payload.pop("acceptable_values", {})
        )
        gold_payload.pop("meta", None)
        try:
            gold = ComplaintCandidate.model_validate_json(json.dumps(gold_payload))
        except ValueError as exc:
            raise GoldenDatasetError(f"invalid gold.json for {directory.name}") from exc

        return GoldenCase(
            case_id=directory.name,
            normalized=normalized,
            gold=gold,
            acceptable_values=acceptable_values,
        )

    @staticmethod
    def _acceptable_values(value: object) -> dict[str, tuple[str, ...]]:
        if not isinstance(value, dict):
            raise GoldenDatasetError("acceptable_values must be an object")

        accepted: dict[str, tuple[str, ...]] = {}
        for field_name, alternatives in value.items():
            if not isinstance(field_name, str) or not isinstance(
                alternatives,
                list,
            ):
                raise GoldenDatasetError(
                    "acceptable_values entries must be string arrays"
                )
            if not all(isinstance(item, str) for item in alternatives):
                raise GoldenDatasetError(
                    "acceptable_values entries must be string arrays"
                )
            accepted[field_name] = tuple(alternatives)
        return accepted

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GoldenDatasetError(f"unable to read {path}") from exc
        if not isinstance(payload, dict):
            raise GoldenDatasetError(f"{path} must contain a JSON object")
        return cast(dict[str, Any], payload)

    @staticmethod
    def _default_schema_directory() -> Path:
        repository_schemas = Path(__file__).resolve().parents[3] / "schemas"
        if repository_schemas.is_dir():
            return repository_schemas
        return Path(__file__).resolve().parents[1] / "schemas" / "contracts"
