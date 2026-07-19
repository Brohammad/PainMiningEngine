# SignalMine

SignalMine turns unstructured internet discussions into structured,
evidence-backed market intelligence. The current repository contains the
approved Phase 0 contracts, the Python backend skeleton, and the Reddit
collector, normalizer, extraction engine, synchronous pipeline, and persistence
layer.

The product definition and constraints are authoritative in
[`docs/`](docs/). The canonical data contracts are the JSON Schemas in
[`schemas/`](schemas/).

## Current scope

The current implementation provides:

- Python package boundaries for the synchronous V1 pipeline
- PRAW-backed Reddit collection into the Phase 0 raw schema
- deterministic RawReddit-to-NormalizedDocument conversion
- Instructor-backed extraction into the complaint contract
- direct synchronous collector → normalizer → extractor → validator orchestration
- insert-only SQLAlchemy persistence for every pipeline stage
- Typer commands for stage-by-stage JSON workflows
- golden-dataset extraction metrics and Markdown reports
- typed settings through `pydantic-settings`
- explicit dependency injection without module-level service instances
- standard-library logging configuration
- Ruff, Black, and Mypy configuration

It deliberately contains no database models, FastAPI endpoints, embeddings,
clustering, opportunity scoring, workers, or frontend.

## Backend package responsibilities

| Package | Responsibility |
|---------|----------------|
| `backend.app.collector` | PRAW-backed acquisition of Reddit posts, subreddit listings, and search results mapped directly to the raw Reddit contract. |
| `backend.app.normalizer` | Deterministic conversion of RawReddit captures into the canonical NormalizedDocument contract. |
| `backend.app.extractor` | Instructor-backed extraction of validated complaints with span-level provenance from normalized documents. |
| `backend.app.validator` | Final Pydantic, JSON Schema, and provenance validation for complaints. |
| `backend.app.storage` | Insert-only SQLAlchemy persistence for raw, normalized, and versioned extraction artifacts. |
| `backend.app.schemas` | Future Python representations of the JSON contracts in the repository-level `schemas/` directory. |
| `backend.app.models` | Persistence-independent domain model boundary. |
| `backend.app.config` | Settings, logging setup, and the explicit dependency container. |
| `backend.app.utils` | Shared side-effect-free helpers that do not belong to a domain package. |
| `backend.app.pipeline` | Direct synchronous orchestration from collection through final validation, returning a Complaint. |
| `backend.app.evaluation` | Golden dataset loading, extraction comparison, metrics, and Markdown reporting. |

Dependencies should point inward through explicit constructor or function
arguments. Entry points will own composition and pass an
`ApplicationDependencies` instance. Packages must not create global clients,
database sessions, settings instances, or other service singletons.

## Configuration

`backend.app.config.Settings` reads environment variables with the
`SIGNALMINE_` prefix when instantiated by a future composition root.

Available skeleton settings:

| Environment variable | Default |
|----------------------|---------|
| `SIGNALMINE_APP_NAME` | `SignalMine` |
| `SIGNALMINE_ENVIRONMENT` | `development` |
| `SIGNALMINE_LOG_LEVEL` | `INFO` |

An optional local `.env` file is supported and ignored by Git. Importing the
package does not read environment variables or configure logging.

## Reddit collector

`RedditCollector` is read-only and returns dictionaries matching
[`schemas/raw_reddit.json`](schemas/raw_reddit.json). It preserves `[deleted]`
and `[removed]` body markers, maps absent authors to `null`, collects top
comments within the configured depth, and retries transient network and
rate-limit failures.

PRAW credentials and collector behavior are loaded from environment variables:

| Environment variable | Required / default |
|----------------------|--------------------|
| `REDDIT_CLIENT_ID` | Required |
| `REDDIT_CLIENT_SECRET` | Required |
| `REDDIT_USER_AGENT` | Required |
| `REDDIT_REQUEST_TIMEOUT_SECONDS` | `10` |
| `REDDIT_RATE_LIMIT_WAIT_SECONDS` | `60` |
| `REDDIT_RETRY_ATTEMPTS` | `3` |
| `REDDIT_RETRY_BACKOFF_SECONDS` | `1.0` |
| `REDDIT_COMMENT_LIMIT` | `20` |
| `REDDIT_COMMENT_MAX_DEPTH` | `3` |

