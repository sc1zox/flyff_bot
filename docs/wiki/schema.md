# LLM wiki schema

The wiki is a persistent, agent-maintained synthesis between raw evidence and day-to-day questions.
Humans curate sources and review results; the agent performs routine indexing, cross-linking, and
maintenance.

## Layers

1. `docs/sources/` contains immutable raw evidence and is the grounding authority.
2. `docs/wiki/` contains derived, linked Markdown pages maintained by agents.
3. `AGENTS.md` and this file define the maintenance contract.

## Page contract

Every knowledge page except `index.md`, `log.md`, and this schema begins with:

```yaml
---
title: Short descriptive title
status: active
updated: YYYY-MM-DD
sources:
  - ../sources/example.md
related:
  - other-page.md
---
```

- `status` is `draft`, `active`, `review-needed`, or `superseded`.
- Distinguish sourced facts from agent inference. Label inference explicitly.
- A wiki page may help navigation but may not be the sole evidence for a new factual claim.
- Record unresolved contradictions; never silently choose a convenient version.
- Prefer one concept per page and descriptive kebab-case filenames.

## Operations

### Ingest

Read one source, extract durable claims, update affected pages and cross-links, update `index.md`,
then append a dated `ingest` entry to `log.md`.

### Query

Read `index.md` first, then relevant pages and their sources. Cite repository files in the answer.
File a useful synthesis only when it is durable and traceable.

### Lint

Check for broken links, missing index entries, orphan pages, stale claims, contradictions, missing
sources, and German/English UI message drift. Append a `lint` log entry with findings.

