# Eval plan (V1 quality gate)

Extraction is not “done” when the pipeline runs. It is done when it passes this gate on a **frozen** eval snapshot.

## Purpose

Measure whether `extract_v1` reliably turns Reddit threads into schema-valid, evidence-grounded JSON for the DevOps / cloud / security vertical.

## Eval set

| Property | Value |
|----------|-------|
| Size | **30–50** threads |
| Source | Reddit only |
| Vertical | DevOps, cloud infra, security ops (see [decisions.md](decisions.md)) |
| Freeze | Snapshot raw JSON under `tests/fixtures/eval/` (added at implementation time); do not silently replace mid-eval |
| Comments | Same top-N / depth policy as production ([architecture.md](architecture.md)) |

Include a mix of:

- Clear single-pain threads
- Workaround-heavy threads
- Tool-comparison threads
- Low-signal / off-topic negatives (expect mostly nulls)
- Ambiguous buyer/budget cases (expect `unknown` / null)

## Gold labels

Hand-label each fixture with a gold `extraction` object (same shape as [`schemas/extraction.json`](../schemas/extraction.json), without requiring model `meta` to match).

Labeling rules:

1. If you would not bet money the claim is in the text, gold `value` is null / `unknown`.
2. Gold `evidence` must use valid provenance spans: `source`, `field`, `character_range`, `confidence` (and `comment_id` when `field` is `comment`). The sliced text must be the supporting passage.
3. Two labelers on the first 10 items; resolve disagreements before expanding the set.

Suggested layout (when coding starts):

```text
tests/fixtures/eval/
  <external_id>/
    normalized.json       # extraction input
    raw.json              # alternative when normalized.json is absent
    gold.json             # hand labels
```

The implemented loader requires `gold.json` and either `normalized.json` or
`raw.json`. When only raw input exists, it runs the deterministic Reddit
normalizer before extraction. Cases are processed in sorted directory order.

## Scoring rubric

Run the pipeline (or extract-only on cached normalized docs). Compare model output to gold **field by field**.

### Text fields (`pain_summary`, `workflow`, `workaround`, `buyer`, `time_cost`, `industry`)

| Outcome | Credit |
|---------|--------|
| Both null | Correct (true negative) |
| Gold null, model non-null | Incorrect (invention) |
| Gold non-null, model null | Incorrect (miss) |
| Both non-null, semantic match (human or rubric-acceptable paraphrase) | Correct |
| Both non-null, different meaning | Incorrect |

For automation in week 1, use: exact match **or** casefold + whitespace-normalized equality **or** flagged “acceptable” list in gold (`acceptable_values` optional extension). Human review for borderline semantic matches when computing the release gate.

Provenance spans are **not** scored for exact range equality against gold in V1 (LLM offsets drift). They are scored under evidence validity below. Optional later metric: span IoU vs gold.

### `budget_owner`

| Gold | Model | Credit |
|------|-------|--------|
| `unknown` | `unknown` | Correct |
| `unknown` | `true` / `false` | Incorrect |
| `true` / `false` | same | Correct |
| `true` / `false` | other | Incorrect |

### `existing_tools`

- Score as set comparison on normalized tool names (casefold).
- Precision and recall both reported; gate uses **F1 ≥ 0.80** on the eval set aggregate.
- Extra invented tools count against precision.
- Each tool must still carry ≥1 valid provenance span.

### Evidence / provenance validity (all fields / tools)

For every evidence provenance object:

1. Resolve field text: `title` → title; `body` → content; `comment` → that comment’s body via `comment_id`.
2. Require `0 <= start < end <= len(field_text)` (Unicode code points).
3. Require `comment_id` present and found when `field` is `comment`; require `comment_id` null otherwise.
4. Non-null text values and every tool must have `len(evidence) >= 1`.

| Metric | Gate |
|--------|------|
| Share of evidence spans that slice validly into the named field | **≥ 95%** |

### Schema validity

| Metric | Gate |
|--------|------|
| Outputs parsing against `extraction.json` after host fills `meta` | **100%** |

## Aggregate gates (must all pass)

Copied from [product.md](product.md):

| Gate | Threshold |
|------|-----------|
| Field-level accuracy on non-null gold text fields | **≥ 80%** |
| Evidence validity | **≥ 95%** |
| False invention rate (docs with any invented buyer/budget/tool) | **≤ 5%** of docs |
| Schema validity | **100%** |
| Tool mention F1 | **≥ 0.80** |

## Process

1. Freeze fixtures + gold.
2. Run extract with fixed `prompt_version` + model id; record both in the eval report.
3. Compute metrics; write `eval_report.md` (gitignored or committed under `tests/reports/` — team choice at impl time).
4. Fail the gate → fix prompt/schema/normalizer, do **not** expand product scope.
5. Pass the gate → allowed to scale Reddit ingest and plan Phase 5+.

`EvaluationRunner` computes JSON validity, precision, recall, field-level
accuracy, missing values, and hallucinated values. `MarkdownReport` emits the
aggregate, per-field, and per-case results without a dashboard.

## Non-goals for V1 eval

- Measuring clustering or opportunity-analysis quality
- Online A/B on production traffic
- Claiming human-level interview quality
