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

        def fetch_post(self, url: str) -> dict[str, Any]:
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
    assert inputs == [raw]
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

    class FakePipeline:
        def __init__(self, **dependencies: object) -> None:
            assert set(dependencies) == {
                "collector",
                "normalizer",
                "extractor",
                "validator",
            }

        def process_url(self, url: str) -> FakeComplaint:
            calls.append(url)
            return FakeComplaint(complaint)

    monkeypatch.setattr(cli, "RedditSettings", lambda: object())
    monkeypatch.setattr(cli, "ExtractionSettings", lambda: object())
    monkeypatch.setattr(cli, "RedditCollector", lambda _settings: object())
    monkeypatch.setattr(cli, "RedditNormalizer", lambda: object())
    monkeypatch.setattr(cli, "ExtractionEngine", lambda _settings: object())
    monkeypatch.setattr(cli, "ComplaintValidator", lambda: object())
    monkeypatch.setattr(cli, "SynchronousPipeline", FakePipeline)

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
