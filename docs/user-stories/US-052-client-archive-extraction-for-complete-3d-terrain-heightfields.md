---
id: US-052
title: Client archive extraction for complete 3D terrain heightfields
status: draft
created: 2026-08-19
updated: 2026-08-19
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

- [ ] Given a local Entropia client directory with `.one` and `.hdr` archives in `Data/World/`, when executing the world extractor (e.g. `uv run python -m flyff_bot extract-world`), then the parser reads the header indexes and extracts all `.lnd` terrain heightfield files into the local navigation data directory.
- [ ] Given extracted `.lnd` files from archives, when validating the header prefix, then all valid `.lnd` files with version 3 decode into $129 \times 129$ float32 height arrays without truncation.
- [ ] Given full terrain coverage for an extracted world (such as Eden or Madrigal), when `WorldVectorMap` loads the world, then all blocks declared in the `.wld` grid resolve to authoritative height fields.
- [ ] Given corrupted, encrypted, or unsupported archive entries, when extraction encounters an unparseable block, then the extractor logs a diagnostic warning, skips the entry safely, and continues extracting remaining blocks.
- [ ] All CLI output, summary reports, and error messages remain synchronized in German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).

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
