# SignalMine project metrics

> Single source of truth for repository engineering metrics.
> Last updated: 2026-11-07
> Regenerate: `pytest --collect-only -q` (from repo root with dev deps installed)

## Summary

| Metric | Value |
|--------|------:|
| pytest tests collected | 125 |
| Canonical JSON schemas (`schemas/`) | 4 |
| Pipeline stages (CLI) | collector → normalizer → extractor → validator |

## Verification

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest --collect-only -q
```

Case study and portfolio copy: [brohammad.tech/projects/signalmine](https://brohammad.tech/projects/signalmine)
