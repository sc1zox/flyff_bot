---
id: BUG-039
title: Generated player-position offset is a byte-match false positive
status: resolved
severity: high
created: 2026-08-29
updated: 2026-08-31
---

# BUG-039: Generated player-position offset is a byte-match false positive

## Environment

- Windows version: Windows 11 Pro 26200
- Python version: 3.14 (`.python-version`)
- Application revision: `main` after `8e2936b`
- Client/server version: Entropia Flyff PServer, `Entropia/Entropia/bin64/neuz.exe`,
  SHA-256 `8079c88f4c4e35a0b5acd117995125bee528c175d5b621e0533d85a4458dada5`

## Reproduction

1. Run the initial setup wizard against the shipped x64 client:
   `ClientBinaryProfiler().profile(Path("Entropia/Entropia/bin64/neuz.exe"))`.
2. Inspect `bundle.position`: `position_offset == 184` (`0xB8`) is generated instead of `PLAYER_POSITION_OFFSET == 0x188` (`392`).
3. `SetupExtractionRunner._run_memory_profile_stage` persists this to
   `data/navigation/client_profiles.json` with `position_offset = 184`.
4. Launch the desktop bot (`flyff-bot`) with the 64-bit game client running in Eden.
5. Open the **Navigation Karte** tab.
6. Observe the top telemetry chip: `GPS: live`.
7. Observe the Map HUD overlay: `GPS: (+0.0, -0.0) Ausrichtung: ... Wegpunkte: 0 Status: GPS: live`.
8. Observe the map canvas: the player marker `▲ Spieler (Blickfeld)` is pinned at coordinate `(0.0, 0.0)` at the bottom-left corner of the map grid instead of on the Eden island terrain.
9. Move the character in-game: the GPS coordinate readout remains stuck at `(+0.0, -0.0)` and does not track character movement.

## Expected behavior

- `ClientBinaryProfiler._discover_player` decodes an actual `add r/m64, imm32` / `lea` instruction
  (or corroborates the member the way `_camera_member_offsets` does) and emits the verified
  player-position offset `0x188`, or emits nothing and fails typed rather than a spurious value
  (US-089; ADR-011 "absence over an adjacent-offset guess").
- The setup wizard never installs an unverified coordinate offset.
- On the Navigation map, live GPS reflects the player's true in-game world coordinates and dynamically updates as the player moves.

## Actual behavior

- `_discover_player` scans a 160-byte window after each `GetPlayer` call for the raw byte pair
  `48 05` and reads the next dword as an `add rax, imm32` immediate, gated only by "the window
  also contains a `rep movsb`(12) **or** any `movss`" — a condition nearly every window meets. In
  `8079c88f…` the `48 05` pair matches inside an unrelated instruction. The real `GetPlayer` copy
  site (`sub_8BE4B0`: `call GetPlayer; mov rcx,rax; call sub_094800; mov rsi,rax; mov ecx,0xC;
  rep movsb`) copies 12 bytes from a helper return value, not from `player + 0xB8`. The emitted
  `position_offset = 184` is wrong.
- `persist_profile_bundle` installs it without a correctness check. `LivePositionReader` then reads
  the 12 bytes at `player + 0xB8` — which are null bytes (`(0.0, 0.0, 0.0)`) — as the world position.
- Because the read succeeds and produces finite floats, `LivePositionReader` reports `PositionSource.LIVE`
  with `WorldPosition(0.0, 0.0, 0.0)`.
- The dashboard shows `GPS: live`, but coordinates stay permanently frozen at `(+0.0, -0.0)` and the
  player cone renders at the bottom-left edge outside the terrain.
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
  shipped x64 build; live GPS reports `live` with coordinates stuck at `(+0.0, -0.0)`, pinning the
  player icon to the corner of the navigation map and preventing position tracking.
- Frequency: every profiler run against `8079c88f…` (100%).

## Resolution

`ClientBinaryProfiler._discover_player` now follows the decoded `GetPlayer` call through its
helper return and accepts the 12-byte position copy only when that proven flow identifies the
member. For the shipped x64 fingerprint, the result is `CMover + 0x188` (`392`), rather than the
former byte-match false positive `0xB8` (`184`). The setup path persists only the decoded,
fingerprint-bound profile.

Position profiles now have a committed home at
`data/config/client_position_profiles.json`. It contains the explicit x64 `0x188` profile only:
the x86 build remains unavailable until independently verified. `LivePositionReader` does not use
an embedded profile or a default/guessed offset when the registry lacks a matching fingerprint.
`data/config/client_world_id_profiles.json` is deliberately committed empty because no world-ID
offset is proven; `LiveWorldIdReader` therefore remains typed-unavailable rather than guessing a
value. Arrival confirmation continues to fail closed when world ID is unavailable.

## Fix plan

- [x] Harden `ClientBinaryProfiler._discover_player` so it follows the decoded `GetPlayer` helper
      path and accepts only the proven 12-byte `D3DXVECTOR3` copy. Synthetic regressions reject a
      spurious `48 05` byte match; the real local x64 profiler yields `0x188`.
- [x] Give fingerprinted position profiles a committed `data/config/` home. The x64 profile carries
      its explicit verified offset; world ID remains an intentionally empty committed registry
      until evidence supports an entry.
- [x] Apply the no-fallback policy to the live position and world-ID readers: no embedded profile
      or default offset is used when a registry entry is absent. The empty world-ID registry is
      documented as typed-unavailable rather than treated as a gap to guess.
- [ ] Verify the bin32 build (`3446ffeb…`) position offset independently; `PLAYER_POSITION_OFFSET`
      is shared as the default for both builds.
- [x] Correct the historical "completes end to end" / "statically evidenced" position claims in
      BUG-038 and `docs/wiki/architecture.md`.

## Regression verification

- [x] A failing automated regression was added for decoded position discovery, false-positive
      rejection, committed profile loading, and unavailable world-ID behavior.
- [x] The focused regression passes: `uv run pytest --no-cov
      tests/unit/test_client_profiling.py tests/unit/test_live_position.py
      tests/unit/test_live_world_id.py tests/unit/test_setup_extraction.py` passed 48 tests with
      repo-local `TMP`, `TEMP`, and `UV_CACHE_DIR`; the real local x64 profiler returned
      `position_offset=392` (`0x188`).
- [x] Related documentation is current. The canonical `./scripts/check.ps1` was attempted with
      the same environment, but stopped after dependency synchronization because of the unrelated,
      pre-existing Ruff error `tests/unit/test_orchestrator.py:1056 E501`; format, mypy, and the
      full pytest suite did not run, so this bug does not claim a green canonical gate.
