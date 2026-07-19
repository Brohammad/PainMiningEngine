"""Deterministic Markdown reporting for extraction evaluations."""

from pathlib import Path

from backend.app.evaluation.runner import EvaluationResult


class MarkdownReport:
    """Render and write human-reviewable evaluation results."""

    @staticmethod
    def render(result: EvaluationResult) -> str:
        """Render aggregate, field, and case metrics as Markdown."""

        lines = [
            "# SignalMine Extraction Evaluation",
            "",
            "## Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Cases | {result.total_cases} |",
            (
                "| Valid JSON | "
                f"{result.valid_json_cases}/{result.total_cases} "
                f"({result.json_validity:.2%}) |"
            ),
            f"| Precision | {result.precision:.2%} |",
            f"| Recall | {result.recall:.2%} |",
            f"| Field-level accuracy | {result.field_accuracy:.2%} |",
            f"| Missing values | {result.missing_values} |",
            f"| Hallucinated values | {result.hallucinated_values} |",
            "",
            "## Field metrics",
            "",
            ("| Field | Precision | Recall | Accuracy | Missing | " "Hallucinated |"),
            "|-------|-----------|--------|----------|---------|--------------|",
        ]
        for field_name, metrics in result.fields.items():
            lines.append(
                f"| `{field_name}` | {metrics.precision:.2%} | "
                f"{metrics.recall:.2%} | {metrics.accuracy:.2%} | "
                f"{metrics.missing_values} | "
                f"{metrics.hallucinated_values} |"
            )

        lines.extend(
            [
                "",
                "## Case details",
                "",
                "| Case | JSON valid | Missing | Hallucinated | Error |",
                "|------|------------|---------|--------------|-------|",
            ]
        )
        for case in result.cases:
            missing = MarkdownReport._escape(", ".join(case.missing_values) or "—")
            hallucinated = MarkdownReport._escape(
                ", ".join(case.hallucinated_values) or "—"
            )
            lines.append(
                f"| `{MarkdownReport._escape(case.case_id)}` | "
                f"{'yes' if case.json_valid else 'no'} | "
                f"{missing} | "
                f"{hallucinated} | "
                f"{MarkdownReport._escape(case.error or '—')} |"
            )

        return "\n".join(lines) + "\n"

    @staticmethod
    def write(result: EvaluationResult, output: Path) -> None:
        """Write a rendered report to the requested path."""

        output.write_text(MarkdownReport.render(result), encoding="utf-8")

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("|", r"\|").replace("\n", " ")
