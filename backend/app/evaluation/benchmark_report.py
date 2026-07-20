"""Markdown comparison reports for multi-model benchmarks."""

from __future__ import annotations

from pathlib import Path

from backend.app.evaluation.benchmark import BenchmarkResult, ModelBenchmarkResult


class BenchmarkReport:
    """Render side-by-side model benchmark comparisons."""

    @staticmethod
    def render(result: BenchmarkResult) -> str:
        lines = [
            "# SignalMine Benchmark Report",
            "",
            "## Model comparison",
            "",
            (
                "| Model | Provider | Latency (avg) | Tokens (total) | "
                "Schema validity | Accuracy |"
            ),
            (
                "|-------|----------|---------------|----------------|"
                "-----------------|----------|"
            ),
        ]
        for model_result in result.models:
            lines.append(BenchmarkReport._summary_row(model_result))

        lines.extend(["", "## Details", ""])
        for model_result in result.models:
            lines.extend(BenchmarkReport._model_section(model_result))

        return "\n".join(lines) + "\n"

    @staticmethod
    def write(result: BenchmarkResult, output: Path) -> None:
        output.write_text(BenchmarkReport.render(result), encoding="utf-8")

    @staticmethod
    def _summary_row(model_result: ModelBenchmarkResult) -> str:
        evaluation = model_result.evaluation
        return (
            f"| {BenchmarkReport._escape(model_result.name)} | "
            f"`{BenchmarkReport._escape(model_result.profile.provider)}` | "
            f"{evaluation.average_latency:.3f}s | "
            f"{model_result.token_usage.total_tokens} | "
            f"{evaluation.json_validity:.2%} | "
            f"{evaluation.field_accuracy:.2%} |"
        )

    @staticmethod
    def _model_section(model_result: ModelBenchmarkResult) -> list[str]:
        evaluation = model_result.evaluation
        usage = model_result.token_usage
        return [
            f"### {BenchmarkReport._escape(model_result.name)}",
            "",
            f"- Model id: `{BenchmarkReport._escape(model_result.profile.model)}`",
            f"- Provider: `{BenchmarkReport._escape(model_result.profile.provider)}`",
            f"- Average latency: {evaluation.average_latency:.3f}s",
            (
                "- Token usage: "
                f"{usage.prompt_tokens} prompt / "
                f"{usage.completion_tokens} completion / "
                f"{usage.total_tokens} total"
            ),
            (
                "- Schema validity: "
                f"{evaluation.valid_json_cases}/{evaluation.total_cases} "
                f"({evaluation.json_validity:.2%})"
            ),
            f"- Field accuracy: {evaluation.field_accuracy:.2%}",
            f"- Missing fields: {evaluation.missing_values}",
            f"- Unexpected fields: {evaluation.unexpected_fields}",
            "",
        ]

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("|", r"\|").replace("\n", " ")
