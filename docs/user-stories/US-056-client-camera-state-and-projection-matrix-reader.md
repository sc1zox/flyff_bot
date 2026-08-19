---
id: US-056
title: Client camera state and projection matrix memory reader
status: draft
created: 2026-08-20
updated: 2026-08-20
---

# US-056: Client Camera State and Projection Matrix Memory Reader

## Story

As a **Flyff bot developer and perception engineer**,
I want **a fingerprinted, read-only memory reader that continuously extracts the game client's 3D camera state ($X, Y, Z$, pitch, yaw, zoom, FOV) and $4 \times 4$ View/Projection matrices**,
so that **2D screen detections can be unprojected into exact 3D world rays for ground-plane and NavMesh mob localization without relying on approximate inverse-perspective calibration**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Relates to:
  - [`docs/wiki/architecture.md`](../wiki/architecture.md) & [`docs/wiki/glossary.md`](../wiki/glossary.md).
  - [`docs/user-stories/US-054-farming-telemetry-and-adaptive-navigation-dataset.md`](US-054-farming-telemetry-and-adaptive-navigation-dataset.md): Farming telemetry and offline RL dataset foundation.
  - [`docs/user-stories/US-055-authoritative-3d-world-geometry-and-navmesh-foundation.md`](US-055-authoritative-3d-world-geometry-and-navmesh-foundation.md): Authoritative 3D world geometry and NavMesh foundation.
  - [`docs/user-stories/completed/US-042-automated-camera-alignment-and-standardized-viewport-initialization.md`](completed/US-042-automated-camera-alignment-and-standardized-viewport-initialization.md) & [`docs/user-stories/completed/US-043-continuous-approach-target-tracking-and-minimap-zoom-initialization.md`](completed/US-043-continuous-approach-target-tracking-and-minimap-zoom-initialization.md): Standardized viewport initialization.
  - Raw source: [`docs/sources/2026-08-19-entropia-client-navigation-data-extraction.md`](../sources/2026-08-19-entropia-client-navigation-data-extraction.md).
- **Direct3D 9 Camera Internals (`neuz.exe`):**
  - Flyff maintains an active camera object (`CCamera`) that updates every frame with the player's view state:
    - Camera eye position: $\mathbf{p}_{\text{cam}} = (X, Y, Z)$
    - Look-at focus point: $\mathbf{p}_{\text{target}} = (X, Y, Z)$
    - Pitch (elevation angle) and Yaw (azimuth / compass heading)
    - Camera distance / zoom level and Field of View (FOV)
    - $4 \times 4$ View Matrix ($\mathbf{V} = \text{D3DXMatrixLookAtLH}$)
    - $4 \times 4$ Projection Matrix ($\mathbf{P} = \text{D3DXMatrixPerspectiveFovLH}$)
- **Mathematical Screen-to-World Unprojection:**
  - Given a 2D bounding box center $(u, v)$ in client viewport pixels $(W, H)$, the normalized device coordinate (NDC) is:
    $$x_{\text{ndc}} = \frac{2u}{W} - 1, \quad y_{\text{ndc}} = 1 - \frac{2v}{H}$$
  - Transforming NDC through the inverted view-projection matrix $\mathbf{M}^{-1} = (\mathbf{V} \cdot \mathbf{P})^{-1}$ yields the authoritative 3D world ray:
    $$\mathbf{r}(t) = \mathbf{p}_{\text{cam}} + t \cdot \mathbf{d}_{\text{ray}}$$
- **Configuration by SHA-256 Fingerprint:**
  - Offsets for the global camera pointer and matrix offsets are defined per binary SHA-256 fingerprint in `data/config/client_camera_profiles.json`, mirroring [`LivePositionReader`](../../src/flyff_bot/features/navigation/live_position.py).
- **Safety Boundaries:**
  - Read-only memory access via `ReadProcessMemory` with `PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION`.
  - Zero memory writes, zero DLL injection, zero API hooking, zero process modification.

## Functional Requirements

