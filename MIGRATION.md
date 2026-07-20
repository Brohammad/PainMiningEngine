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

The pipeline depends only on this interface. Concrete collectors (`RedditCollector`, `FileCollector`, `URLCollector`) implement it today. `GitHubCollector` is not implemented yet.

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
- `DiscussionIdentityResolver` is optional; the API/CLI composition roots inject `RedditDiscussionIdentityResolver` for Reddit URL duplicate detection.

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

## Follow-up (not in this migration)

- Implement `GitHubCollector` implementing `SourceCollector`
- Split `RedditNormalizer` into generic `DiscussionNormalizer` + Reddit field mapping if a second source lands
- Migrate existing `raw_sources.payload` rows in DB from legacy envelope to `RawDiscussion` (optional; new ingests already store `RawDiscussion`)
- Remove deprecated aliases after downstream consumers migrate

## Test status

All **113** tests pass after updating fixtures and assertions for the new contracts.
