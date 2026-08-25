---
id: BUG-033
title: Unified setup does not ingest or autoload the client data it reports
status: reported
severity: critical
created: 2026-08-26
updated: 2026-08-26
---

# BUG-033: Unified setup does not ingest or autoload the client data it reports

## Environment

- Windows version: Windows 11 Pro 10.0.26200
- Python version: Python 3.14.7 (`uv` environment)
- Application revision: `bd2cde2` on `main`
- Client/server version: Entropia Flyff PServer x64 (`neuz.exe`), SHA-256
  `8079c88f4c4e35a0b5acd117995125bee528c175d5b621e0533d85a4458dada5`

## Reproduction

1. Start from the current checkout and call `MainWindow.is_first_run_setup_required()`. The result
   is true because `data/dungeons/dungeons.json` and
   `data/config/client_player_stats_profiles.json` are absent.
2. Trace the supported desktop startup in `ui/app.py::run_desktop`. It constructs and shows the
   dashboard but never calls the first-run detector or opens the setup wizard automatically.
3. Inspect `UnifiedClientExtractor._run_mover_stage`. It only checks whether `propMover.txt`,
   `PropMoverEx.inc`, and `Spec_Item.txt` exist and increments summary counters. It parses no row
   and writes no mover, drop, or item dataset. `propSkill.txt` and `propSkillAdd.csv` are not part of
   the stage at all.
4. Inspect the remaining stages. No dataset manifest is generated, no NavMesh is baked, no portable
   mover/item/skill/NPC catalog is written, and the memory-profile stage only copies an externally
   supplied proven profile. It cannot generate the exact offsets promised by US-078 and correctly
   has no registry entry to copy for this client.
5. Read the real client archives through the existing read-only keyed-archive adapter. The current
   client exposes approximately 1.29 MB of mover data, 1.86 MB of drop declarations, 0.52 MB of
   skill rows, 0.37 MB of skill additions, 28.6 MB of item rows, 1.03 MB of NPC declarations, and
   4.09 MB of quest declarations. The setup stage reports file presence while leaving these rows
   unavailable to runtime consumers.
6. Compare the client and generated artifacts. Sixteen world directories are discoverable by the
   current extractor, but only `wdaurania.json` and `wdeden.json` are present under
   `data/navigation/worlds/`; no baked `*.navmesh.json` artifact is present. The quest database has
   1,434 entries, while the dungeon database, player-stat profile, dataset manifest, and normalized
   gameplay catalogs are absent.
7. Start the desktop composition with the current client. `LivePlayerStatsReader` returns
   `NO_PROFILE`; because the pipeline advertises the reader as configured, the central readiness
   gate makes player stats mandatory for combat and pauses every autonomous action.
8. Run the focused setup and reader tests. All 40 tests pass because they assert file discovery,
   synthetic extraction, and typed failure paths, but they do not assert that the promised real
   datasets are parsed, complete, automatically loaded, or usable by the desktop bot.

## Expected behavior

[US-078](../user-stories/completed/US-078-initial-setup-wizard-and-unified-client-data-extraction.md)
requires the first-run desktop workflow to produce and autoload a versioned portable dataset for
worlds, NavMeshes, movers, drops, items, skills, NPCs, quests, dungeons, and every available proven
memory profile.

- First-run detection must be invoked by the supported desktop startup, and Start must remain
  explicitly unavailable until every mandatory artifact is either valid or acknowledged as an
  unsupported capability.
- A setup stage may report an extracted count only for records actually parsed, validated, written,
  and reloadable through a production consumer. Finding a filename is not ingestion.
- Every generated artifact must appear in one manifest with schema version, relative path, record
  count, source client digest, content digest, diagnostics, completeness state, and UTC timestamp.
- World extraction must cover every supported discoverable region and bake the navigation artifact
  required for YOLO-to-world unprojection and route planning, or record a typed per-world failure.
- Player-stat, world-ID, camera, position, and dungeon profiles may be installed only from proven
  exact-fingerprint registries. Missing proof must remain a visible incomplete capability; setup
  must never infer or fabricate an offset.
- After successful setup, desktop and CLI composition roots must load the same manifest-selected
  artifacts rather than relying on unrelated hard-coded defaults or manual dialog state.

## Actual behavior

The desktop never invokes its first-run detector. The setup workflow counts several packed files
without parsing them, omits the skill tables, writes no mover/drop/item/skill catalog or manifest,
does not bake NavMeshes, and cannot supply the profile that its own first-run completeness check
requires. The repository therefore contains a partially extracted dataset that is presented by
completed documentation as unified and portable, while the normal desktop session has neither the
authoritative static features nor the live player-stat profile needed to leave readiness pause.

## Impact and frequency

- Impact: Critical. The supported desktop can remain permanently action-blocked, while a positive
  setup summary can conceal that most authoritative gameplay data is not available to navigation,
  targeting, telemetry, or learning. Policies trained from the remaining subset cannot represent
  the promised client state.
- Frequency: Deterministic on the reviewed checkout and current exact-fingerprint client. The
  missing autostart, presence-only counters, omitted outputs, and absent profile occur on every run.

## Regression verification

- [ ] A desktop integration test starts with missing required artifacts and proves that the setup
  wizard opens automatically before autonomous Start can be armed.
- [ ] Fixture archives containing movers, drops, skills, items, NPCs, quests, dungeons, and worlds
  produce normalized, schema-versioned datasets whose parsed record counts and content are asserted;
  presence-only counters cannot satisfy the test.
- [ ] A manifest round-trip test verifies every artifact path, schema, count, client/content digest,
  completeness state, warning, and timestamp, and rejects a missing or stale artifact.
- [ ] Multi-world extraction proves every supported discovered world is either saved and NavMesh
  baked or listed with a typed failure; setup cannot report complete with only a silent subset.
- [ ] Missing proven memory offsets leave the relevant capability explicitly unsupported without
  inventing a profile, while a matching proven registry entry installs and reloads successfully.
- [ ] Desktop and CLI composition tests load the same manifest-selected artifacts and expose a clear
  localized reason when mandatory data prevents autonomous operation.
- [ ] The completed status and architecture claims of US-063, US-076, and US-078 are reconciled with
  the verified implementation and outstanding live validation.
- [ ] German and English diagnostics remain synchronized, `./scripts/check.ps1` passes, and a clean
  checkout stays clean after the extraction tests.
