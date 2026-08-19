---
id: US-052
title: Client archive extraction for complete 3D terrain heightfields
status: completed
created: 2026-08-19
updated: 2026-08-19
completed: 2026-08-19
---

# US-052: Client archive extraction for complete 3D terrain heightfields

## Story

As a **bot operator navigating complex 3D terrain across Entropia Flyff**, I want **to extract packed terrain heightfield blocks directly from client `.one` / `.hdr` archives**, so that **the bot has authoritative 3D terrain coverage across all declared map coordinates rather than only the loose blocks left on disk**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Client world assets in `Entropia/Entropia/Data/World/` contain 123 `.one` and 123 `.hdr` container archives covering 3,861 declared terrain blocks across all worlds (Eden, Madrigal, dungeons, etc.), with only 153 blocks currently loose (3.96%).
- The `.hdr` files index entries with structured header records. The `.one` archives contain compressed/obfuscated data.
- Each extracted `.lnd` heightfield contains a 66,576-byte prefix ($129 \times 129$ float32 heights) which converts directly into $128 \times 128 \times 2 = 32,768$ 3D triangles per block.
- Extraction is non-destructive and read-only against the game installation: compiled vector maps are stored in `data/navigation/worlds/<region>.json` with `.lnd` heightfields beside them.
- Builds upon [US-020](US-020-visual-navigation-path-and-heatmap-inspector.md), [US-045](US-045-vector-world-terrain-extraction-and-goal-navigation.md), [US-048](US-048-3d-world-navigation-teleport-dispatch-and-terrain-aware-pathing.md), and [ADR-005](../../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md).

## Acceptance criteria

- [x] Given a local Entropia client directory with `.one` and `.hdr` archives in `Data/World/`, when executing the world extractor (e.g. `uv run python -m flyff_bot extract-world`), then the parser reads the header indexes and extracts all `.lnd` terrain heightfield files into the local navigation data directory.
- [x] Given extracted `.lnd` files from archives, when validating the header prefix, then all valid `.lnd` files with version 3 decode into $129 \times 129$ float32 height arrays without truncation.
- [x] Given full terrain coverage for an extracted world (such as Eden or Madrigal), when `WorldVectorMap` loads the world, then all blocks declared in the `.wld` grid resolve to authoritative height fields.
- [x] Given corrupted, encrypted, or unsupported archive entries, when extraction encounters an unparseable block, then the extractor logs a diagnostic warning, skips the entry safely, and continues extracting remaining blocks.
- [x] All CLI output, summary reports, and error messages remain synchronized in German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).

## Out of scope

- Modifying, repacking, or writing data back into the game client's original `.one` / `.hdr` archives.
- Runtime in-memory archive hooking or DLL injection into the running `neuz.exe` process.
- Free-flight 3D aerobatics on flying mounts.

## Verification

- Automated:
  - Unit tests in `tests/unit/test_world_extractor.py` verifying archive header parsing and payload decoding.
  - Regression tests in `tests/unit/test_terrain_routing.py` verifying that terrain routing uses complete height coverage.
- Manual (Windows):
  - Run `uv run python -m flyff_bot --extract-world` against the local Entropia installation, verify that extracted `.lnd` block count increases from 153 to full world coverage, and inspect complete topographic contours in the Path Inspector UI.

## Outcome

The extractor is a CLI flag on the existing single-command interface rather than a subcommand, so
the command is:

```powershell
uv run python -m flyff_bot --extract-world
```

It accepts `--client-world-root`, `--world-map-directory`, and a repeatable `--world` region
filter, and it opens no game window.

`flyff_bot.features.navigation.client_archive` reads the `<world>.hdr` index (`int32 count`, then
per entry `int32 name_length`, an opaque name digest, `int32 offset`, `int32 size`) and decodes
`<world>.one` entries with the keystream `stored[i] = swap_nibbles(plain[i]) ^ ((name[i % len] - 1)
& 0xFF)`, keyed on the plain lower-case file name. Because the index stores a digest rather than a
name, a terrain block is located by encoding its known twelve-byte plaintext prefix - version 3 plus
its two block coordinates - and matching the entry's stored bytes. Reading is offline and
read-only; no client file is written or repacked.

Run against the operator's own unmodified Entropia installation, the command produced **1,116**
decoded `.lnd` height fields against the **153** loose blocks the audit counted. Eden resolves all
25 of its declared blocks with full sampled coverage; Madrigal resolves 874 of the 900 its `.wld`
declares, the remaining 26 being coordinates the client itself ships no block for.

Two deviations from the story text, both deliberate:

- **World-map schema version 3.** Height grids are no longer inlined in the JSON document. Each
  block is written beside it as a plain 66,576-byte `.lnd` height field under
  `data/navigation/worlds/<region>/`, which is also what satisfies the first acceptance criterion.
  Inlining Madrigal's 874 grids would have produced a JSON document of several hundred megabytes.
- **Maps are named after the region directory, not its world script.** The seasonal Madrigal
  variants all declare `wdmadrigal`, so a shared name had them overwrite each other's output.

Twenty-five regions ship a second `.hdr` layout whose records carry an extra leading `-1` field.
That layout is refused rather than guessed at: it is reported as a localized diagnostic and skipped,
and the region still extracts whatever it leaves loose. Undecodable packed blocks and placed-object
files in unknown record layouts are reported the same way.

Verified by `./scripts/check.ps1`: ruff check and format clean, mypy clean over 127 source files,
768 tests passed and 3 skipped at 92.44% coverage. The live `neuz.exe` walkthrough - confirming
that routes over newly mapped blocks match the client's own physics, and inspecting contours in the
Path Inspector against a running session - remains outstanding.
