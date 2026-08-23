---
title: Entropia game wiki consultation
status: active
updated: 2026-08-23
sources:
  - ../sources/2026-08-23-entropia-wiki-access-and-page-inventory.md
  - ../sources/2026-08-23-entropia-wiki-page-inventory.csv
related:
  - project-overview.md
  - glossary.md
---

# Entropia game wiki consultation

For domain knowledge about Entropia Flyff gameplay, systems, progression, items, monsters,
dungeons, zones, rates, and server-specific behavior, consult the official Entropia Wiki before
recording or acting on an in-game claim.

## Authoritative source

- Site: [Entropia Wiki](https://wiki.entropia.top/)
- Markdown index: [`llms.txt`](https://wiki.entropia.top/llms.txt)
- Per-page Markdown: append `.md` to a normal page URL (for example,
  [`/server-rates.md`](https://wiki.entropia.top/server-rates.md)).
- Captured inventory: [2026-08-23 Entropia Wiki page inventory](../sources/2026-08-23-entropia-wiki-page-inventory.csv).

## Consultation workflow

1. Search the captured page inventory by title or URL segment to find candidate pages.
2. Retrieve the current `.md` version of each relevant page at answer time; do not infer page body
   content from the inventory alone. Four inventory rows are marked `sitemap-only` because their
   first retrieval did not return a usable H1 header.
3. Record the consulted URL and the wiki page title in durable documentation when a claim affects
   implementation, configuration, or user-facing behavior.
4. Treat the wiki as authoritative for Entropia-specific gameplay facts unless newer evidence from
   the live client or repository sources contradicts it. Record contradictions instead of silently
   choosing one side.

## Inventory snapshot

The CSV was generated from `sitemap-pages.xml` on 2026-08-23. It contains all 260 URLs advertised by
the sitemap, with titles and `lastmod` timestamps. It is an index for locating current pages, not a
copy of their prose: 256 rows include retrieved H1 headers and four are marked `sitemap-only`.