Copy `.env.example` to `.env` for local development. Construct dependencies
explicitly:

```python
from backend.app.collector import RedditCollector, RedditSettings

collector = RedditCollector(RedditSettings())
capture = collector.fetch_post("https://www.reddit.com/r/example/comments/id/title/")
```

`fetch_subreddit(subreddit, limit)` and
`fetch_search(query, subreddit, limit)` return lists of the same raw capture
shape. The collector performs no normalization, extraction, or persistence.

## Reddit normalizer

`RedditNormalizer.normalize(raw)` accepts one object matching
[`schemas/raw_reddit.json`](schemas/raw_reddit.json) and returns one object
matching
[`schemas/normalized_document.json`](schemas/normalized_document.json).

The transformation:

- removes Markdown syntax while retaining its textual content
- collapses whitespace deterministically
- converts source timestamps to UTC ISO 8601
- flattens nested comment replies in traversal order
- keeps the first occurrence of each comment ID
- stores exact original title, body, and every comment body under
  `metadata.original_text`

The normalizer validates both input and output against the repository
contracts. It performs no AI inference, enrichment, extraction, or
persistence.

```python
from backend.app.normalizer import RedditNormalizer

normalized = RedditNormalizer().normalize(raw_capture)
```

## Extraction engine

`ExtractionEngine.extract(normalized)` accepts a schema-valid normalized post
and returns a strict Pydantic `Complaint` matching
[`schemas/extraction.json`](schemas/extraction.json).

All model instructions and message templates are loaded from
[`prompts/extract_v1.md`](prompts/extract_v1.md). Prompt text is not embedded
in Python. The engine asks Instructor for model-owned extraction fields, adds
host-owned metadata, then validates the complete response with both Pydantic
and JSON Schema. Evidence ranges are checked against the referenced normalized
title, body, or comment.

OpenAI and OpenAI-compatible providers use:

| Environment variable | Required / default |
|----------------------|--------------------|
| `EXTRACTION_API_KEY` | Required |
| `EXTRACTION_MODEL` | Required |
| `EXTRACTION_BASE_URL` | OpenAI default when unset |
| `EXTRACTION_INSTRUCTOR_MODE` | `tools`; also supports `json`, `json_schema` |
| `EXTRACTION_TIMEOUT_SECONDS` | `60` |
| `EXTRACTION_VALIDATION_RETRIES` | `2` |

The OpenAI client has transport retries disabled. The engine retries only
response-validation failures and returns no partially repaired output.

```python
from backend.app.extractor import (
    ExtractionEngine,
    ExtractionSettings,
)

engine = ExtractionEngine(ExtractionSettings())
complaint = engine.extract(normalized)
```

The engine does not create embeddings, clusters, opportunity scores, or
database records.

## Synchronous pipeline

`SynchronousPipeline` executes each stage directly in a fixed order:

```text
Collector → Normalizer → Extractor → Validator → Complaint
```

`process_url(url)` collects a Reddit URL and runs the complete flow.
`process_post(post)` accepts an already-collected RawReddit object and starts at
normalization. Both methods block until they return the final validated
`Complaint`; they do not enqueue work, mutate the input, cache results, or
write to storage.

```python
from backend.app.collector import RedditCollector, RedditSettings
from backend.app.extractor import ExtractionEngine, ExtractionSettings
from backend.app.normalizer import RedditNormalizer
from backend.app.pipeline import SynchronousPipeline
from backend.app.validator import ComplaintValidator

pipeline = SynchronousPipeline(
    collector=RedditCollector(RedditSettings()),
    normalizer=RedditNormalizer(),
    extractor=ExtractionEngine(ExtractionSettings()),
    validator=ComplaintValidator(),
)

complaint = pipeline.process_url(
    "https://www.reddit.com/r/example/comments/id/title/"
)
```

The pipeline has no HTTP API, workers, queues, or asynchronous orchestration.
Persistence is enabled only when storage is injected. Components are explicit;
given the same component outputs, orchestration returns the same complaint.
Extraction requests use temperature zero.

## Persistence

Persistence uses SQLAlchemy 2.x, Alembic, and PostgreSQL through psycopg. The
three Phase 0 stages remain separate:

| Python model | Table | Contents |
|--------------|-------|----------|
| `RawPost` | `raw_sources` | Original RawReddit payload |
| `NormalizedPost` | `normalized_documents` | Canonical normalized fields |
| `Complaint` | `extractions` | Versioned complaint result |

