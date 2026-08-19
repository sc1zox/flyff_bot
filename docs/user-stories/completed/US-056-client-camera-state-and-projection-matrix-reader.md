---
id: US-056
title: Client camera state and projection matrix memory reader
status: completed
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
- **Direct3D 9 Camera Internals (`neuz.exe`):** Static analysis verified exact x86/x64 camera
  pointer, eye, View, look-at, and independent module-global projection addresses. The active
  projection is not a camera member; see [`docs/sources/2026-08-20-entropia-camera-static-analysis.md`](../sources/2026-08-20-entropia-camera-static-analysis.md).
  Pitch, yaw, zoom, and FOV are derived from verified matrices/vectors, not unverified scalar
  fields.
- **Mathematical Screen-to-World Unprojection:**
  - Given a 2D bounding box center $(u, v)$ in client viewport pixels $(W, H)$, the normalized device coordinate (NDC) is:
    $$x_{\text{ndc}} = \frac{2u}{W} - 1, \quad y_{\text{ndc}} = 1 - \frac{2v}{H}$$
  - Transforming NDC through the inverted view-projection matrix $\mathbf{M}^{-1} = (\mathbf{V} \cdot \mathbf{P})^{-1}$ yields the authoritative 3D world ray:
    $$\mathbf{r}(t) = \mathbf{p}_{\text{cam}} + t \cdot \mathbf{d}_{\text{ray}}$$
- **Configuration by SHA-256 Fingerprint:**
  - Offsets for the global camera pointer, pointer-relative camera structures, and independent
    module-relative projection matrix are defined per binary SHA-256 fingerprint in
    `data/config/client_camera_profiles.json`.
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
  - No `angles_offset` is used: pitch, yaw, zoom distance, and FOV are derived from verified
    matrices and the look-at vector.

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

- [x] **Camera Profile Configuration:** `data/config/client_camera_profiles.json` parses validated 32-bit and 64-bit offsets mapped by SHA-256 fingerprint, distinguishing camera pointer offsets from the independent projection RVA.
- [x] **10 Hz Live Camera Extraction:** `LiveCameraReader` provides the 10 Hz foreground-gated extraction contract for camera position, derived orientation/FOV/distance, and $4 \times 4$ View/Projection matrices. Synthetic automated tests cover the read path; live latency and tracking remain Windows checks.
- [x] **Matrix Inversion Integrity:** The inverse view-projection matrix $\mathbf{VP}^{-1}$ is computed reliably; singular or near-zero determinant matrices are rejected safely.
- [x] **Accurate Ray Unprojection:** `unproject_screen_ray()` transforms viewport pixels $(0, 0)$, $(W/2, H/2)$, and $(W, H)$ into mathematically correct 3D rays matching the verified Direct3D perspective convention.
- [x] **Fault Tolerance & Clean Recovery:** Lost process handles, background window state, or client restarts recover automatically upon re-acquisition without thread deadlocks or crashes in the tested lifecycle paths.
- [x] **Safety Boundaries Preserved:** Handles are opened strictly with `PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION`. No write APIs (`WriteProcessMemory`, `VirtualAllocEx`) are used.
- [x] **Quality Gate:** `./scripts/check.ps1` passes cleanly: 792 tests passed, 2 skipped, and 91.48% coverage.
- [x] **Localization:** All diagnostic error messages and status chips are localized in German (`de.json`) and English (`en.json`).

## Out of scope

- Ray-triangle mesh intersection (handled in US-057).
- Modifying camera FOV, pitch, or zoom via memory write (camera input is commanded exclusively via Win32 keystrokes/scroll events).
- Dynamic DLL hooking or graphics API interception (Direct3D `EndScene` hooking is strictly prohibited).

## Verification

- Automated:
  - Unit tests in `tests/unit/test_live_camera.py` validating synthetic memory buffer reads, binary profile resolution, matrix math, and `unproject_screen_ray()` vectors.
  - Tests simulating handle loss and process restart recovery.
  - Check suite pass: `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- Manual (Windows, outstanding):
  - Run the camera reader against live `neuz.exe` and verify camera rotation, zoom, viewport resize,
    pitch/yaw signs, and View/Projection tracking in real time.
  - Measure live read latency, then minimize/background and restore the client and restart
    `neuz.exe` to verify recovery and handle reacquisition.
