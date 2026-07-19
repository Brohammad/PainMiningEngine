"""Typer command-line interface for explicit pipeline stages."""

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, cast

import typer

from backend.app.collector import RedditCollector, RedditSettings
from backend.app.config import Settings, configure_logging
from backend.app.extractor import ExtractionEngine, ExtractionSettings
from backend.app.normalizer import RedditNormalizer
from backend.app.pipeline import SynchronousPipeline
from backend.app.validator import ComplaintValidator

app = typer.Typer(
    name="signalmine",
    help="Run SignalMine pipeline stages and emit JSON.",
    no_args_is_help=True,
)

InputOption = Annotated[
    str,
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


@app.command()
def fetch(
    input_value: InputOption,
    output: OutputOption = "-",
    verbose: VerboseOption = False,
) -> None:
    """Fetch one Reddit URL and emit a RawReddit JSON object."""

    _configure_logging(verbose)
    collector = RedditCollector(_reddit_settings())
    _write_json(collector.fetch_post(input_value), output)


@app.command()
def normalize(
    input_value: InputOption,
    output: OutputOption = "-",
    verbose: VerboseOption = False,
) -> None:
    """Normalize one RawReddit JSON object."""

    _configure_logging(verbose)
    raw = _read_json(input_value)
    _write_json(RedditNormalizer().normalize(raw), output)


@app.command()
def extract(
    input_value: InputOption,
    output: OutputOption = "-",
    verbose: VerboseOption = False,
) -> None:
    """Extract one Complaint from a NormalizedDocument JSON object."""

    _configure_logging(verbose)
    normalized = _read_json(input_value)
    complaint = ExtractionEngine(_extraction_settings()).extract(normalized)
    _write_json(complaint.model_dump(mode="json"), output)


@app.command()
def process(
    input_value: InputOption,
    output: OutputOption = "-",
    verbose: VerboseOption = False,
) -> None:
    """Run the synchronous pipeline for one Reddit URL."""

    _configure_logging(verbose)
    pipeline = SynchronousPipeline(
        collector=RedditCollector(_reddit_settings()),
        normalizer=RedditNormalizer(),
        extractor=ExtractionEngine(_extraction_settings()),
        validator=ComplaintValidator(),
    )
    complaint = pipeline.process_url(input_value)
    _write_json(complaint.model_dump(mode="json"), output)


def _configure_logging(verbose: bool) -> None:
    level = "DEBUG" if verbose else "INFO"
    configure_logging(Settings(log_level=level))


def _reddit_settings() -> RedditSettings:
    factory = cast(Callable[[], RedditSettings], RedditSettings)
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
