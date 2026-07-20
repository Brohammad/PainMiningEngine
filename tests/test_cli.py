"""Unit tests for the Typer stage commands."""

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from backend.app import cli

runner = CliRunner()


class FakeComplaint:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return self.payload


def capture_logging(monkeypatch: Any) -> list[str]:
    levels: list[str] = []
    monkeypatch.setattr(
        cli,
        "configure_logging",
        lambda settings: levels.append(settings.log_level),
    )
    return levels


def test_fetch_executes_collector_and_writes_json_stdout(monkeypatch: Any) -> None:
    levels = capture_logging(monkeypatch)
    calls: list[str] = []
    payload = {"stage": "raw", "source": "reddit"}

    class FakeCollector:
        def __init__(self, _settings: object) -> None:
            pass

        def fetch(self, url: str) -> dict[str, Any]:
            calls.append(url)
            return payload

    monkeypatch.setattr(cli, "RedditSettings", lambda: object())
    monkeypatch.setattr(cli, "RedditCollector", FakeCollector)

    result = runner.invoke(
        cli.app,
        [
            "fetch",
            "--input",
            "https://reddit.test/post",
            "--output",
            "-",
            "--verbose",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == payload
    assert calls == ["https://reddit.test/post"]
    assert levels == ["DEBUG"]


def test_normalize_reads_json_file_and_writes_json_file(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    levels = capture_logging(monkeypatch)
    raw = {"stage": "raw"}
    coerced = {"stage": "coerced"}
    normalized = {"stage": "normalized"}
    input_path = tmp_path / "raw.json"
    output_path = tmp_path / "normalized.json"
    input_path.write_text(json.dumps(raw), encoding="utf-8")
    inputs: list[dict[str, Any]] = []

    class FakeNormalizer:
        def normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
            inputs.append(payload)
            return normalized

    monkeypatch.setattr(cli, "RedditNormalizer", FakeNormalizer)
    monkeypatch.setattr(cli, "coerce_to_discussion", lambda payload: coerced)

    result = runner.invoke(
        cli.app,
        [
            "normalize",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--verbose",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout == ""
    assert json.loads(output_path.read_text(encoding="utf-8")) == normalized
    assert inputs == [coerced]
    assert levels == ["DEBUG"]


def test_extract_reads_stdin_and_emits_complaint_json(monkeypatch: Any) -> None:
    levels = capture_logging(monkeypatch)
    normalized = {"stage": "normalized"}
    complaint = {"stage": "complaint"}
    inputs: list[dict[str, Any]] = []

    class FakeEngine:
        def __init__(self, _settings: object) -> None:
            pass

        def extract(self, payload: dict[str, Any]) -> FakeComplaint:
            inputs.append(payload)
            return FakeComplaint(complaint)

    monkeypatch.setattr(cli, "ExtractionSettings", lambda: object())
    monkeypatch.setattr(cli, "ExtractionEngine", FakeEngine)

    result = runner.invoke(
        cli.app,
        [
            "extract",
            "--input",
            "-",
            "--output",
            "-",
            "--verbose",
        ],
        input=json.dumps(normalized),
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == complaint
    assert inputs == [normalized]
    assert levels == ["DEBUG"]


def test_process_executes_synchronous_pipeline_and_emits_json(
    monkeypatch: Any,
) -> None:
    levels = capture_logging(monkeypatch)
    complaint = {"stage": "complaint"}
    calls: list[str] = []

    def fake_run_pipeline(
        *,
        collector: object,
        input_value: str,
        verbose: bool,
    ) -> tuple[FakeComplaint, object]:
        calls.append(input_value)
        assert verbose is True
        return FakeComplaint(complaint), cli.PipelineTracer()

    monkeypatch.setattr(cli, "_run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(cli, "_reddit_settings", lambda: object())
    monkeypatch.setattr(cli, "RedditCollector", lambda _settings: object())

    result = runner.invoke(
        cli.app,
        [
            "process",
            "--input",
            "https://reddit.test/post",
            "--output",
            "-",
            "--verbose",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == complaint
    assert calls == ["https://reddit.test/post"]
    assert levels == ["DEBUG"]


def test_process_file_executes_pipeline_with_local_json_file(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    levels = capture_logging(monkeypatch)
    complaint = {"stage": "complaint"}
    calls: list[tuple[object, str]] = []
    raw = {"stage": "raw", "source": {"platform": "reddit"}}
    input_path = tmp_path / "capture.json"
    input_path.write_text(json.dumps(raw), encoding="utf-8")

    def fake_run_pipeline(
        *,
        collector: object,
        input_value: str,
        verbose: bool,
    ) -> tuple[FakeComplaint, object]:
        calls.append((collector, input_value))
        assert isinstance(collector, cli.FileCollector)
        return FakeComplaint(complaint), cli.PipelineTracer()

    monkeypatch.setattr(cli, "_run_pipeline", fake_run_pipeline)

    result = runner.invoke(
        cli.app,
        [
            "process-file",
            str(input_path),
            "--output",
            "-",
            "--verbose",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == complaint
    assert calls[0][1] == str(input_path)
    assert levels == ["DEBUG"]


def test_process_writes_trace_output_when_requested(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    from datetime import UTC, datetime

    from backend.app.pipeline.trace import PipelineTrace, StageStatus

    complaint = {"stage": "complaint"}
    trace_path = tmp_path / "trace.json"
    started = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

    class FakeTracer:
        @property
        def trace(self) -> PipelineTrace:
            return PipelineTrace(
                started_at=started,
                ended_at=started,
                duration_seconds=1.0,
                status=StageStatus.SUCCESS,
                stages=(),
            )

    def fake_run_pipeline(
        *,
        collector: object,
        input_value: str,
        verbose: bool,
    ) -> tuple[FakeComplaint, FakeTracer]:
        return FakeComplaint(complaint), FakeTracer()

    monkeypatch.setattr(cli, "_run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(cli, "_reddit_settings", lambda: object())
    monkeypatch.setattr(cli, "RedditCollector", lambda _settings: object())

    result = runner.invoke(
        cli.app,
        [
            "process",
            "--input",
            "https://reddit.test/post",
            "--output",
            "-",
            "--trace-output",
            str(trace_path),
        ],
    )

    assert result.exit_code == 0
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["status"] == "success"
    assert trace["started_at"] == started.isoformat().replace("+00:00", "Z")


def test_trace_command_writes_pipeline_trace_json(
    monkeypatch: Any,
) -> None:
    from datetime import UTC, datetime

    from backend.app.pipeline.trace import PipelineTrace, StageStatus, StageTrace

    started = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

    class FakeTracer:
        @property
        def trace(self) -> PipelineTrace:
            return PipelineTrace(
                started_at=started,
                ended_at=started,
                duration_seconds=0.0,
                status=StageStatus.SUCCESS,
                stages=(
                    StageTrace(
                        stage="collector",
                        started_at=started,
                        ended_at=started,
                        duration_seconds=0.0,
                        status=StageStatus.SUCCESS,
                    ),
                ),
            )

    monkeypatch.setattr(
        cli,
        "_run_pipeline",
        lambda **_: (FakeComplaint({"ignored": True}), FakeTracer()),
    )
    monkeypatch.setattr(cli, "_reddit_settings", lambda: object())
    monkeypatch.setattr(cli, "RedditCollector", lambda _settings: object())

    result = runner.invoke(
        cli.app,
        [
            "trace",
            "--input",
            "https://reddit.test/post",
            "--output",
            "-",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "success"
    assert payload["stages"][0]["stage"] == "collector"


def test_process_url_executes_url_collector_and_writes_json_stdout(
    monkeypatch: Any,
) -> None:
    levels = capture_logging(monkeypatch)
    calls: list[str] = []
    payload = {"stage": "raw", "source": {"platform": "reddit", "api": "url_html"}}

    class FakeCollector:
        def __init__(self, _settings: object) -> None:
            pass

        def fetch(self, url: str) -> dict[str, Any]:
            calls.append(url)
            return payload

    monkeypatch.setattr(cli, "URLCollectorSettings", lambda: object())
    monkeypatch.setattr(cli, "URLCollector", FakeCollector)

    result = runner.invoke(
        cli.app,
        [
            "process-url",
            "--input",
            "https://www.reddit.com/r/devops/comments/post1/title/",
            "--output",
            "-",
            "--verbose",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == payload
    assert calls == ["https://www.reddit.com/r/devops/comments/post1/title/"]
    assert levels == ["DEBUG"]


def test_evaluate_writes_markdown_report(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    levels = capture_logging(monkeypatch)
    report_path = tmp_path / "report.md"
    run_calls: list[object] = []

    class FakeRunner:
        def __init__(self, _factory: object) -> None:
            pass

        def run(self, dataset: object) -> object:
            run_calls.append(dataset)
            from backend.app.evaluation.runner import (
                EVALUATED_FIELDS,
                CaseEvaluation,
                EvaluationResult,
                FieldMetrics,
            )

            return EvaluationResult(
                cases=(CaseEvaluation("case-a", True, (), ()),),
                fields={name: FieldMetrics() for name in EVALUATED_FIELDS},
            )

    monkeypatch.setattr(cli, "PipelineEvaluationRunner", FakeRunner)

    result = runner.invoke(
        cli.app,
        [
            "evaluate",
            "--dataset",
            "tests/golden",
            "--output",
            str(report_path),
            "--verbose",
        ],
    )

    assert result.exit_code == 0
    assert run_calls
    report = report_path.read_text(encoding="utf-8")
    assert "# SignalMine Evaluation Report" in report
    assert "Wrote evaluation report" in result.stdout
    assert levels == ["DEBUG"]


def test_benchmark_writes_markdown_report(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    levels = capture_logging(monkeypatch)
    report_path = tmp_path / "benchmark.md"
    run_calls: list[tuple[object, object]] = []

    class FakeRunner:
        def __init__(self, *, defaults: object) -> None:
            _ = defaults

        def run(self, dataset: object, models: object) -> object:
            run_calls.append((dataset, models))
            from backend.app.evaluation.benchmark import (
                BenchmarkResult,
                ModelBenchmarkResult,
            )
            from backend.app.evaluation.benchmark_models import BenchmarkModel
            from backend.app.evaluation.runner import (
                EVALUATED_FIELDS,
                CaseEvaluation,
                EvaluationResult,
                FieldMetrics,
            )
            from backend.app.extractor.usage import TokenUsage

            evaluation = EvaluationResult(
                cases=(CaseEvaluation("case-a", True, (), ()),),
                fields={name: FieldMetrics() for name in EVALUATED_FIELDS},
            )
            return BenchmarkResult(
                (
                    ModelBenchmarkResult(
                        profile=BenchmarkModel(
                            name="GPT-4.1-mini",
                            model="gpt-4.1-mini",
                            provider="openai",
                        ),
                        evaluation=evaluation,
                        token_usage=TokenUsage(10, 5, 15),
                    ),
                )
            )

    monkeypatch.setattr(cli, "BenchmarkRunner", FakeRunner)
    monkeypatch.setattr(
        cli,
        "_extraction_settings",
        lambda: object(),
    )

    result = runner.invoke(
        cli.app,
        [
            "benchmark",
            "--dataset",
            "tests/golden",
            "--output",
            str(report_path),
            "--verbose",
        ],
    )

    assert result.exit_code == 0
    assert run_calls
    report = report_path.read_text(encoding="utf-8")
    assert "# SignalMine Benchmark Report" in report
    assert "Wrote benchmark report" in result.stdout
    assert levels == ["DEBUG"]


def test_create_golden_writes_fixture_directory(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    levels = capture_logging(monkeypatch)
    raw = {
        "fetched_at": "2024-07-19T15:30:00+05:30",
        "source": {
            "platform": "reddit",
            "external_id": "t3_post1",
            "permalink": "https://www.reddit.com/r/devops/comments/post1/",
            "subreddit": "devops",
        },
        "post": {
            "id": "post1",
            "title": "Certificate rotation is painful",
            "selftext": "Manual certificate rotation takes hours.",
            "author": "operator",
            "score": 42,
            "created_utc": 1_721_379_600.0,
            "url": "https://example.com/source-link",
            "permalink": "/r/devops/comments/post1/",
            "subreddit": "devops",
        },
    }
    input_path = tmp_path / "raw.json"
    output_dir = tmp_path / "golden" / "case-cli"
    input_path.write_text(json.dumps(raw), encoding="utf-8")
    created: list[Path] = []

    def fake_create(raw_payload: dict[str, Any], destination: Path) -> Path:
        created.append(destination)
        destination.mkdir(parents=True)
        (destination / "input.json").write_text(
            json.dumps(raw_payload),
            encoding="utf-8",
        )
        (destination / "expected.json").write_text("{}", encoding="utf-8")
        (destination / "metadata.json").write_text("{}", encoding="utf-8")
        return destination

    monkeypatch.setattr(cli, "create_golden_case", fake_create)

    result = runner.invoke(
        cli.app,
        [
            "create-golden",
            "--input",
            str(input_path),
            "--output",
            str(output_dir),
            "--verbose",
        ],
    )

    assert result.exit_code == 0
    assert created == [output_dir]
    assert "Created golden case" in result.stdout
    assert levels == ["DEBUG"]
