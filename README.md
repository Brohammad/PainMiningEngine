# SignalMine

SignalMine turns unstructured internet discussions into structured,
evidence-backed market intelligence. The current repository contains the
approved Phase 0 contracts and a passive Python backend skeleton. It does not
collect, normalize, extract, validate, or persist data yet.

The product definition and constraints are authoritative in
[`docs/`](docs/). The canonical data contracts are the JSON Schemas in
[`schemas/`](schemas/).

## Current scope

This skeleton provides:

- Python package boundaries for the synchronous V1 pipeline
- typed settings through `pydantic-settings`
- explicit dependency injection without module-level service instances
- standard-library logging configuration
- Ruff, Black, and Mypy configuration

It deliberately contains no Reddit integration, LLM calls, database models,
FastAPI endpoints, workers, or frontend.

## Backend package responsibilities

| Package | Responsibility |
|---------|----------------|
| `backend.app.collector` | Boundary for acquiring raw discussion payloads. The V1 implementation will target Reddit, but no client exists yet. |
| `backend.app.normalizer` | Boundary for deterministic conversion of raw payloads into the canonical normalized document contract. |
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
python -m build
```

## Repository layout

```text
backend/app/  Python package boundaries
docs/         Product, architecture, data model, and evaluation contracts
prompts/      Versioned extraction prompt policy
schemas/      Canonical JSON Schema contracts
```
