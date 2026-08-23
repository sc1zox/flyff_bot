# Entropia Wiki access and page inventory

- Origin: user request to document the official Entropia client wiki as domain knowledge
- Captured: 2026-08-23
- Language: English
- Website: `https://wiki.entropia.top/`
- Mutability: immutable

## Summary

The official Entropia Wiki is hosted on GitBook and exposes an agent-friendly Markdown index at
`https://wiki.entropia.top/llms.txt`. Normal page URLs accept `.md`, which returns the page as
Markdown rather than the rendered HTML application.

A same-day snapshot was taken from `https://wiki.entropia.top/sitemap-pages.xml`. The resulting
[page inventory CSV](2026-08-23-entropia-wiki-page-inventory.csv) records 260 advertised URLs,
sitemap modification timestamps, and H1 titles where retrieval succeeded. Four pages are marked
`sitemap-only`; they remain locatable but their headers were unavailable during the first snapshot.
The inventory is deliberately an index, not a copy of copyrighted wiki prose.
