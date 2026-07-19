# Design decisions (Phase 0)

Locked for V1 design. Revisit only with an explicit product decision.

## Product name

**SignalMine**

Rationale: describes the system as a data platform that turns scattered discussion signals into structured evidence. Avoids idea-generator / GPT framing.

Directory name `painminingengine` is legacy; rename the repo when implementation starts.

## V1 vertical focus

**DevOps, cloud infrastructure, and security operations**

Seed topics for ingest and eval (not an exhaustive taxonomy):

- IAM / access control
- Secrets management
- Certificate rotation
- Infrastructure-as-code drift (e.g. Terraform)
- Compliance workflows (e.g. SOC2)
- Vendor / tool sprawl in the ops stack

Rationale: a narrow vertical sharpens the extraction schema, prompt examples, and hand-labeled eval set. Schema fields stay general enough to expand later; source selection and eval labeling stay vertical-first.

## Design artifacts

**Markdown docs + JSON Schema contracts only**

No Python package stubs, FastAPI app, or frontend in Phase 0. Implementation begins only after these contracts are signed off.

## Provenance (day one)

Every non-null extracted claim carries **span-level provenance**, not free-floating quote strings:

```json
{
  "source": "reddit",
  "field": "body",
  "comment_id": null,
  "character_range": [142, 286],
  "confidence": 0.94
}
```

- `character_range` is a half-open `[start, end)` into the referenced field text (Unicode code points).
- `field` is `title` | `body` | `comment` (`body` = normalized `content`).
- Host **rejects** extractions whose spans do not slice cleanly to the named field.
- Primary extraction field for the core pain claim is `pain_summary`.

Rationale: trust is the product. Traceability enables review, debugging, and later model improvement.

## Deferred (explicit non-goals for Phase 0 / week-1 milestone)

- Embeddings / pgvector
- Clustering
- Opportunity-analysis LLM over clusters
- Dashboard / search UI
- Auth, billing, multi-tenant
- GitHub Issues / Hacker News ingest (schema leaves room; code does not)
- Celery / Temporal (sync CLI first)

