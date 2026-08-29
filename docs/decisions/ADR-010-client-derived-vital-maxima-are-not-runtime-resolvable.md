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
   declared output is statically proven. A vital whose maximum is computed at runtime yields no
   provable bounded ratio, so the profiler omits that vital rather than guessing an offset or an
   adjacent value.
2. A shortfall in the vital set is not fatal to profile generation. The generated bundle still
   carries every independently evidenced artifact (player pointer, position, camera, dungeon,
   monster-kills RVA, level, experience). `analyze_ratio_function` keeps its narrow contract and
   a separate equally narrow decoder handles the wrapper shape; neither returns partial evidence.
3. `ClientPlayerStatsProfile` permits `hp`, `mp` and `fp` to be absent. The 0..100 output bound
   is enforced only for vital fields that actually declare a `RatioPlayerStatSource`.
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
- **Read only the current value from memory and treat "mp"/"fp" as raw values.** Rejected as a
  memory design: the vitals consumer (`PlayerVitals`) is percentage-only, and a raw current with
  no maximum is not a ratio. The HUD fallback already covers this case.
- **Keep `_discover_player_stats` all-or-nothing.** Rejected: one changed helper shape would keep
  discarding unrelated, fully evidenced position, camera and dungeon plans.

## Consequences

- The generated bundle for `8079c88f…dada5` contains position, camera, dungeon, monster-kills,
  level and experience, and no `hp`/`mp`/`fp` fields. `data/config/client_player_stats_profiles.json`
  is regenerated to this shape.
- The dashboard shows `PLAYER_STATS` healthy for kills, level and experience, with vital
  percentages sourced from the HUD reader and no permanent setup gate.
- A future client build that exposes a fixed vital ratio (or a proven write-back of the computed
  maximum) can restore the full `RatioPlayerStatSource` without a schema change, because the
  fields are already optional.
- No back-compatibility shim is added for the old direct-offset player-stats document; per
  [ADR-003](ADR-003-clean-schema-over-backward-compatibility.md) the one current schema stands and
  the stale committed document is replaced.

## Verification

`tests/unit/test_client_profiling.py` covers a synthetic PE carrying the wrapped vital-ratio shape
(current-only MP/FP, computed HP/max) and asserts the bundle still generates with position,
camera, dungeon, level, experience and monster-kills intact and no vital fields.
`tests/unit/test_player_stats_reader.py` covers a profile with no vital fields loading and
decoding, and the loader still rejecting a raw (non-ratio) `hp`/`mp`/`fp` field.
`tests/unit/test_production_readiness.py` and the orchestrator readiness tests cover a
vitals-free profile keeping the session armable with the HUD vitals fallback engaged.
`./scripts/check.ps1` is green.
