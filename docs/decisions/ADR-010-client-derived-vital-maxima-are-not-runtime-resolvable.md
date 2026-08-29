# ADR-010: Client-derived vital maxima are not runtime-resolvable; vital percentages are a degradable capability

- Status: accepted
- Date: 2026-08-29
- Related stories: [US-076](../user-stories/completed/US-076-complete-client-player-stats-reader.md), [US-089](../user-stories/US-089-automated-client-binary-reverse-engineering-and-memory-profiling.md), [US-092](../user-stories/US-092-teleporter-config-target-selection-and-legacy-pruning.md)
- Related decisions: [ADR-006](ADR-006-read-only-process-memory-access.md), [ADR-003](ADR-003-clean-schema-over-backward-compatibility.md)
- Supersedes: none

## Context

The automated binary profiler ([US-089](../user-stories/US-089-automated-client-binary-reverse-engineering-and-memory-profiling.md))
generated a `RatioPlayerStatSource(numerator_offset, denominator_offset, scale)` for HP, MP and FP
by decoding one self-contained helper per vital
(`mov eax,[rcx+num]; imul eax,eax,100; cdq; idiv [rcx+den]; ret`). The live reader then performed
one bounded structure read and computed `current * 100 / maximum` itself.

The shipped Entropia client `8079c88f4c4e35a0b5acd117995125bee528c175d5b621e0533d85a4458dada5`
restructured these helpers. Each vital now has a wrapper that calls a maximum getter (guarded
`!= 0`), then a current getter, then combines them MulDiv-style with `100` as the scale.
Static decoding of the shipped binary shows:

- MP and FP current values are clean fixed player-struct offsets (`+0x12FC`, `+0x1300`).
- MP and FP maxima are computed at runtime from base stat, equipment and buffs through a generic
  attribute resolver (`sub_849d40`, keyed by attribute-id immediates). They are not stored at a
  fixed offset.
- HP resolves both current and maximum through further call chains with no single fixed offset.
- No instruction in the getter chain writes the computed maximum back to any object field, so a
  denominator offset cannot be recovered indirectly either.

A live memory read that stays within [ADR-006](ADR-006-read-only-process-memory-access.md)
(one fixed pointer read plus one bounded structure read, no runtime scanning or pointer chasing)
therefore cannot obtain a vital maximum for this build.

## Decision

1. The profiler emits a player-stat field only when a bounded read that yields that field's
   declared output is statically proven, never an offset or adjacent value it had to guess.
   A vital whose maximum is computed at runtime yields no provable `current * 100 / maximum`
   ratio, so no `hp`/`mp`/`fp` percentage field is emitted for it. When the *current* value
   alone has a proven bounded source, it is emitted under the distinct name `current_<vital>`
   (`current_hp`, `current_mp`, `current_fp`) so it is available to consumers that want the
   raw number without ever being mistaken for a 0..100 percentage.
2. A shortfall in the vital set is not fatal to profile generation. The generated bundle still
   carries every independently evidenced artifact (player pointer, position, camera, dungeon,
   monster-kills RVA, level, experience). `analyze_ratio_function` keeps its narrow contract and
   separate, equally narrow decoders handle the wrapper, the XOR-pair and the fixed-member
   shapes; none returns partial evidence.
3. `ClientPlayerStatsProfile` permits `hp`, `mp` and `fp` to be absent, and permits a
   `current_<vital>` field to carry a raw `DirectPlayerStatSource` or `XorPairPlayerStatSource`.
   The 0..100 output bound is enforced only for a vital field that actually declares a
   `RatioPlayerStatSource`.
4. Player-stats source health is derived from the fields a profile declares, not from a fixed
   `{hp, mp, fp}` set. A profile that proves no vital percentages is healthy for what it does
   provide (monster kills, level, experience), and the `PLAYER_STATS` readiness gate does not
   latch on the missing vitals.
5. Vital percentages for such a build come from the visual HUD reader (`PlayerVitalsReader`) via
   the existing degrade/restore machinery. `PlayerVitalsReader` is retained until a supported
   client build exposes a memory-resolvable vital ratio; the [US-092](../user-stories/US-092-teleporter-config-target-selection-and-legacy-pruning.md)
   decommissioning of the pixel vitals reader is gated on that condition. The
   [US-092](../user-stories/US-092-teleporter-config-target-selection-and-legacy-pruning.md)
   memory `monster_kills` extraction is independent and not gated.

## Alternatives

- **Guess the maximum offset from an adjacent struct member or a plausible constant.** Rejected:
  it contradicts the profiler's own "absence is a hard failure rather than an adjacent-offset
  guess" principle and would feed unverified data into a safety-relevant reading.
- **Replay the attribute resolver at runtime to compute the maximum.** Rejected: it requires
  walking variable-length equipment and buff structures keyed by attribute id, which is unbounded
  runtime traversal outside [ADR-006](ADR-006-read-only-process-memory-access.md) and US-076's
  fixed-bounded-read contract.
- **Emit the current value under the name `mp`/`fp` and treat it as the vital.** Rejected: the
  vitals consumer (`PlayerVitals`) is percentage-only and would reject a raw current, and any
  code keying `"hp"`/`"mp"`/`"fp"` would silently read a raw number as a percentage. The raw
  current is emitted under `current_<vital>` instead, and the percentage stays on the HUD.
- **Keep `_discover_player_stats` all-or-nothing.** Rejected: one changed helper shape would keep
  discarding unrelated, fully evidenced position, camera and dungeon plans.

## Consequences

- The generated player-stats profile for `8079c88f…dada5` carries `current_hp` (XOR-pair at
  `+0x1304`), `current_mp` (`+0x12FC`), `current_fp` (`+0x1300`), `level` (`+0x12C0`),
  `experience` (`+0x12C8`) and `monster_kills_rva`, and no `hp`/`mp`/`fp` percentage fields.
  `data/config/client_player_stats_profiles.json` is regenerated to this shape.
- The perception pipeline reads vital percentages from the HUD reader whenever a client-memory
  snapshot has no `hp`/`mp`/`fp` fields; the dashboard shows `PLAYER_STATS` healthy for what the
  profile does provide, with no permanent setup gate.
- A future client build that exposes a fixed vital ratio (or a proven write-back of the computed
  maximum) can restore a full `RatioPlayerStatSource` under `hp`/`mp`/`fp` without a schema
  change, because those fields are already optional.
- No back-compatibility shim is added for the old direct-offset player-stats document; per
  [ADR-003](ADR-003-clean-schema-over-backward-compatibility.md) the one current schema stands and
  the stale committed document is replaced.
- The dungeon-container decoder and a memory path for the vital percentages (the `CWndStatus`
  gauge floats) remain follow-up work tracked in [BUG-038](../bugs/BUG-038-player-stats-profiler-fails-closed-on-wrapped-vital-ratio-helpers.md).

## Verification

`tests/unit/test_client_profiling.py` covers the wrapped vital-ratio decoder, the XOR-pair HP
decoder, and the fixed-member level/experience discovery over synthetic PEs.
`tests/unit/test_player_stats_reader.py` covers `XorPairPlayerStatSource` decoding and consistency
failure, and a `current_<vital>` profile loading and decoding.
`tests/unit/test_production_readiness.py` and the orchestrator readiness tests cover a
percentage-free profile keeping the session armable with the HUD vitals fallback engaged.
`./scripts/check.ps1` is green.
