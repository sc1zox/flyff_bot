---
id: US-075
title: Portable one-click static client data extraction
status: draft
created: 2026-08-23
updated: 2026-08-23
---

# US-075: Portable one-click static client data extraction

## Story

As a **bot operator running the extraction workstation separately from the automation PC**, I want **a single dashboard action that reads an explicitly selected Entropia installation and produces one portable structured dataset**, so that **the automation PC can consume complete offline client knowledge without needing access to the game installation**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- The operator selects or enters the installation path; the application must not assume that `Entropia/Entropia/Data` exists on every machine.
- Static file reading is authorized by [ADR-005](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md). The installation remains read-only.
- Existing archive readers already support both `.hdr`/`.one` generations, including name-addressed keyed archives ([US-052](completed/US-052-client-archive-extraction-for-complete-3d-terrain-heightfields.md), [US-061](completed/US-061-client-quest-data-extraction-and-goal-driven-quest-farming.md)).
- This story covers the currently known static tables in addition to existing world/quest outputs. It does not invent semantics for fields whose meaning cannot be verified from the client evidence.
- Optional client-start detection may trigger extraction after the operator enables it; it must never launch, patch, write to, or monitor the client beyond the documented process-existence signal.

## Acceptance criteria

- [ ] Given a valid Entropia installation path, when the operator clicks **Extract Client Data**, then the app runs all static extractors through one bounded background workflow and reports progress without blocking the Qt thread.
- [ ] Given extraction succeeds, when it finishes, then it writes one versioned portable dataset containing:
  - monster properties from `propMover.txt`, including combat stats, movement, resistances, EXP/FXP, killability, and AI references;
  - monster extensions from `PropMoverEx.inc`, including drop items, drop counts, gold ranges, item limits, and verifiable AI structure;
  - skills and skill levels from `propSkill.txt` and `propSkillAdd.csv`, including requirements, ranges, timing, costs, effects, prerequisites, motions, and icons where declared;
  - full item properties and localized text links from `Spec_Item.txt`;
  - crafting, exchange, reward-box, upgrade, set-effect, recycle, Royal/Astral/Anarchy/Guild-buff, progression, title, and pet-related declarations that are present;
  - NPC identities, names, menu actions, shop entries, dialog references, and localized labels from `character.inc` and its catalogs;
  - world geometry, spawn records, object placements, model collision references, and baked NavMesh artifacts for supported regions;
  - quest definitions and their ground bindings using the latest compatible quest schema.
- [ ] Given a table or record cannot be parsed safely, when extraction reaches it, then the extractor records a typed diagnostic with source path/table and continues with unaffected data rather than inventing defaults.
- [ ] Given extraction finishes, when the operator opens the output folder, then it contains a machine-readable manifest with schema versions, source-path-independent relative table names, record counts, warnings, client fingerprint metadata, and UTC timestamps.
- [ ] Given the resulting dataset directory is copied to another PC, when the bot starts there, then it loads the dataset without requiring the original client installation or re-running extraction.
- [ ] Given the selected path is missing, incomplete, or read-only at the filesystem level, when extraction is requested, then the UI shows a localized actionable error before writing partial output.
- [ ] Given optional start-triggered extraction is enabled, when a `neuz.exe` process appears, then extraction runs once per detected installation signature and remains cancellable; disabled by default, it must not run automatically.
- [ ] Failure and cancellation behavior is defined: cancellation stops scheduling new work, preserves completed partial results as clearly incomplete, and leaves the client installation unchanged.
- [ ] All user-visible text is available in German and English.

## Out of scope

- Committing raw client assets, archives, executables, textures, sounds, or proprietary tables to Git.
- Runtime memory reads, packet access, injection, hooks, anti-cheat behavior, or writes to the installation.
- Replacing the separate dungeon-data fix currently in progress.
- Implementing policies or rewards that consume the new dataset; this story only establishes and validates the portable data contract.

## Verification

- Automated:
  - Synthetic client trees cover both archive generations, valid/invalid indexes, keyed-table round trips, world files, O3D collision fixtures, NPC scripts, and malformed rows.
  - Tests assert typed diagnostics, manifest contents, schema validation, cancellation, no client mutation, portable loading from a relocated copy, and German/English message parity.
  - Performance and memory bounds are covered for large synthetic tables so a click does not freeze the UI.
  - `./scripts/check.ps1` passes.
- Manual (Windows):
  - Select the real local installation, run extraction from the dashboard, inspect diagnostics and manifest, cancel mid-run, rerun, and verify no client-file timestamps/content change.
  - Copy the generated dataset to a second Windows PC without the game folder, configure only the dataset path, and confirm the bot loads worlds, quests, monsters, items, skills, NPCs, and economic data.
