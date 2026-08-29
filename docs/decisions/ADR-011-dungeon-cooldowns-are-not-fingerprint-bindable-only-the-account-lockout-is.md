# ADR-011: Per-dungeon cooldowns are not fingerprint-bindable; only the account lockout timestamp is a bounded read

- Status: accepted
- Date: 2026-08-29
- Related stories: [US-063](../user-stories/completed/US-063-client-dungeon-data-and-live-cooldown-memory-extraction.md), [US-089](../user-stories/US-089-automated-client-binary-reverse-engineering-and-memory-profiling.md)
- Related decisions: [ADR-006](ADR-006-read-only-process-memory-access.md), [ADR-003](ADR-003-clean-schema-over-backward-compatibility.md), [ADR-010](ADR-010-client-derived-vital-maxima-are-not-runtime-resolvable.md)
- Related bugs: [BUG-038](../bugs/fixed/BUG-038-player-stats-profiler-fails-closed-on-wrapped-vital-ratio-helpers.md)
- Supersedes: none

## Context

US-063 specified `client_dungeon_profiles.json` as a per-build fingerprint selecting a bounded
contiguous container of per-dungeon cooldown records (`fixed_array` or `begin_end_span`) plus four
record field offsets. The shipped file was left empty; `_discover_dungeon` in the automated
profiler ([US-089](../user-stories/US-089-automated-client-binary-reverse-engineering-and-memory-profiling.md))
only decoded the `begin_end_span` shape and had no verified target.

Reverse engineering the shipped Entropia client
`8079c88f4c4e35a0b5acd117995125bee528c175d5b621e0533d85a4458dada5` (Ghidra 12.1 decompilation of the
`CWndDungeonCooldownList` / `CWndDungeonCooldownQuick` render methods) establishes:

- Per-dungeon cooldown rows exist only in **transient `std::vector<Record>` members owned by the
  cooldown UI windows** (`CWndDungeonCooldownQuick` at `this+0x1FE8`, `CWndDungeonCooldownList` at
  `*(this+0x48)+0x1FF0`; `sizeof(Record) == 0x1C`). The vector starts empty ("Refreshing..") and is
  filled asynchronously while a cooldown window is open. There is no fixed global holding these
  records, so no SHA-256-fingerprinted address can bind to them under
  [ADR-006](ADR-006-read-only-process-memory-access.md).
- The one bounded read the dungeon UI itself performs against persistent memory is
  `now < *(player + 0x2678)`: `player + 0x2678` is an `ATL::CTime` (`__time64_t`, Unix seconds UTC)
  holding the **account-wide daily dungeon lockout end** ("Locked until 03:00 AM UTC+2"), zeroed with
  its neighbours by the player-object initialiser. `player` is the widely-used player pointer global
  at RVA `0xB7BF28` (the same object the player-stats profile reaches through `0xB7C948`).
- The previously committed `fixed_array` profile for this digest (`records_offset 0`,
  `record_size_bytes 48`, `record_count 32`, fields `0/16/24/28`) matched nothing in the binary — the
  `48` is the MSVC red-black-tree node size seen in `std::chrono` template glue, not a record — and a
  live read against it would have mis-parsed 1536 bytes of unrelated player-object memory.

## Decision

1. The dungeon profiler binds only what the cooldown windows demonstrably read from persistent
   memory: the account lockout timestamp. `_discover_dungeon` scans the `CWndDungeonCooldownList`
   and `CWndDungeonCooldownQuick` primary vtables for `mov rcx,[rip+global]; call helper` where the
   helper is the fixed shape `mov rax,[rsp+x]; mov r64,[rax+disp32]; lea rcx,[rsp+y]; call` — a single
   bounded 8-byte `this` member handed straight to a time constructor — and requires exactly one
   `(player_global_rva, offset)` pair. A 32-bit load, an indexed access, or a pointer chase is
   rejected.

2. `DungeonContainerKind` gains `GLOBAL_LOCKOUT_TIMESTAMP` and `GlobalDungeonLockout(offset)`.
   `ClientDungeonProfile.fields` is `None` for that kind; the `0..100`-style per-record validation
   applies only to the two contiguous container kinds, which are retained for a future build that
   exposes one.

3. `LiveDungeonCooldownReader` reads one fixed pointer plus one bounded 8-byte `__time64_t`. While
   the lockout is in the future it maps that one end time onto every known dungeon
   (`DungeonStatus.ON_COOLDOWN`, shared remaining seconds). When the timestamp is zero or past it
   reports `DungeonStatus.UNKNOWN` for every dungeon rather than an invented `READY`, because
   per-dungeon cooldowns are not observable for this build.

4. `data/config/client_dungeon_profiles.json` carries the `global_lockout_timestamp` entry for this
   digest (`runtime_state_pointer_rva 12042024`, `lockout_timestamp_offset 9848`). Per
   [ADR-003](ADR-003-clean-schema-over-backward-compatibility.md) the stale `fixed_array` entry is
   replaced, not shimmed.

## Alternatives

- **Traverse the UI-owned record vector at runtime.** Rejected: the vector has no fingerprint anchor,
  exists only while a specific window instance is open, and reaching it needs that window's `this`
  pointer — runtime pointer chasing outside [ADR-006](ADR-006-read-only-process-memory-access.md).
- **Keep the fabricated `fixed_array` profile.** Rejected: it does not correspond to the binary and
  feeds unverified memory into a reader, exactly the failure [ADR-010](ADR-010-client-derived-vital-maxima-are-not-runtime-resolvable.md)
  and the profiler's own contract forbid.
- **Leave `client_dungeon_profiles.json` empty and report the dungeon feature unconfigured.**
  Rejected: the account lockout timestamp is a genuine bounded read with real scheduling value
  ("daily-capped until reset"), and binding it lets `ClientBinaryProfiler.profile()` run end to end.
- **Report `READY` when no lockout is active.** Rejected: it asserts more than the memory supports;
  a real per-dungeon cooldown would be invisible, so `UNKNOWN` is the honest state.

## Consequences

- `ClientBinaryProfiler.profile()` now completes for `8079c88f…dada5` (position, player-stats,
  camera, dungeon), so the setup wizard can install a full generated bundle.
- The live dungeon feature degrades to a single account-wide signal for this build: every dungeon
  shares the lockout while it is active, and shows `UNKNOWN` otherwise. Per-dungeon cooldown and
  entry-count numbers stay visual-only / unavailable until a client build exposes a fixed container.
- A future build with a real contiguous container needs no schema change — `fixed_array` and
  `begin_end_span` remain in `DungeonContainerKind` with their decoders.

## Verification

- `tests/unit/test_client_profiling.py` covers `analyze_dungeon_lockout_helper` (aligned 64-bit
  member accepted; 32-bit load, unaligned offset, and non-helper rejected) and `_discover_dungeon`
  proving `GlobalDungeonLockout` from a synthetic cooldown-window vtable, plus the persisted
  `global_lockout_timestamp` document round-tripping.
- `tests/unit/test_live_dungeon_reader.py` covers the lockout mapped onto every dungeon while active
  and `UNKNOWN` for a cleared timestamp, each asserting the two bounded reads.
- `./scripts/check.ps1` is green.