`SQLAlchemyStageStore` exposes `save_raw`, `save_normalized`, and
`save_complaint`. Each method owns and commits its own transaction. Inserts are
idempotent: repeated natural keys or identical complaint results return the
existing row ID. Existing rows are never updated. A different extraction
result remains a new immutable version.

Configure the database with:

| Environment variable | Required / default |
|----------------------|--------------------|
| `DATABASE_URL` | Required; e.g. `postgresql+psycopg://...` |
| `DATABASE_ECHO` | `false` |
| `DATABASE_POOL_PRE_PING` | `true` |

Run migrations:

```bash
DATABASE_URL=postgresql+psycopg://... uv run alembic upgrade head
```

Inject persistence into the existing synchronous pipeline:

```python
from backend.app.config import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from backend.app.storage import SQLAlchemyStageStore

engine = create_database_engine(DatabaseSettings())
store = SQLAlchemyStageStore(create_session_factory(engine))

pipeline = SynchronousPipeline(
    collector=RedditCollector(RedditSettings()),
    normalizer=RedditNormalizer(),
    extractor=ExtractionEngine(ExtractionSettings()),
    validator=ComplaintValidator(),
    storage=store,
)
```

The pipeline persists raw and normalized stages before extraction. If a later
stage fails, earlier completed stages remain committed and can be processed
again. No API, UI, queue, or worker is included.

## Command-line interface

Install the project, then run `signalmine --help`. Every command accepts
`--input`, `--output`, and `--verbose`. Use `--output -` (the default) for JSON
on stdout. `normalize` and `extract` also accept `--input -` for JSON on stdin.
Verbose diagnostics are written to stderr so stdout remains valid JSON.

| Command | Input | Execution |
|---------|-------|-----------|
| `fetch` | Reddit URL | Collector only → RawReddit JSON |
| `normalize` | RawReddit JSON path or stdin | Normalizer only → NormalizedDocument JSON |
| `extract` | NormalizedDocument JSON path or stdin | Extractor only → Complaint JSON |
| `process` | Reddit URL | One synchronous `process_url` pipeline invocation → Complaint JSON |

Examples:

```bash
signalmine fetch \
  --input https://www.reddit.com/r/example/comments/id/title/ \
  --output raw.json

signalmine normalize --input raw.json --output normalized.json
signalmine extract --input normalized.json --output complaint.json --verbose

signalmine process \
  --input https://www.reddit.com/r/example/comments/id/title/ \
  --output -
```

The CLI composes existing application boundaries and adds no FastAPI server,
frontend, worker, or asynchronous execution. The `process` command does not
inject persistence; stage storage remains an explicit application choice.

## Evaluation framework

Golden fixtures follow the Phase 0 layout:

```text
golden/
  <case-id>/
    normalized.json
    gold.json
```

`raw.json` may replace `normalized.json`; the loader then runs the deterministic
Reddit normalizer. `gold.json` contains the model-owned extraction fields.
Host metadata is ignored during comparison. An optional top-level
`acceptable_values` object can list accepted text alternatives by field.

```python
from pathlib import Path

from backend.app.evaluation import (
    EvaluationRunner,
    GoldenDataset,
    MarkdownReport,
)
from backend.app.extractor import ExtractionEngine, ExtractionSettings

dataset = GoldenDataset.load(Path("golden"))
result = EvaluationRunner(
    ExtractionEngine(ExtractionSettings())
).run(dataset)
MarkdownReport.write(result, Path("evaluation.md"))
```

The report includes JSON validity, aggregate precision and recall,
field-level accuracy, missing values, hallucinated values, per-field metrics,
and per-case discrepancies. Text matching is case-insensitive with normalized
whitespace; tool names use set comparison. Provider failures propagate, while
extraction-validation failures are recorded as invalid outputs. The framework
produces Markdown only—no dashboard or UI.

## Development

Python 3.11 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Run the quality checks:

```bash
ruff check .
black --check .
mypy backend
pytest
python -m build
```

## Repository layout

```text
backend/app/  Python package boundaries
docs/         Product, architecture, data model, and evaluation contracts
prompts/      Versioned extraction prompt policy
schemas/      Canonical JSON Schema contracts
```
