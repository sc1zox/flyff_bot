---
id: BUG-039
title: Generated player-position offset is a byte-match false positive
status: reported
severity: high
created: 2026-08-29
updated: 2026-08-29
---

# BUG-039: Generated player-position offset is a byte-match false positive

## Environment

- Windows version: Windows 11 Pro 26200
- Python version: 3.14 (`.python-version`)
- Application revision: `main` after `83c469d`
- Client/server version: Entropia Flyff PServer, `Entropia/Entropia/bin64/neuz.exe`,
  SHA-256 `8079c88f4c4e35a0b5acd117995125bee528c175d5b621e0533d85a4458dada5`

## Reproduction

1. Run the binary profiler against the shipped x64 client:
   `ClientBinaryProfiler().profile(Path("Entropia/Entropia/bin64/neuz.exe"))`.
2. Inspect `bundle.position`: `position_offset == 184` (`0xB8`).
3. Compare with the verified offset: `PLAYER_POSITION_OFFSET == 0x188` (`392`) in
   `src/flyff_bot/features/navigation/live_position.py`, the position unit tests, and the static
   evidence in
   [2026-08-29 CWndStatus and player-position static analysis](../sources/2026-08-29-entropia-cwndstatus-and-player-position-static-analysis.md)
   (14 corroborating `movups`/`movss` sites at `CMover + 0x188`; `0xB8` is an unrelated vec3).
4. `SetupExtractionRunner._run_memory_profile_stage` calls `persist_profile_bundle(...,
   position_path=...)`, which validates only that the document round-trips, not that the offset
   is correct. On a real operator setup run this installs
   `data/navigation/client_profiles.json` with `position_offset = 184`.

## Expected behavior

- `ClientBinaryProfiler._discover_player` decodes an actual `add r/m64, imm32` / `lea` instruction
  (or corroborates the member the way `_camera_member_offsets` does) and emits the verified
  player-position offset `0x188`, or emits nothing and fails typed rather than a spurious value
  (US-089; ADR-011 "absence over an adjacent-offset guess").
- The setup wizard never installs an unverified coordinate offset.

## Actual behavior

- `_discover_player` scans a 160-byte window after each `GetPlayer` call for the raw byte pair
  `48 05` and reads the next dword as an `add rax, imm32` immediate, gated only by "the window
  also contains a `rep movsb`(12) **or** any `movss`" — a condition nearly every window meets. In
  `8079c88f…` the `48 05` pair matches inside an unrelated instruction. The real `GetPlayer` copy
  site (`sub_8BE4B0`: `call GetPlayer; mov rcx,rax; call sub_094800; mov rsi,rax; mov ecx,0xC;
  rep movsb`) copies 12 bytes from a helper return value, not from `player + 0xB8`. The emitted
  `position_offset = 184` is wrong.
- `persist_profile_bundle` installs it without a correctness check. `LivePositionReader` would then
  read a `D3DXVECTOR3` at `player + 0xB8` — unrelated floats — as the world position.
- The repository masks this: `data/navigation/` is `.gitignore`d ("locally learned navigation
  maps"), so no committed `client_profiles.json` exists and the position reader currently returns
  a typed "no profile" diagnostic for the shipped build (`LivePositionReader` seeds `self._profiles`
  only from that file and never from the module-level `ENTROPIA_POSITION_PROFILES` map, which is
  referenced only by tests). The committed camera / dungeon / player-stat registries live under the
  non-ignored `data/config/`; the fingerprinted position profile has no committed home.
- BUG-038 and `docs/wiki/architecture.md` state the profiler "completes end to end" and that
  position is "statically evidenced" for this digest. That holds for camera / dungeon /
  player-stats (RTTI- and prologue-anchored); it is overstated for position.

## Impact and frequency

- Impact: on operator first-run setup the wizard installs a wrong player-coordinate offset for the
  shipped x64 build; live GPS then feeds navigation an unrelated vec3 as the world position. In
  the repository as shipped, live GPS is instead simply unconfigured for this build.
- Frequency: every profiler run against `8079c88f…` (100%).

## Fix plan

- [ ] Harden `ClientBinaryProfiler._discover_player`: decode the `add`/`lea` instruction rather
      than byte-matching `48 05`, and require the member to be the actual source register of the
      12-byte `D3DXVECTOR3` copy. Add a synthetic-PE regression with a spurious `48 05` byte in an
      unrelated instruction. Re-run against the real binary and assert `0x188`.
- [ ] Give the fingerprinted position (and world-id) profile a committed home consistent with
      camera / dungeon / player-stats — i.e. a `data/config/` path — or, if it must stay operator-
      generated, have `persist_profile_bundle` / the wizard cross-check the generated
      `position_offset` against `PLAYER_POSITION_OFFSET` and refuse a mismatch.
- [ ] Decide whether the live readers should fall back to their `ENTROPIA_*_PROFILES` maps when no
      registry file is present; apply one policy across all four live readers. `live_world_id.py`
      has no embedded map and `GeneratedClientProfileBundle` emits no world-id profile — close that
      gap or document it.
- [ ] Verify the bin32 build (`3446ffeb…`) position offset independently; `PLAYER_POSITION_OFFSET`
      is shared as the default for both builds.
- [ ] Correct the "completes end to end" / "statically evidenced" position claims in BUG-038 and
      `docs/wiki/architecture.md` (done in the reporting change).

## Regression verification

- [ ] A failing automated test or deterministic manual check exists.
- [ ] The check passes after the fix.
- [ ] Related documentation is current.
