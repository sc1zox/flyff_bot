---
id: BUG-038
title: Player-stats profiler fails closed on the shipped neuz.exe wrapped vital-ratio helpers
status: resolved
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

## Dungeon-container decoder (resolved via ADR-011)

Ghidra 12.1 decompilation of the shipped `8079c88f…dada5` client established that the
committed `fixed_array` dungeon profile (`record_size_bytes` 48, `record_count` 32, fields
`0/16/24/28`) was fabricated — it matched nothing in the binary and a live read against it
would have mis-parsed 1536 bytes of unrelated player-object memory. Per-dungeon cooldown rows
exist only in transient `std::vector` members owned by the `CWndDungeonCooldownList` /
`CWndDungeonCooldownQuick` windows, with no fingerprint anchor.

The one persistent bounded read the dungeon UI performs is the account-wide daily lockout
`__time64_t` at `player + 0x2678` (`now < *(player + 0x2678)` -> "Locked until 03:00 AM UTC+2").
The fix binds exactly that
([ADR-011](../decisions/ADR-011-dungeon-cooldowns-are-not-fingerprint-bindable-only-the-account-lockout-is.md)):

- `DungeonContainerKind.GLOBAL_LOCKOUT_TIMESTAMP` / `GlobalDungeonLockout(offset)`;
  `ClientDungeonProfile.fields` is now optional (`None` for the lockout kind). The two
  contiguous container kinds and their decoders are retained for a future build.
- `_discover_dungeon` scans the two cooldown-window vtables for
  `mov rcx,[rip+player]; call <helper>` where the helper is the fixed shape
  `mov rax,[rsp+x]; mov r64,[rax+disp32]; lea rcx,[rsp+y]; call` — one bounded 8-byte `this`
  member handed to a time constructor — and requires a unique `(player_global_rva, offset)`.
  The unverified `analyze_dungeon_span_function` / `_four_record_field_offsets` speculative
  begin/end decoder is deleted.
- `LiveDungeonCooldownReader` reads one fixed pointer plus one bounded 8-byte value; while the
  lockout is active it maps that end time onto every known dungeon (`ON_COOLDOWN`, shared
  remaining), and reports `UNKNOWN` for all of them when it is zero or past rather than an
  invented `READY`.
- `data/config/client_dungeon_profiles.json` is replaced with the
  `global_lockout_timestamp` entry (`runtime_state_pointer_rva 12042024`,
  `lockout_timestamp_offset 9848`).

`ClientBinaryProfiler.profile()` now runs end-to-end for `8079c88f…dada5` (position,
player-stats, camera, dungeon).

## Remaining follow-up

**Memory path for the vital percentages (`CWndStatus` gauge floats).** Resolved —
closed as not implementable within
[ADR-006](../decisions/ADR-006-read-only-process-memory-access.md) by
[US-094](../user-stories/completed/US-094-cwndstatus-gauge-vital-memory-path.md), with the
[ADR-010 update](../decisions/ADR-010-client-derived-vital-maxima-are-not-runtime-resolvable.md)
and [static-analysis source](../sources/2026-08-29-entropia-cwndstatus-and-player-position-static-analysis.md).
The five gauges are real inline `CWndGauge` members at
`CWndStatus + {0x2168, 0x2194, 0x21C0, 0x21EC, 0x2218} + 0x28`, but that float is a **0..100**
value (not 0..1 as first recorded) and there is **no fingerprint-stable anchor to the
`CWndStatus` instance** — so it is not a bounded read. Vital percentages keep coming from
`PlayerVitalsReader`.

**Generated position offset.** During the same analysis the `position` half of the generated
bundle for `8079c88f…` was found to be a byte-match false positive (`184` where the verified
offset is `0x188`), installed verbatim by the setup wizard's `persist_profile_bundle` call. The
"position … statically evidenced" and "completes end to end" statements above overstate the
position result; they hold for camera / dungeon / player-stats. [BUG-039](BUG-039-generated-position-offset-false-positive-and-empty-position-world-id-registries.md)
is resolved: the x64 profile is now explicit committed configuration, world ID remains
typed-unavailable from its intentionally empty registry, and the focused regression passed. Its
canonical repository gate was attempted but did not complete because of an unrelated pre-existing
Ruff E501; this note makes no claim that BUG-039 has a green canonical gate.

## Regression verification

- [x] A failing automated test or deterministic manual check exists
      (`tests/unit/test_client_profiling.py`: synthetic PEs for the wrapped vital-ratio decoder,
      the XOR-pair HP decoder, fixed-member level/experience discovery, `analyze_dungeon_lockout_helper`
      accept/reject cases, and `_discover_dungeon` proving `GlobalDungeonLockout` from a synthetic
      cooldown-window vtable; `tests/unit/test_player_stats_reader.py`: `XorPairPlayerStatSource` and a
      `current_<vital>` profile load and decode; `tests/unit/test_live_dungeon_reader.py`: the account
      lockout mapped onto every dungeon while active and `UNKNOWN` for a cleared timestamp).
- [x] The check passes after the fix (`./scripts/check.ps1` green: 1285 passed, 4 skipped,
      coverage 88.7%).
- [x] Related documentation is current (ADR-010 for the vital half; ADR-011 for the dungeon half;
      `docs/wiki/architecture.md` dungeon section; this file; US-089 and US-092 unaffected).

`ClientBinaryProfiler.profile()` now regenerates the full bundle (position, player-stats, camera,
dungeon) for `8079c88f…dada5`.
