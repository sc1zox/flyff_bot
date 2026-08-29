---
id: BUG-038
title: Player-stats profiler fails closed on the shipped neuz.exe wrapped vital-ratio helpers
status: reported
severity: high
created: 2026-08-29
updated: 2026-08-29
---

# BUG-038: Player-stats profiler fails closed on the shipped neuz.exe wrapped vital-ratio helpers

## Environment

- Windows version: Windows 11 Pro 26200
- Python version: 3.14 (`.python-version`)
- Application revision: `main` after `a80adae`, with the client-profiling / dungeon-container / setup-wizard migration applied
- Client/server version: Entropia Flyff PServer, `Entropia/Entropia/bin64/neuz.exe`, SHA-256 `8079c88f4c4e35a0b5acd117995125bee528c175d5b621e0533d85a4458dada5`

## Reproduction

1. Run the binary profiler against the shipped x64 client:
   `ClientBinaryProfiler().profile(Path("Entropia/Entropia/bin64/neuz.exe"))`
2. Observe it raises `ClientProfilingError(ClientProfilingErrorCode.INCOMPLETE_PLAYER_STATS,
   "A vital helper does not directly expose a bounded numerator/denominator pair.")`
   from `analyze_ratio_function` via `_discover_player_stats`.
3. Separately, load the committed profile document:
   `load_client_player_stats_profiles(Path("data/config/client_player_stats_profiles.json"))`
4. Observe it raises `ValueError` ("The hp field must be a proven ratio, not a raw value.") because
   the committed document still uses the pre-ratio `offset`/`type` field schema.

## Expected behavior

- The profiler produces a `GeneratedClientProfileBundle` for the shipped client: position, camera,
  dungeon, monster-kills, level and experience are all statically evidenced and must not be lost
  because the vital helpers changed shape (US-089).
- When a vital percentage cannot be statically proven, the profile omits it rather than guessing;
  the live player-stats source stays healthy for what it does provide, and vital percentages fall
  back to the HUD reader (`PlayerVitalsReader`) without a permanent readiness gate
  (ADR-010, US-076 degradation contract).
- The committed `client_player_stats_profiles.json` loads under the current schema.

## Actual behavior

The shipped build wraps HP/MP/FP in two-call helpers:

- Each wrapper calls `callee[0]` (guarded `!= 0`, the maximum/denominator), then `callee[1]`
  (the current value/numerator), then combines them MulDiv-style with `edx = 100` as the scale.
- MP `callee[1]` is `movsxd rax,[rax+0x12FC]; ret`; FP `callee[1]` is `movsxd rax,[rax+0x1300]; ret`
  — the current values are clean fixed player-struct offsets.
- MP/FP `callee[0]` (maximum) loads a float constant and calls a generic attribute resolver
  (`sub_849d40`, keyed by attribute-id immediates such as `0x24`, `0x35`): the maximum is computed
  at runtime from base stat + equipment + buffs and is **not** stored at a fixed offset.
- HP resolves both current and maximum through further call chains
  (`sub_8493a0` / `sub_849320`) with no single fixed offset.
- A byte scan of the whole getter chain finds no write-back of the computed maximum to any object
  field, so no denominator offset can be recovered by static analysis either.

`analyze_ratio_function` only decodes the old self-contained
`mov eax,[rcx+disp32]; imul eax,eax,100; cdq; idiv [rcx+disp32]; ret` shape, and
`_discover_player_stats` treats any shortfall as a fatal bundle error, so the entire generated
bundle (including position, camera and dungeon) is discarded.

## Impact and frequency

- Impact: automated memory profiling is unusable for the current shipped client; the setup wizard
  cannot install a generated profile bundle, so live GPS, camera and dungeon readers stay
  unconfigured. Player vitals from client memory are unavailable for this build regardless.
- Frequency: every profiler run against `8079c88f…dada5` (100%).

## Regression verification

- [ ] A failing automated test or deterministic manual check exists
      (`tests/unit/test_client_profiling.py`: synthetic PE with the wrapped vital-ratio shape;
      `tests/unit/test_player_stats_reader.py`: profile without vital fields loads).
- [ ] The check passes after the fix.
- [ ] Related documentation is current (ADR-010; US-089 and US-092 notes).