### FR-1 – Fingerprinted Camera Profile Registry
- The system must maintain `data/config/client_camera_profiles.json` storing verified module-relative offsets for each supported client executable:
  - `camera_global_rva`: RVA to global `CCamera*` or `CWorld*` camera pointer
  - `view_matrix_offset`: Offset to 64-byte $4 \times 4$ float32 View Matrix
  - `proj_matrix_offset`: Offset to 64-byte $4 \times 4$ float32 Projection Matrix
  - `position_offset`: Offset to 12-byte float32 $(X, Y, Z)$ eye position
  - `angles_offset`: Offset to pitch, yaw, zoom distance, and FOV floats

### FR-2 – Read-Only Memory Extraction Engine (`LiveCameraReader`)
- `LiveCameraReader` continuously reads camera state at 10–20 Hz:
  - Authoritative camera world position $(X, Y, Z)$
  - Pitch, Yaw, Distance/Zoom, and FOV
  - Complete $4 \times 4$ View Matrix $\mathbf{V}$ and Projection Matrix $\mathbf{P}$
  - Computed View-Projection Matrix $\mathbf{VP} = \mathbf{V} \cdot \mathbf{P}$ and its inverse $\mathbf{VP}^{-1}$

### FR-3 – Screen Ray Unprojection Utility
- The camera feature must provide a typed unprojection function:
  ```python
  def unproject_screen_ray(
      screen_x: float,
      screen_y: float,
      viewport_width: int,
      viewport_height: int,
      camera_state: CameraState,
  ) -> WorldRay3D: ...
  ```
- Returns `WorldRay3D(origin=WorldPosition, direction=Vector3D)` normalized to unit length.

### FR-4 – Idempotent Lifecycle & Diagnostics
- `LiveCameraReader` handles process restarts, lost handles, minimized client windows, and unsupported builds cleanly.
- Emits typed `CameraReadError` diagnostics with specific error codes (`UNSUPPORTED_BUILD`, `HANDLE_LOST`, `PROCESS_UNAVAILABLE`, `WINDOW_NOT_FOREGROUND`).

### FR-5 – Truthfulness & Graceful Fallback
- When camera memory reading is unavailable or unconfigured, camera state resolves to `None`.
- Downstream perception and telemetry systems explicitly record projected geometry fields as `null` without fabricating heuristics.

## Acceptance criteria

- [ ] **Camera Profile Configuration:** `data/config/client_camera_profiles.json` parses validated 32-bit and 64-bit offsets mapped by SHA-256 fingerprint.
- [ ] **10 Hz Live Camera Extraction:** `LiveCameraReader` extracts camera position, orientation angles, FOV, and $4 \times 4$ View/Projection matrices with $< 0.1\,\text{ms}$ read latency.
- [ ] **Matrix Inversion Integrity:** The inverse view-projection matrix $\mathbf{VP}^{-1}$ is computed reliably; singular or near-zero determinant matrices are rejected safely.
- [ ] **Accurate Ray Unprojection:** `unproject_screen_ray()` transforms viewport pixels $(0, 0)$, $(W/2, H/2)$, and $(W, H)$ into mathematically correct 3D rays matching the client's perspective frustum.
- [ ] **Fault Tolerance & Clean Recovery:** Lost process handles, background window state, or client restarts recover automatically upon re-acquisition without thread deadlocks or crashes.
- [ ] **Safety Boundaries Preserved:** Handles are opened strictly with `PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION`. No write APIs (`WriteProcessMemory`, `VirtualAllocEx`) are used.
- [ ] **Quality Gate:** `./scripts/check.ps1` passes cleanly (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- [ ] **Localization:** All diagnostic error messages and status chips are localized in German (`de.json`) and English (`en.json`).

## Out of scope

- Ray-triangle mesh intersection (handled in US-057).
- Modifying camera FOV, pitch, or zoom via memory write (camera input is commanded exclusively via Win32 keystrokes/scroll events).
- Dynamic DLL hooking or graphics API interception (Direct3D `EndScene` hooking is strictly prohibited).

## Verification

- Automated:
  - Unit tests in `tests/unit/test_live_camera.py` validating synthetic memory buffer reads, binary profile resolution, matrix math, and `unproject_screen_ray()` vectors.
  - Tests simulating handle loss and process restart recovery.
  - Check suite pass: `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- Manual (Windows):
  - Run the camera reader against live `neuz.exe`, rotate the camera in-game, and verify that extracted pitch/yaw/matrices track smoothly in real time.
