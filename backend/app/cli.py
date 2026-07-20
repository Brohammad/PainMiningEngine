"""Typer command-line interface for explicit pipeline stages."""

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, cast

import typer

from backend.app.collector import (
    FileCollector,
    GitHubSettings,
    RedditSettings,
    URLCollector,
    URLCollectorSettings,
    build_url_collector,
)
from backend.app.collector.discussion import coerce_to_discussion
from backend.app.collector.source_status import format_sources_report, reddit_configured
from backend.app.config import Settings, configure_logging
from backend.app.evaluation import (
    BenchmarkConfigError,
    BenchmarkReport,
    BenchmarkRunner,
    GoldenCreateError,
    GoldenDataset,
    GoldenDatasetError,
    MarkdownReport,
    PipelineEvaluationRunner,
    create_golden_case,
    default_benchmark_models,
    load_benchmark_models,
)
from backend.app.extractor import ExtractionEngine, ExtractionSettings
from backend.app.normalizer import DispatchingNormalizer
from backend.app.observability import NoOpTelemetry, ObservabilitySettings, Telemetry, TelemetryRecorder
from backend.app.pipeline import PipelineTracer, SourceCollector, SynchronousPipeline
from backend.app.source_identity import (
    CompositeIdentityResolver,
    GitHubDiscussionIdentityResolver,
    RedditDiscussionIdentityResolver,
)
from backend.app.validator import ComplaintValidator

app = typer.Typer(
    name="signalmine",
    help="Run SignalMine pipeline stages and emit JSON.",
    no_args_is_help=True,
)

UrlArgument = Annotated[
    str | None,
    typer.Argument(help="Discussion URL (GitHub issue or Reddit thread)."),
]
InputOption = Annotated[
    str | None,
    typer.Option("--input", help="Input URL, JSON file path, or '-' for stdin."),
]
OutputOption = Annotated[
    str,
    typer.Option("--output", help="Output JSON file path or '-' for stdout."),
]
VerboseOption = Annotated[
    bool,
    typer.Option("--verbose", help="Enable verbose diagnostic logging."),
]
DatasetOption = Annotated[
    Path,
    typer.Option("--dataset", help="Golden dataset directory."),
]
ReportOption = Annotated[
    Path,
    typer.Option("--output", help="Markdown report output path."),
]
GoldenCaseDirOption = Annotated[
    Path,
    typer.Option("--output", help="Golden case directory to create."),
]
ModelsConfigOption = Annotated[
    Path | None,
    typer.Option(
        "--models-config",
        help="JSON file listing benchmark model profiles.",
    ),
]
TraceOutputOption = Annotated[
    Path | None,
    typer.Option(
        "--trace-output",
        help="Write the pipeline stage trace JSON to this path.",
    ),
]


@app.command()
def sources() -> None:
    """List available discussion sources and configuration status."""

    typer.echo(format_sources_report())


@app.command()
def fetch(
    url: UrlArgument = None,
    input_value: InputOption = None,
    output: OutputOption = "-",
    verbose: VerboseOption = False,
) -> None:
    """Fetch one discussion URL and emit a RawDiscussion JSON object."""

    _configure_logging(verbose)
    target = _resolve_target(url, input_value)
    _write_json(_url_collector().fetch(target), output)


@app.command()
def normalize(
    input_value: InputOption,
    output: OutputOption = "-",
    verbose: VerboseOption = False,
) -> None:
    """Normalize one RawDiscussion JSON object."""

    _configure_logging(verbose)
    raw = _read_json(_require_input(input_value))
    discussion = coerce_to_discussion(raw)
    _write_json(DispatchingNormalizer().normalize(discussion), output)


@app.command()
def extract(
    input_value: InputOption,
    output: OutputOption = "-",
    verbose: VerboseOption = False,
) -> None:
    """Extract one Complaint from a NormalizedDocument JSON object."""

    _configure_logging(verbose)
    normalized = _read_json(_require_input(input_value))
    complaint = ExtractionEngine(_extraction_settings()).extract(normalized)
    _write_json(complaint.model_dump(mode="json"), output)


