"""Golden dataset, metric, and Markdown report tests."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from backend.app.evaluation import (
    EvaluationRunner,
    GoldenDataset,
    MarkdownReport,
    PipelineEvaluationRunner,
)
from backend.app.extractor import (
    Complaint,
    ComplaintCandidate,
    EvidenceField,
    EvidenceSource,
    ExtractionMeta,
    ExtractionValidationError,
    Provenance,
    TextField,
    ToolMention,
    TriStateField,
)


class SequenceExtractor:
    """Return predetermined outputs in dataset order."""

    def __init__(self, outputs: list[object]) -> None:
        self._outputs: Iterator[object] = iter(outputs)
        self.inputs: list[dict[str, Any]] = []

    def extract(self, normalized: dict[str, Any]) -> object:
        self.inputs.append(normalized)
        output = next(self._outputs)
        if isinstance(output, Exception):
            raise output
        return output


def make_normalized(
    case_number: int,
    body: str,
) -> dict[str, Any]:
    return {
        "id": str(UUID(int=case_number)),
        "platform": "reddit",
        "external_id": f"t3_case{case_number}",
        "url": f"https://www.reddit.com/r/devops/comments/case{case_number}/",
        "title": f"Case {case_number}",
        "content": body,
        "comments": [],
        "author": "operator",
        "score": 10,
        "created_at": "2024-07-19T09:00:00+00:00",
        "fetched_at": "2024-07-19T10:00:00+00:00",
        "community": "devops",
        "metadata": {},
    }


def evidence_for(body: str) -> Provenance:
    return Provenance(
        source=EvidenceSource.REDDIT,
        field=EvidenceField.BODY,
        comment_id=None,
        character_range=[0, len(body)],
        confidence=0.95,
    )


def empty_field() -> TextField:
    return TextField(value=None, evidence=[])


def make_candidate(
    *,
    pain: str | None = None,
    buyer: str | None = None,
    body: str,
    tools: tuple[str, ...] = (),
) -> ComplaintCandidate:
    evidence = evidence_for(body)
    return ComplaintCandidate(
        pain_summary=TextField(
            value=pain,
            evidence=[evidence] if pain is not None else [],
        ),
        workflow=empty_field(),
        workaround=empty_field(),
        buyer=TextField(
            value=buyer,
            evidence=[evidence] if buyer is not None else [],
        ),
        budget_owner=TriStateField(value="unknown", evidence=[]),
        time_cost=empty_field(),
        industry=empty_field(),
        existing_tools=[ToolMention(name=name, evidence=[evidence]) for name in tools],
    )


def make_complaint(
    candidate: ComplaintCandidate,
    normalized: dict[str, Any],
) -> Complaint:
    return Complaint.model_validate(
        {
            **candidate.model_dump(),
            "meta": ExtractionMeta(
                model="test-model",
                prompt_version="extract_v1",
                provider="openai",
                temperature=0.0,
                source_id=str(normalized["external_id"]),
                document_id=UUID(str(normalized["id"])),
                extracted_at=datetime(2026, 7, 19, 12, 30, tzinfo=UTC),
            ),
        }
    )


def write_case(
    dataset_path: Path,
    case_id: str,
    normalized: dict[str, Any],
    gold: ComplaintCandidate,
    *,
    acceptable_values: dict[str, list[str]] | None = None,
) -> None:
    case_path = dataset_path / case_id
    case_path.mkdir(parents=True)
    (case_path / "input.json").write_text(
        json.dumps(normalized),
        encoding="utf-8",
    )
    gold_payload = gold.model_dump(mode="json")
    if acceptable_values is not None:
        gold_payload["acceptable_values"] = acceptable_values
    (case_path / "expected.json").write_text(
        json.dumps(gold_payload),
        encoding="utf-8",
    )


def build_dataset(tmp_path: Path) -> tuple[
    GoldenDataset,
    list[dict[str, Any]],
    list[ComplaintCandidate],
]:
    dataset_path = tmp_path / "golden"
    case1_body = "Manual certificate rotation with certbot takes hours."
    case2_body = "A platform engineer owns this workflow."
    case3_body = "No operational complaint appears here."
    normalized = [
        make_normalized(1, case1_body),
        make_normalized(2, case2_body),
        make_normalized(3, case3_body),
    ]
    gold = [
        make_candidate(
            pain="Manual certificate rotation takes hours.",
            body=case1_body,
            tools=("certbot",),
        ),
        make_candidate(
            buyer="Platform engineer",
            body=case2_body,
        ),
        make_candidate(body=case3_body),
    ]
    write_case(
        dataset_path,
        "case-b",
        normalized[1],
        gold[1],
    )
    write_case(
        dataset_path,
        "case-a",
        normalized[0],
        gold[0],
        acceptable_values={
            "pain_summary": [
                "Certificate rotation takes hours manually.",
            ]
        },
    )
    write_case(
        dataset_path,
        "case-c",
        normalized[2],
        gold[2],
    )
    return GoldenDataset.load(dataset_path), normalized, gold


def test_golden_dataset_loads_sorted_validated_cases(tmp_path: Path) -> None:
    dataset, normalized, _gold = build_dataset(tmp_path)

    assert [case.case_id for case in dataset] == [
        "case-a",
        "case-b",
        "case-c",
    ]
    assert dataset[0].normalized == normalized[0]
    assert dataset[0].acceptable_values["pain_summary"] == (
        "Certificate rotation takes hours manually.",
    )


def test_evaluation_computes_validity_precision_recall_and_accuracy(
    tmp_path: Path,
) -> None:
    dataset, normalized, _gold = build_dataset(tmp_path)
    case1_prediction = make_candidate(
        pain="Certificate rotation takes hours manually.",
        body=str(normalized[0]["content"]),
        tools=("certbot",),
    )
    case2_prediction = make_candidate(
        pain="An invented pain.",
        body=str(normalized[1]["content"]),
    )
    extractor = SequenceExtractor(
        [
            make_complaint(case1_prediction, normalized[0]),
            make_complaint(case2_prediction, normalized[1]),
            {"invalid": "complaint"},
        ]
    )

    result = EvaluationRunner(extractor).run(dataset)

    assert result.total_cases == 3
    assert result.valid_json_cases == 2
    assert result.json_validity == pytest.approx(2 / 3)
    assert result.precision == pytest.approx(2 / 3)
    assert result.recall == pytest.approx(2 / 3)
    assert result.field_accuracy == pytest.approx(14 / 24)
    assert result.missing_values == 1
    assert result.hallucinated_values == 1
    assert result.fields["existing_tools"].precision == 1.0
    assert result.cases[1].missing_values == ("buyer=Platform engineer",)
    assert result.cases[1].hallucinated_values == ("pain_summary=An invented pain.",)
    assert result.cases[2].json_valid is False


def test_evaluation_records_extraction_validation_failure(
    tmp_path: Path,
) -> None:
    dataset, _normalized, _gold = build_dataset(tmp_path)
    extractor = SequenceExtractor(
        [
            ExtractionValidationError("invalid response"),
            ExtractionValidationError("invalid response"),
            ExtractionValidationError("invalid response"),
        ]
    )

    result = EvaluationRunner(extractor).run(dataset)

    assert result.valid_json_cases == 0
    assert all(case.error == "invalid response" for case in result.cases)


def test_evaluation_does_not_hide_provider_failures(tmp_path: Path) -> None:
    dataset, _normalized, _gold = build_dataset(tmp_path)
    extractor = SequenceExtractor([RuntimeError("provider unavailable")])

    with pytest.raises(RuntimeError, match="provider unavailable"):
        EvaluationRunner(extractor).run(dataset)


def test_markdown_report_renders_and_writes_metrics(tmp_path: Path) -> None:
    dataset, normalized, gold = build_dataset(tmp_path)
    extractor = SequenceExtractor(
        [
            make_complaint(gold[0], normalized[0]),
            make_complaint(gold[1], normalized[1]),
            make_complaint(gold[2], normalized[2]),
        ]
    )
    result = EvaluationRunner(extractor).run(dataset)
    report_path = tmp_path / "evaluation.md"

    MarkdownReport.write(result, report_path)
    report = report_path.read_text(encoding="utf-8")

    assert "# SignalMine Evaluation Report" in report
    assert "| Schema validity | 3/3 (100.00%) |" in report
    assert "| Field accuracy | 100.00% |" in report
    assert "| Missing fields | 0 |" in report
    assert "| Unexpected fields | 0 |" in report
    assert "| `pain_summary` |" in report
    assert "| `case-a` | yes |" in report


def test_pipeline_evaluation_runs_full_pipeline_and_records_latency(
    tmp_path: Path,
) -> None:
    dataset, normalized, gold = build_dataset(tmp_path)

    class FakePipeline:
        def process_post(self, post: dict[str, Any]) -> Complaint:
            raise AssertionError("raw input not used in this dataset")

        def process_normalized(self, normalized_doc: dict[str, Any]) -> Complaint:
            from backend.app.pipeline.result import PipelineResult

            index = next(
                index
                for index, item in enumerate(dataset)
                if item.normalized == normalized_doc
            )
            return PipelineResult(
                complaint=make_complaint(gold[index], normalized_doc)
            )

    class PipelineFactory:
        def __call__(self, telemetry: object) -> FakePipeline:
            from backend.app.evaluation.telemetry import EvaluationTelemetry

            assert isinstance(telemetry, EvaluationTelemetry)

            class InstrumentedPipeline(FakePipeline):
                def process_normalized(
                    self,
                    normalized_doc: dict[str, Any],
                ) -> object:
                    from backend.app.pipeline.result import PipelineResult

                    with telemetry.pipeline_run():
                        result = super().process_normalized(normalized_doc)
                    assert isinstance(result, PipelineResult)
                    return result

            return InstrumentedPipeline()

    result = PipelineEvaluationRunner(PipelineFactory()).run(dataset)

    assert result.total_cases == 3
    assert result.valid_json_cases == 3
    assert result.field_accuracy == 1.0
    assert all(case.latency_seconds >= 0 for case in result.cases)


def test_builtin_golden_fixture_loads_input_and_expected() -> None:
    dataset = GoldenDataset.load(Path("tests/golden"))

    assert [case.case_id for case in dataset] == ["case-a"]
    assert dataset[0].normalized["external_id"] == "t3_case1"
    assert dataset[0].gold.pain_summary.value == (
        "Manual certificate rotation takes hours."
    )
