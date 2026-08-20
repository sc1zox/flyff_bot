# Entropia camera and projection static analysis (2026-08-20)

Local static analysis of the operator's unmodified Entropia PServer client for US-056.
Collected 2026-08-20 by repository maintainers from the local installation. No process was
started, no client file was modified, and no client binary or asset is included in this repository.

## Exact executable profiles

| Client | PE | SHA-256 | Image base | Camera pointer RVA | Pointer | Base eye | View | Inverse view | Look-at | Projection RVA |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `Entropia/Entropia/bin32/neuz.exe` | i386 | `3446FFEB5D104A68D187E9E2ECFA216E1BDB88CE3F9201A046AA900525B6C07E` | `0x00400000` | `0x00967FBC` | 4 | `+0x04` | `+0x10` | `+0x50` | `+0x90` | `0x00B015D0` |
| `Entropia/Entropia/bin64/neuz.exe` | x86-64 | `8079C88F4C4E35A0B5ACD117995125BEE528C175D5B621E0533D85A4458DADA5` | `0x140000000` | `0x00BAD8E8` | 8 | `+0x08` | `+0x14` | `+0x54` | `+0x94` | `0x00D76B80` |

The active viewport projection is a module global in both builds, not a member of the camera
object. A camera profile must therefore distinguish pointer-relative structure offsets from the
direct module-relative projection-matrix RVA.

## Static evidence

- x86 camera pointer setter/getter: `0x004CE040` / `0x004EBB50`.
- x86 update at `0x00B2E8C0` uses `D3DXMatrixLookAtLH` to write the View Matrix at `this+0x10`
  from the base eye at `this+0x04` and the look-at target at `this+0x90`.
- x86 code around `0x00B480A4` writes the active projection matrix to `0x00F015D0` and applies it
  to Direct3D.
- x64 camera-pointer setter: `0x1400F02E0`.
- x64 update at `0x1408BF840` copies the base eye at `this+0x08`, applies transient camera-shake
  displacement, calls `D3DXMatrixLookAtLH`, writes the View Matrix at `this+0x14`, and computes
  inverse view at `this+0x54`.
- x64 function `0x1408DAF00` derives viewport aspect ratio, calls `D3DXMatrixPerspectiveFovLH` at
  `0x1408DB0E5`, writes the active projection to `0x140D76B80`, then applies it to Direct3D.

## Derived-state convention

The verified D3DX matrices are row-major and use row-vector multiplication. The authoritative
camera eye is the fourth row XYZ of the computed inverse View Matrix; it includes transient
camera shake, unlike the stored base eye. The forward direction is the inverse View Matrix third
row XYZ. The following quantities are therefore derived rather than read from unverified scalar
fields:

```text
view_projection = view @ projection
pitch = asin(clamp(forward.y, -1, 1))
yaw = atan2(forward.x, forward.z)
zoom_distance = norm(look_at - effective_eye)
vertical_fov = 2 * atan(1 / projection[1, 1])
```

Direct3D clip-space depth is `[0, 1]`. A screen ray transforms NDC near `(x, y, 0, 1)` and far
`(x, y, 1, 1)` by `inverse(view_projection)`, divides by homogeneous `w`, and normalizes the
vector from the effective camera eye to the far point.

## Explicit exclusions

The following square-projection paths are distinct render targets and must not be used as the
active viewport camera:

- x86 object `0x00E6EF78`, View `+0x04`, Projection `+0x44`.
- x64 object `0x140CBA7F0`, View `+0x08`, Projection `+0x48`.

Scalar fields near x86 `+0xD0` and x64 `+0xD4` were not semantically proven as pitch, yaw, zoom,
or FOV and are deliberately not included in profiles.

## Remaining runtime validation

This source proves fixed, hash-bound static addresses and Direct3D call paths. It does not prove
live `ReadProcessMemory` latency, camera-shake amplitude, pitch/yaw sign expectations, viewport
resize behavior, or the values from a running `neuz.exe`. Those remain Windows live-client
walkthroughs.