@app.command()
def process(
    url: UrlArgument = None,
    input_value: InputOption = None,
    output: OutputOption = "-",
    trace_output: TraceOutputOption = None,
    verbose: VerboseOption = False,
) -> None:
    """Run the synchronous pipeline for one discussion URL."""

    _configure_logging(verbose)
    target = _resolve_target(url, input_value)
    complaint, tracer = _run_pipeline(
        collector=_url_collector(),
        input_value=target,
        verbose=verbose,
    )
    _write_json(complaint.model_dump(mode="json"), output)
    _maybe_write_trace(tracer, trace_output)


FilePathArgument = Annotated[
    Path,
    typer.Argument(help="Path to a RawDiscussion JSON file."),
]


@app.command("process-file")
def process_file(
    file_path: FilePathArgument,
    output: OutputOption = "-",
    trace_output: TraceOutputOption = None,
    verbose: VerboseOption = False,
) -> None:
    """Run the synchronous pipeline for one local RawDiscussion JSON file."""

    _configure_logging(verbose)
    complaint, tracer = _run_pipeline(
        collector=FileCollector(),
        input_value=str(file_path),
        verbose=verbose,
    )
    _write_json(complaint.model_dump(mode="json"), output)
    _maybe_write_trace(tracer, trace_output)


@app.command()
def trace(
    url: UrlArgument = None,
    input_value: InputOption = None,
    output: OutputOption = "-",
    verbose: VerboseOption = False,
) -> None:
    """Run the pipeline and emit a structured stage trace."""

    _configure_logging(verbose)
    target = _resolve_target(url, input_value)
    _, tracer = _run_pipeline(
        collector=_url_collector(),
        input_value=target,
        verbose=verbose,
    )
    from backend.app.api.trace import to_trace_response

    _write_json(
        to_trace_response(tracer.trace).model_dump(mode="json"),
        output,
    )


@app.command("process-url")
def process_url(
    input_value: InputOption,
    output: OutputOption = "-",
    verbose: VerboseOption = False,
) -> None:
    """Fetch one Reddit URL via HTML scraping and emit a RawDiscussion JSON object."""

    _configure_logging(verbose)
    collector = URLCollector(URLCollectorSettings())
    _write_json(collector.fetch(_require_input(input_value)), output)


@app.command()
def evaluate(
    dataset: DatasetOption = Path("tests/golden"),
    output: ReportOption = Path("evaluation.md"),
    verbose: VerboseOption = False,
) -> None:
    """Run the pipeline over a golden dataset and write a Markdown report."""

    _configure_logging(verbose)
    try:
        loaded = GoldenDataset.load(dataset)
    except GoldenDatasetError as exc:
        raise typer.BadParameter(str(exc), param_hint="--dataset") from exc

    runner = PipelineEvaluationRunner(_build_evaluation_pipeline)
    result = runner.run(loaded)
    MarkdownReport.write(result, output)
    typer.echo(f"Wrote evaluation report to {output}")


@app.command("create-golden")
def create_golden(
    input_value: InputOption,
    output: GoldenCaseDirOption,
    verbose: VerboseOption = False,
) -> None:
    """Create a golden case folder for manual extraction annotation."""

    _configure_logging(verbose)
    raw = _read_json(_require_input(input_value))
    try:
        case_dir = create_golden_case(raw, output)
    except GoldenCreateError as exc:
        raise typer.BadParameter(str(exc), param_hint="--input") from exc

    typer.echo(f"Created golden case at {case_dir}")


@app.command()
def benchmark(
    dataset: DatasetOption = Path("tests/golden"),
    output: ReportOption = Path("benchmark.md"),
    models_config: ModelsConfigOption = None,
    verbose: VerboseOption = False,
) -> None:
    """Run a golden dataset across multiple models and compare results."""

    _configure_logging(verbose)
    try:
        loaded = GoldenDataset.load(dataset)
    except GoldenDatasetError as exc:
        raise typer.BadParameter(str(exc), param_hint="--dataset") from exc

    try:
        models = (
            load_benchmark_models(models_config)
            if models_config is not None
            else default_benchmark_models()
        )
    except BenchmarkConfigError as exc:
        raise typer.BadParameter(str(exc), param_hint="--models-config") from exc

    result = BenchmarkRunner(defaults=_extraction_settings()).run(loaded, models)
    BenchmarkReport.write(result, output)
    typer.echo(f"Wrote benchmark report to {output}")


