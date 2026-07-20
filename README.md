# SignalMine

SignalMine turns unstructured internet discussions into structured,
evidence-backed market intelligence.

The product definition and constraints are authoritative in
[`docs/`](docs/). The canonical data contracts are the JSON Schemas in
[`schemas/`](schemas/).

## Quick start

Validate the core pipeline on a real GitHub issue:

```bash
git clone <repository-url>
cd painminingengine
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Set these in `.env`:

| Variable | Required |
|----------|----------|
| `GITHUB_TOKEN` | Recommended (strongly) — avoids GitHub rate limits during testing |
| `EXTRACTION_API_KEY` | Yes |
| `EXTRACTION_MODEL` | Yes |

Then run:

```bash
signalmine sources

signalmine fetch https://github.com/kubernetes/kubernetes/issues/12345

signalmine process https://github.com/kubernetes/kubernetes/issues/12345
```

If `process` returns a structured Complaint JSON, the collector → normalizer →
extractor → validator pipeline is working. Database, API server, and Reddit
credentials can come later.

## Sources

`fetch` and `process` accept a URL and route to the correct collector
automatically. No source-specific subcommands are required.

```bash
signalmine fetch https://github.com/org/repo/issues/42
signalmine process https://github.com/org/repo/issues/42
```

Check what is available in your environment:

```bash
signalmine sources
```

Example output:

```text
Available Sources

