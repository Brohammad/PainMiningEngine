# SignalMine

SignalMine turns unstructured internet discussions into structured,
evidence-backed market intelligence. The current repository contains the
approved Phase 0 contracts, the Python backend skeleton, and the Reddit
collector and normalizer. It does not extract or persist data yet.

The product definition and constraints are authoritative in
[`docs/`](docs/). The canonical data contracts are the JSON Schemas in
[`schemas/`](schemas/).

## Current scope

The current implementation provides:

- Python package boundaries for the synchronous V1 pipeline
- PRAW-backed Reddit collection into the Phase 0 raw schema
- deterministic RawReddit-to-NormalizedDocument conversion
- typed settings through `pydantic-settings`
- explicit dependency injection without module-level service instances
- standard-library logging configuration
- Ruff, Black, and Mypy configuration

It deliberately contains no LLM calls, database models, FastAPI endpoints,
workers, or frontend.

## Backend package responsibilities

| Package | Responsibility |
|---------|----------------|
| `backend.app.collector` | PRAW-backed acquisition of Reddit posts, subreddit listings, and search results mapped directly to the raw Reddit contract. |
| `backend.app.normalizer` | Deterministic conversion of RawReddit captures into the canonical NormalizedDocument contract. |
| `backend.app.extractor` | Boundary for producing structured market-intelligence candidates from normalized documents. |
| `backend.app.validator` | Boundary for JSON contract validation and provenance span checks before persistence. |
| `backend.app.storage` | Persistence boundary for raw, normalized, and versioned extraction artifacts. No database models exist yet. |
| `backend.app.schemas` | Future Python representations of the JSON contracts in the repository-level `schemas/` directory. |
| `backend.app.models` | Persistence-independent domain model boundary. |
| `backend.app.config` | Settings, logging setup, and the explicit dependency container. |
| `backend.app.utils` | Shared side-effect-free helpers that do not belong to a domain package. |
| `backend.app.pipeline` | Future synchronous orchestration boundary for collector → normalizer → extractor → validator → storage. |

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
