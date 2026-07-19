# SignalMine — product one-pager

## What is the output?

Not startup ideas.

> **A structured market intelligence database built from unstructured internet discussions.**

V1 proves one atomic capability:

> Take a Reddit post (including top comments) and convert it into validated structured JSON grounded in evidence from the source text.

Everything else (search, clustering, dashboards, opportunity scores) builds on that.

## Who is it for?

**Primary ICP (V1):** builders and operators researching B2B problems in **DevOps, cloud infrastructure, and security operations** — founders, PMs, and solutions engineers who need evidence of real pain, not brainstormed ideas.

**Secondary (later):** market researchers and product teams who want queryable complaint corpora with provenance.

## What problem does it solve?

Public forums contain high-signal complaints, workarounds, and tool mentions — but they are unstructured, noisy, and hard to compare. SignalMine turns those threads into **queryable, versioned records** with explicit evidence links back to source text.

## V1 scope (in)

- Reddit as the only live source
- Normalize into one document schema
- LLM extraction into the pain-intelligence schema (Instructor / structured JSON)
- Persist raw → normalized → extraction in PostgreSQL
- Hand-labeled eval set as the quality gate

## V1 scope (out)

- Authentication, payments, multi-tenant SaaS
- Dashboards, search UI, trend charts
- Embeddings, clustering, opportunity analysis
- GitHub Issues / Hacker News ingestion (planned later; normalized schema is platform-agnostic)
- Async workers at scale (Celery/Temporal deferred until sync CLI works)

## Success metric (V1)

On a fixed eval set of **30–50** hand-labeled Reddit threads in the DevOps/security vertical:

| Gate | Threshold |
|------|-----------|
| Field-level accuracy (non-null gold fields) | **≥ 80%** exact-or-acceptable match per [eval.md](eval.md) |
| Evidence / provenance validity (spans slice correctly into named fields) | **≥ 95%** of non-empty evidence spans |
| False invention rate (model invents buyer/budget/tools with no support) | **≤ 5%** of docs |
| Schema validity | **100%** of outputs parse against `schemas/extraction.json` |

Pipeline is “reliable enough” only when all gates pass on a frozen eval snapshot. Do not scale ingest or add Phase 5+ features before that.

## Non-goals (product)

- Generating startup pitches or “idea of the day”
- Replacing customer interviews
- Claiming market size or TAM from Reddit alone
- Treating model speculation as fact when evidence is missing

## One-line positioning

**SignalMine turns forum threads into structured, evidence-backed market signals.**
