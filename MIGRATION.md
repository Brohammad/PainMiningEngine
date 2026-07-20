# Source-agnostic architecture migration

This document records the architectural refactor that generalizes SignalMine
from a Reddit-specific pipeline into a source-agnostic market intelligence
platform. Business logic, extraction prompts, complaint schema, and database
semantics are unchanged unless noted below.

## Summary

| Before | After |
|--------|-------|
| `RawRedditCapture` / `RawReddit` / `RedditThread` / `RedditPost` | `RawDiscussion` |
| `Collector.fetch_post()` | `SourceCollector.fetch()` |
| `reddit_identity_from_url()` in pipeline | `DiscussionIdentityResolver` injected at composition root |
| Duplicate match type `reddit_id` | `platform_id` |
| Normalizer reads legacy Reddit envelope | Normalizer reads `RawDiscussion` |
| `raw_sources.payload` stores legacy envelope | `raw_sources.payload` stores `RawDiscussion` (legacy files coerced on ingest) |

## New contracts

### `RawDiscussion` ([`schemas/raw_discussion.json`](../schemas/raw_discussion.json))

Source-agnostic capture stored in `raw_sources.payload`:

- `source` — platform identifier (`reddit`, future: `github`, `hackernews`, …)
- `discussion_id` — stable platform id (maps to DB `external_id`)
- `title`, `body`, `comments`, `author`, `created_at`, `updated_at`, `url`
- `metadata` — source-specific fields (Reddit: `subreddit`, `score`, `flair`; GitHub: `repository`, `labels`, …)

### `SourceCollector` ([`backend/app/collector/source_collector.py`](../backend/app/collector/source_collector.py))

```python
class SourceCollector(Protocol):
    def fetch(self, target: str) -> RawDiscussion: ...
```

The pipeline depends only on this interface. Concrete collectors include
`GitHubCollector`, `RedditCollector`, `FileCollector`, and `URLCollector`.

### `DiscussionSource` enum ([`backend/app/collector/sources.py`](../backend/app/collector/sources.py))

Canonical `source` values: `reddit`, `github`, `hackernews`, `file`. The
`raw_discussion.json` schema constrains `source` to this enum.

### Legacy adapter

[`schemas/raw_reddit.json`](../schemas/raw_reddit.json) remains as a **legacy Reddit envelope** for fixtures and backward-compatible file ingest. `coerce_to_discussion()` in [`backend/app/collector/discussion.py`](../backend/app/collector/discussion.py) converts legacy captures to `RawDiscussion` at collection time.

## Pipeline changes

[`backend/app/pipeline/synchronous.py`](../backend/app/pipeline/synchronous.py)

```
SourceCollector.fetch()
    → DiscussionNormalizer.normalize()
    → Extractor.extract()
    → Validator.validate()
    → StageStorage (optional)
```

- `process_discussion(discussion)` is the canonical entry point; `process_post()` is a backward-compatible alias.
- `process_url(url)` calls `collector.fetch(url)` — no Reddit imports in the pipeline module.
- `DiscussionIdentityResolver` is optional; API/CLI inject `CompositeIdentityResolver` with GitHub and Reddit resolvers when configured.

## GitHub collector and CLI (post-migration)

### GitHub collector

- [`backend/app/collector/github.py`](../backend/app/collector/github.py) — `GitHubCollector` fetches issues via GitHub REST API
- [`backend/app/collector/github_parser.py`](../backend/app/collector/github_parser.py) — issue URL parsing and canonical identity
- [`backend/app/collector/github_settings.py`](../backend/app/collector/github_settings.py) — `GITHUB_*` settings
- [`backend/app/normalizer/github.py`](../backend/app/normalizer/github.py) — GitHub `RawDiscussion` → `NormalizedDocument`
- [`backend/app/normalizer/dispatch.py`](../backend/app/normalizer/dispatch.py) — `DispatchingNormalizer` routes by `source`
- [`backend/app/collector/wiring.py`](../backend/app/collector/wiring.py) — `build_url_collector()` routes URLs to GitHub/Reddit
- [`backend/app/collector/source_status.py`](../backend/app/collector/source_status.py) — runtime source availability for `signalmine sources`

`discussion_id` for GitHub issues: `{owner}/{repo}#issue-{number}`.

`GITHUB_TOKEN` is optional for public repos but **strongly recommended** to avoid rate limits.

### URL routing

`fetch` and `process` accept a URL argument (or `--input`) and route automatically:

```bash
signalmine fetch https://github.com/org/repo/issues/42
signalmine process https://github.com/org/repo/issues/42
```

Reddit is registered in the URL router only when `REDDIT_*` credentials are
present, so GitHub-only validation does not require Reddit API access.

### CLI

| Change | Detail |
|--------|--------|
| `signalmine sources` | Lists GitHub, File, Reddit, Hacker News availability |
| Positional URLs | `fetch` / `process` / `trace` accept URL as first argument |
| Removed | `fetch-github` (use `fetch` with any supported URL) |
| README | GitHub-first Quick Start; Reddit moved to optional section |

### Identity resolution

- `GitHubDiscussionIdentityResolver` in [`backend/app/source_identity.py`](../backend/app/source_identity.py)
- `CompositeIdentityResolver` tries GitHub then Reddit for duplicate detection

## Storage changes

[`backend/app/storage/repository.py`](../backend/app/storage/repository.py)

- `save_raw(discussion: RawDiscussion)` reads `discussion["source"]` and `discussion["discussion_id"]` instead of `post["source"]["platform"]` / `external_id`.
- Duplicate lookup by platform id returns `match_type="platform_id"` (was `reddit_id`).
- Database columns are unchanged: `(platform, external_id)` still index raw and normalized rows.

## API changes

- `duplicate_match` enum values: `url`, `platform_id`, `content_hash` (was `reddit_id`).
- No route or response shape changes beyond the renamed duplicate match type.

## Evaluation changes

- Golden fixture `input_schema` metadata is `raw_discussion`.
- `create-golden` accepts legacy Reddit JSON or `RawDiscussion` and writes canonical `RawDiscussion` to `input.json`.
- `GoldenDataset.load()` coerces legacy fixtures before normalization.

## Backward compatibility

| Symbol | Status |
|--------|--------|
| `RawRedditCapture` | Type alias for `RawDiscussion` in `reddit.py` |
| `fetch_post()` on collectors | Alias for `fetch()` |
| `reddit_identity_from_url()` | Re-exported from `reddit_identity.py`; delegates to `RedditDiscussionIdentityResolver` |
| `Collector` / `Normalizer` in `pipeline` | Aliases for `SourceCollector` / `DiscussionNormalizer` |
| Legacy JSON fixture files | Still loadable via `FileCollector` and `coerce_to_discussion()` |

## What did not change

- Extraction prompts ([`prompts/extract_v1.md`](../prompts/extract_v1.md))
- Complaint / extraction schema ([`schemas/extraction.json`](../schemas/extraction.json))
- Normalized document schema and normalization **behavior** for Reddit content
- Database table/column names and migration history
- Duplicate detection semantics (URL, platform+id, content hash)

## Follow-up

- Hacker News collector
- Migrate existing `raw_sources.payload` rows in DB from legacy envelope to `RawDiscussion` (optional)
- Remove deprecated aliases after downstream consumers migrate

## Test status

- **113** tests after the source-agnostic refactor
- **125** tests after GitHub collector and CLI UX changes
