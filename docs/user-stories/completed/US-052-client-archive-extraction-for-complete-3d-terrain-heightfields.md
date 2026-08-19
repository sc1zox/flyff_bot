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

As a **bot operator navigating complex 3D worlds across Entropia Flyff**, I want **an offline extraction capability that unpacks the client's `.one` / `.hdr` data archives and decodes all contained `.lnd` terrain heightfields**, so that **the 3D A\* path planner has 100% of the world's elevation data available instead of relying on flat-terrain approximations for the 96% of unextracted archive blocks**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Evidence from [2026-08-19 extraction audit](../sources/2026-08-19-entropia-client-navigation-data-extraction.md): The client contains 123 `.one` and 123 `.hdr` archive pairs covering 3,861 declared terrain blocks in `Data/World/`, but only 153 blocks (3.96%) exist as loose `.lnd` files.
- Flyff `.one` / `.hdr` archives package client assets with an index header (`.hdr`) and compressed data payload (`.one`) using Flyff container structures.
- Decoded `.lnd` files follow the verified 66,576-byte heightfield prefix (version 3, block coordinates, $129 \times 129$ float32 heights) established in [US-045](completed/US-045-vector-world-terrain-extraction-and-goal-navigation.md) and [US-048](completed/US-048-3d-world-navigation-teleport-dispatch-and-terrain-aware-pathing.md).
- Extraction is strictly offline and non-destructive: client game files are read-only and never modified; extracted `.lnd` files are output to `data/navigation/worlds/`.

## Acceptance criteria

- [x] Given a local Entropia client directory with `.one` and `.hdr` archives in `Data/World/`, when executing the world extractor (e.g. `uv run python -m flyff_bot extract-world`), then the parser reads the header indexes and extracts all `.lnd` terrain heightfield files into the local navigation data directory.
- [x] Given extracted `.lnd` files from archives, when validating the header prefix, then all valid `.lnd` files with version 3 decode into $129 \times 129$ float32 height arrays without truncation.
- [x] Given full terrain coverage for an extracted world (such as Eden or Madrigal), when `WorldVectorMap` loads the world, then all blocks declared in the `.wld` grid resolve to authoritative height fields.
- [x] Given corrupted, encrypted, or unsupported archive entries, when extraction encounters an unparseable block, then the extractor logs a diagnostic warning, skips the entry safely, and continues extracting remaining blocks.
- [x] All CLI output, summary reports, and error messages remain synchronized in German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).

## Out of scope

- Modifying, repacking, or writing data back into the game client's `.one` / `.hdr` archives.
- Dynamic in-memory archive interception or runtime DLL hooking.
- 3D mesh physics collision parsing beyond heightfield elevations.

## Verification

- Automated:
  - Unit tests in `tests/unit/test_world_extractor.py` verifying archive header parsing, container decompression, and `.lnd` height field decoding.
  - Regression tests in `tests/unit/test_terrain_routing.py` verifying that 3D A* utilizes extracted archive heightfields.
- Manual (Windows):
  - Run `uv run python -m flyff_bot extract-world` against the local Entropia installation, verify that extracted `.lnd` block count increases from 153 to full world coverage, and inspect complete topographic contours in the Path Inspector UI.

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