✓ GitHub
✓ File
○ Reddit (not configured)
○ Hacker News (planned)
```

| Source | Collection | Configuration |
|--------|------------|---------------|
| GitHub | REST API via `fetch` / `process` | `GITHUB_TOKEN` strongly recommended |
| File | `process-file <path>` | None |
| Reddit | `fetch` / `process` when configured | See optional section below |
| Hacker News | Planned | — |

All collectors implement `SourceCollector.fetch(target) -> RawDiscussion` and
return dictionaries matching
[`schemas/raw_discussion.json`](schemas/raw_discussion.json).

### GitHub

`GitHubCollector` fetches public or token-authenticated GitHub issues via the
REST API.

| Environment variable | Required / default |
|----------------------|--------------------|
| `GITHUB_TOKEN` | Recommended (strongly) |
| `GITHUB_USER_AGENT` | `signalmine-github-collector/1.0` |
| `GITHUB_REQUEST_TIMEOUT_SECONDS` | `15` |
| `GITHUB_COMMENT_LIMIT` | `50` |
| `GITHUB_RETRY_ATTEMPTS` | `3` |
| `GITHUB_RETRY_BACKOFF_SECONDS` | `1.0` |

Unauthenticated GitHub API access works for public repositories but hits rate
limits quickly. Set `GITHUB_TOKEN` before running repeated tests.

## Current scope

The current implementation provides:

- source-agnostic `RawDiscussion` contract and `SourceCollector` interface
- GitHub and Reddit collectors with URL-based routing
- deterministic RawDiscussion-to-NormalizedDocument conversion
- Instructor-backed extraction into the complaint contract
- direct synchronous collector → normalizer → extractor → validator orchestration
- insert-only SQLAlchemy persistence for every pipeline stage
- Typer commands for stage-by-stage JSON workflows
- golden-dataset extraction metrics and Markdown reports
- FastAPI endpoints for processing, complaint reads, health, and Prometheus metrics

It deliberately contains no authentication, embeddings, clustering,
opportunity scoring, workers, or frontend.

## Optional: Reddit source (requires Reddit API access)

Reddit collection requires a Reddit API application. Until credentials are
approved and configured, use GitHub as the default validation path.

| Environment variable | Required / default |
|----------------------|--------------------|
| `REDDIT_CLIENT_ID` | Required for Reddit |
| `REDDIT_CLIENT_SECRET` | Required for Reddit |
| `REDDIT_USER_AGENT` | Required for Reddit |
| `REDDIT_REQUEST_TIMEOUT_SECONDS` | `10` |
| `REDDIT_RATE_LIMIT_WAIT_SECONDS` | `60` |
| `REDDIT_RETRY_ATTEMPTS` | `3` |
| `REDDIT_RETRY_BACKOFF_SECONDS` | `1.0` |
| `REDDIT_COMMENT_LIMIT` | `20` |
| `REDDIT_COMMENT_MAX_DEPTH` | `3` |

Create a script app at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps),
then add credentials to `.env`. Once configured, Reddit URLs work through the
same commands:

```bash
signalmine fetch https://www.reddit.com/r/devops/comments/abc123/title/
signalmine process https://www.reddit.com/r/devops/comments/abc123/title/
```

`RedditCollector` maps PRAW submissions to `RawDiscussion`. Legacy Reddit
envelope JSON ([`schemas/raw_reddit.json`](schemas/raw_reddit.json)) is still
accepted by `FileCollector` and coerced automatically.

## Normalizer

`DispatchingNormalizer` routes `RawDiscussion` captures to the correct source
normalizer and returns one object matching
[`schemas/normalized_document.json`](schemas/normalized_document.json).

The transformation removes Markdown syntax, collapses whitespace
deterministically, converts timestamps to UTC ISO 8601, and stores original text
under `metadata.original_text`. No AI inference or persistence occurs in this
stage.

## Extraction engine

`ExtractionEngine.extract(normalized)` accepts a schema-valid normalized post
and returns a strict Pydantic `Complaint` matching
[`schemas/extraction.json`](schemas/extraction.json).

| Environment variable | Required / default |
|----------------------|--------------------|
| `EXTRACTION_API_KEY` | Required |
| `EXTRACTION_MODEL` | Required |
| `EXTRACTION_PROVIDER` | `openai` |
| `EXTRACTION_BASE_URL` | OpenAI default when unset |
| `EXTRACTION_PROMPT_VERSION` | `extract_v1` |
| `EXTRACTION_TEMPERATURE` | `0` |
| `EXTRACTION_TIMEOUT_SECONDS` | `60` |
| `EXTRACTION_VALIDATION_RETRIES` | `2` |

## Synchronous pipeline

```text
Collector → Normalizer → Extractor → Validator → Complaint
```

`process <url>` runs the complete flow for GitHub or Reddit URLs. The CLI does
not persist results unless storage is injected explicitly (the REST API does).

## Persistence and REST API

Persistence requires PostgreSQL, `DATABASE_URL`, and Alembic migrations. These
are needed for the API server, not for the CLI quick start above.

```bash
DATABASE_URL=postgresql+psycopg://... alembic upgrade head
uv run uvicorn backend.app.api:create_app --factory
```

| Method | Path | Contract |
|--------|------|----------|
| `POST` | `/process` | `{"url": "https://..."}` → Complaint |
| `GET` | `/complaints/{id}` | Persisted Complaint |
| `GET` | `/health` | Database health |
| `GET` | `/metrics` | Prometheus metrics |

## Command-line interface

Install the project, then run `signalmine --help`.

| Command | Input | Execution |
|---------|-------|-----------|
| `sources` | — | List configured and planned sources |
| `fetch` | URL (argument or `--input`) | Collector → RawDiscussion JSON |
| `process` | URL (argument or `--input`) | Full pipeline → Complaint JSON |
| `normalize` | RawDiscussion JSON | Normalizer only |
| `extract` | NormalizedDocument JSON | Extractor only |
| `process-file` | Local JSON path | Full pipeline from file |
| `trace` | URL | Pipeline stage trace JSON |

Examples:

```bash
signalmine fetch https://github.com/kubernetes/kubernetes/issues/12345
signalmine process https://github.com/kubernetes/kubernetes/issues/12345 --output complaint.json
signalmine normalize --input raw.json --output normalized.json
signalmine extract --input normalized.json --output complaint.json
```

## Development

Python 3.11 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Repository layout

```text
backend/app/  Python package boundaries
docs/         Product, architecture, data model, and evaluation contracts
prompts/      Versioned extraction prompt policy
schemas/      Canonical JSON Schema contracts
```