def _resolve_target(url: str | None, input_value: str | None) -> str:
    target = url or input_value
    if target is None or not target.strip():
        raise typer.BadParameter(
            "provide a discussion URL as an argument or --input",
            param_hint="url",
        )
    return target.strip()


def _require_input(input_value: str | None) -> str:
    if input_value is None or not input_value.strip():
        raise typer.BadParameter(
            "--input is required",
            param_hint="--input",
        )
    return input_value.strip()


def _run_pipeline(
    *,
    collector: SourceCollector,
    input_value: str,
    verbose: bool,
) -> tuple[Any, PipelineTracer]:
    telemetry: TelemetryRecorder
    if verbose:
        telemetry = Telemetry(ObservabilitySettings())
    else:
        telemetry = NoOpTelemetry()
    tracer = PipelineTracer(telemetry)
    pipeline = SynchronousPipeline(
        collector=collector,
        normalizer=DispatchingNormalizer(),
        extractor=ExtractionEngine(_extraction_settings(), telemetry=telemetry),
        validator=ComplaintValidator(telemetry=telemetry),
        telemetry=tracer,
        identity_resolver=CompositeIdentityResolver(
            [
                GitHubDiscussionIdentityResolver(),
                RedditDiscussionIdentityResolver(),
            ]
        ),
    )
    return pipeline.process_url(input_value).complaint, tracer


def _maybe_write_trace(tracer: PipelineTracer, trace_output: Path | None) -> None:
    if trace_output is None:
        return
    from backend.app.api.trace import to_trace_response

    payload = to_trace_response(tracer.trace).model_dump(mode="json")
    _write_json(payload, str(trace_output))


def _build_evaluation_pipeline(telemetry: TelemetryRecorder) -> SynchronousPipeline:
    settings = _extraction_settings()
    return SynchronousPipeline(
        collector=_unused_collector(),
        normalizer=DispatchingNormalizer(),
        extractor=ExtractionEngine(settings, telemetry=telemetry),
        validator=ComplaintValidator(),
        telemetry=telemetry,
    )


def _unused_collector() -> SourceCollector:
    class UnusedCollector:
        def fetch(self, url: str) -> dict[str, Any]:
            raise RuntimeError(f"collector must not be used during evaluation: {url}")

    return cast(SourceCollector, UnusedCollector())


def _configure_logging(verbose: bool) -> None:
    level = "DEBUG" if verbose else "INFO"
    configure_logging(Settings(log_level=level))


def _url_collector() -> SourceCollector:
    reddit_settings = _reddit_settings() if reddit_configured() else None
    return build_url_collector(
        github_settings=_github_settings(),
        reddit_settings=reddit_settings,
    )


def _reddit_settings() -> RedditSettings:
    factory = cast(Callable[[], RedditSettings], RedditSettings)
    return factory()


def _github_settings() -> GitHubSettings:
    factory = cast(Callable[[], GitHubSettings], GitHubSettings)
    return factory()


def _extraction_settings() -> ExtractionSettings:
    factory = cast(Callable[[], ExtractionSettings], ExtractionSettings)
    return factory()


def _read_json(input_value: str) -> dict[str, Any]:
    try:
        content = (
            sys.stdin.read()
            if input_value == "-"
            else Path(input_value).read_text(encoding="utf-8")
        )
        payload = json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(
            f"unable to read JSON input: {exc}",
            param_hint="--input",
        ) from exc

    if not isinstance(payload, dict):
        raise typer.BadParameter(
            "JSON input must be an object",
            param_hint="--input",
        )
    return cast(dict[str, Any], payload)


def _write_json(payload: dict[str, Any], output: str) -> None:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if output == "-":
        typer.echo(serialized)
        return

    try:
        Path(output).write_text(f"{serialized}\n", encoding="utf-8")
    except OSError as exc:
        raise typer.BadParameter(
            f"unable to write JSON output: {exc}",
            param_hint="--output",
        ) from exc
