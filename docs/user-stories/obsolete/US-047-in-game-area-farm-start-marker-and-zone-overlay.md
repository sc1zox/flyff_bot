---
id: US-047
title: In-game area farm start marker and vector zone boundary overlay
status: draft
created: 2026-08-19
updated: 2026-08-19
---

# US-047: In-game area farm start marker and vector zone boundary overlay

## Story

As a **bot operator configuring or monitoring an area farming session**,
I want **a toggleable, transparent in-game desktop overlay that visualizes the exact start anchor / registered vector farm zone origin, patrol perimeter, and live player offset directly over the game client window**,
so that **I can visually verify the character's exact spatial alignment with the mapped world vector terrain before and during farming, calibrate the registration anchor, and ensure obstacle-free routing without blind collisions**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- [US-045](../completed/US-045-vector-world-terrain-extraction-and-goal-navigation.md) extracts vector spawn zones, terrain elevation, and impassable slope meshes (`WorldVectorMap`) and introduces `WorldRegistration` to map client world coordinates to session minimap pixels.
- [US-035](../completed/US-035-measured-minimap-odometry-and-tracking-quality.md) measures live player position and heading from the minimap via phase correlation.
- [US-037](../completed/US-037-measured-spawn-distance-and-enforced-leash.md) defines and enforces the patrol leash radius around the session anchor.
- [BUG-008](../../bugs/fixed/BUG-008-placement-guides-in-game-overlay.md) established the transparent desktop overlay architecture: a frameless, click-through (`Qt.WindowType.WindowTransparentForInput`, `WA_ShowWithoutActivating`, `WA_TranslucentBackground`) `Qt.Tool` window tracking the game client window on screen via `ClientGeometryProvider` without stealing window focus or pausing guarded sessions.
- In Area Farm Mode, the start point / anchor defines the reference origin $(0, 0)$ for relative navigation or the registered centroid of the active `VectorSpawnZone` in the world vector map.
- The overlay must display:
  - The start point / anchor position (crosshair / marker symbol with coordinate and zone name label).
  - The active patrol perimeter / leash radius boundary.
  - Live spatial vector / distance (minimap pixels and meters/MPU) and relative bearing from the player's current location to the start anchor.
- Operator controls:
  - Toggleable via a dedicated UI control (e.g. checkbox / button in Dashboard Navigation panel and/or World Data Dialog).
  - Explicitly available in Standby mode (before starting the session) so the operator can inspect and calibrate the character's exact alignment before input dispatch begins.
  - Can be toggled on/off during active farming without interrupting or restarting the session.
- Safety boundaries:
  - Never steals foreground window focus (retains `Qt.WindowType.WindowTransparentForInput` and `WA_ShowWithoutActivating`).
  - Automatically hides when the game client window is closed, minimized, or lost.
  - All user-visible labels, tooltips, and chip texts must be synchronized in German (`de.json`) and English (`en.json`).

## Acceptance criteria

- [ ] **In-Game Start Marker Overlay Widget:**
  - A dedicated transparent, click-through desktop overlay widget (`AreaStartOverlayWindow` or extension of `PlacementOverlayWindow`) renders directly aligned over the tracked `neuz.exe` client area.
  - The window uses `Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput` and `Qt.WidgetAttribute.WA_ShowWithoutActivating`, ensuring no focus is stolen and input guards remain unaffected.
- [ ] **Visual Anchor & Perimeter Rendering:**
  - When enabled, the overlay displays the start anchor point (prominent crosshair / bullseye icon with high-contrast outline).
  - Displays the active zone name (e.g. `Flame (Zone #12)` or `Session Origin (0, 0)`), world coordinates $(X, Z)$, and configured leash radius circle.
- [ ] **Live Spatial Telemetry & Offset Tracking:**
  - When live odometry (`MovementTracker`) is active, the overlay indicates the player's current position relative to the start anchor:
    - Distance from anchor in minimap pixels and approximate world units / meters.
    - Directional indicator (bearing arrow or connecting vector line) pointing back to the start anchor when the player moves away.
    - Warning indicator when the player approaches or crosses the leash perimeter.
- [ ] **Standby & Pre-Flight Calibration Mode:**
  - The overlay can be activated while the bot is in `STANDBY` (paused / not farming), allowing the operator to manually move the character in-game and align the character with the desired start anchor before pressing "Start".
  - Updating or selecting a new spawn zone in the World Data Dialog immediately refreshes the rendered start anchor and boundary.
- [ ] **Dashboard Toggle & Persistence:**
  - A dedicated checkbox/action (e.g. *"Startpunkt-Overlay"* / *"Area Start Overlay"*) is available in the Dashboard Navigation card and Telemetry toolbar.
  - Toggling the overlay takes effect immediately on the screen without resetting session state or interrupting active farming loops.
- [ ] **Client Tracking & Window Resizing:**
  - Reuses `ClientGeometryProvider` / `client_screen_bounds()` to continuously track client movement, resizing, and DPI scaling changes.
  - The overlay automatically hides when the game client is minimized, lost, or closed.
- [ ] **Localization:**
  - All new labels, dialog texts, tooltips, and overlay captions are fully synchronized in German (`de.json`) and English (`en.json`).

## Out of scope

- In-game HUD texture modification or client memory injection (uses external transparent desktop overlay only).
- Direct 3D camera projection matrix transformations (renders 2D ground-plane / radar-style relative overlay or screen-aligned HUD indicator anchored to client geometry).
- Automatic character walking to the start anchor before session start (operator positions character or path planner navigates within leash bounds).

## Verification

- Automated:
  - Unit tests for overlay layout computation, coordinate mapping to overlay canvas, toggle signal wiring, and locale dictionary key matching.
  - Tests ensuring the overlay window maintains transparent, click-through, and non-activating window attributes.
- Manual (Windows):
  1. Launch Flyff game client (`neuz.exe`) and start `flyff-bot` in desktop mode.
  2. Open the Navigation / World Data panel and enable "Area Start Overlay".
  3. Verify that the start anchor marker and leash boundary appear directly overlaid on the game client in standby mode.
  4. Move the character in-game; verify that distance and directional indicators to the start anchor update smoothly.
  5. Move or resize the Flyff client window; verify that the overlay tracks geometry without stealing focus.
  6. Start farming; verify that the overlay remains toggleable and does not interfere with combat or pathing.
