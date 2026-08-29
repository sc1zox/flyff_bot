---
id: BUG-038
title: Player-stats profiler fails closed on the shipped neuz.exe wrapped vital-ratio helpers
status: in-progress
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

## Fix progress

`b665490` (`feat(client_profiling): complete player-stats discovery for neuz.exe 8079c88f`)
resolves the player-stats half of this defect:

- `_discover_player_stats` no longer fails closed on the wrapped helper shape. Three narrow
  decoders were added, each verified against the shipped binary:
  - `analyze_hp_xor_pair` follows the HP current getter through its adder (`add rax, disp32`)
    into the XOR decoder and recovers offset `+0x1304` plus both 64-bit keys
    (`0x5A3C9E17C4D2F8B1` / `0x2D74B1C9A6E03F5D`).
  - `_discover_level_experience` locates the experience-gauge wrapper (the gauge call not
    preceded by `mov edx, 100`) and reads its two fixed-member getters -> `level` i32 @
    `+0x12C0`, `experience` u64 @ `+0x12C8`.
  - `_member_load_evidence` decodes `mov rax,[rsp+8]; mov (r|e)ax,[rax+disp32]`.
- When a vital maximum is computed at runtime the current value is emitted under a distinct
  name (`current_hp` / `current_mp` / `current_fp`, MP @ `+0x12FC`, FP @ `+0x1300`) so a raw
  current is never mistaken for a 0..100 percentage (ADR-010).
- The perception pipeline reads vital percentages from the HUD reader whenever a client-memory
  snapshot carries no `hp`/`mp`/`fp` ratio; orchestrator `PLAYER_STATS` readiness is now
  profile-driven (healthy unless a declared field failed the poll).
- `data/config/client_player_stats_profiles.json` is regenerated to the current schema
  (`current_hp`/`mp`/`fp`, `level`, `experience`, `monster_kills_rva`) and loads again.

`./scripts/check.ps1` green: 1279 passed, 4 skipped, coverage 88.5%.

## Remaining follow-up

Both items are accepted as open in
[ADR-010](../decisions/ADR-010-client-derived-vital-maxima-are-not-runtime-resolvable.md).

1. **Dungeon-container decoder for this build.** `_discover_dungeon` still raises
   `ClientProfilingError(ClientProfilingErrorCode.INCOMPLETE_DUNGEON, …)` for `8079c88f…dada5`,
   so `ClientBinaryProfiler.profile()` does not yet run end-to-end — only `_discover_player_stats`
   is proven for this client (it runs before `_discover_dungeon` in `profile()`). The
   shipped `data/config/client_dungeon_profiles.json` already carries a valid hand-verified
   fixed-value profile for this digest (`kind` `fixed_array`, `record_count` 32,
   `record_size_bytes` 48; `dungeon_id` / `cooldown_end_timestamp` / `entries_used` /
   `daily_entry_limit` at `+0` / `+16` / `+24` / `+28`), so the live dungeon reader is
   configured; the profiler simply cannot regenerate it yet.
2. **Memory path for the vital percentages (`CWndStatus` gauge floats).** Vital percentages
   keep coming from the visual HUD reader (`PlayerVitalsReader`), accepted per ADR-010. The
   candidate bounded read for a later implementation is the five gauge fill ratios on
   `CWndStatus`: `CWndStatus + {0x2168, 0x2194, 0x21C0, 0x21EC, 0x2218} + 0x28` (each a 0..1
   float). Recorded here for the eventual `RatioPlayerStatSource` / dedicated gauge source; not
   yet wired.

## Regression verification

- [x] A failing automated test or deterministic manual check exists
      (`tests/unit/test_client_profiling.py`: synthetic PEs for the wrapped vital-ratio decoder,
      the XOR-pair HP decoder and fixed-member level/experience discovery;
      `tests/unit/test_player_stats_reader.py`: `XorPairPlayerStatSource` and a
      `current_<vital>` profile load and decode).
- [x] The check passes after the fix (`b665490`, `./scripts/check.ps1` green).
- [x] Related documentation is current (ADR-010 updated in `b665490`; this file; US-089 and
      US-092 unaffected).

Not yet closed: `ClientBinaryProfiler.profile()` cannot regenerate the full bundle until
follow-up 1 (the dungeon-container decoder) lands, so `status` stays `in-progress`.
