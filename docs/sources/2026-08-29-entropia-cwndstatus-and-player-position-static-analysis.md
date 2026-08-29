# Entropia CWndStatus gauge and player-position static analysis (2026-08-29)

Local static analysis of the operator's unmodified Entropia PServer client for the BUG-038 /
ADR-010 vital-percentage follow-up and an incidental audit of the generated position profile.
Collected 2026-08-29 by repository maintainers from the local installation with a standard-library
PE reader plus `capstone` disassembly. No process was started, no client file was modified, and no
client binary or asset is included in this repository.

## Executable

| Client | PE | SHA-256 | Image base |
| --- | --- | --- | ---: |
| `Entropia/Entropia/bin64/neuz.exe` | x86-64 | `8079C88F4C4E35A0B5ACD117995125BEE528C175D5B621E0533D85A4458DADA5` | `0x140000000` |

`.text` `0x1000..0x965FA8`; `.data` `0xB59000` (file-backed only to `0xB74400`, the rest is BSS);
`.pdata` carries 40706 `RUNTIME_FUNCTION` entries.

## Part 1 — CWndStatus vital gauges (ADR-010 follow-up)

### The gauge members exist and BUG-038's offsets are correct

- `CWndStatus` primary RTTI vtable: RVA `0xA79FE0` (57 entries). Its only code cross-references
  are `lea` at `0x6BD2DE` (constructor `sub_6BD2D0`) and `0x6E55A9` (destructor). No absolute
  pointer to the vtable exists in initialised data.
- `CWndStatus::OnDraw` is vtable index 10 → `sub_6BB730`. It has **zero direct callers**; it is
  reached polymorphically through the window manager's render loop.
- `sub_6BB730` calls `sub_6BCAC0` (its only caller) with `rcx = this`. `sub_6BCAC0` walks five
  inline `CWndGauge` members:

  | Gauge | Offset from `CWndStatus` | Fill source | Draw colour (`AARRGGBB`) | Meaning |
  | ---: | ---: | --- | ---: | --- |
  | 0 | `+0x2168` | `sub_844500(player, 100)` | `0x64FF0000` red | HP |
  | 1 | `+0x2194` | `sub_8443E0(player, 100)` | `0x640000FF` blue | MP |
  | 2 | `+0x21C0` | `sub_844430(player, 100)` | `0x6400FF00` green | FP |
  | 3 | `+0x21EC` | `sub_844480(player)` | `0x847070FF` | 4th bar (value already 0..100) |
  | 4 | `+0x2218` | `sub_824C90(player)` | `0x84E6B710` gold | EXP-like (value already 0..100) |

  Gauge stride is `0x2C` (44 bytes).

- The HP/MP/FP fill sources `sub_844500` / `sub_8443E0` / `sub_844430` are the ADR-010
  wrapped-ratio helpers: `p = sub_8493A0(player); if !p return 0; MulDiv(sub_849320(player), 100, p)`.
  They return an integer percentage `0..100`.
- `CWndGauge::SetFillRatio` = `sub_AE8E0(gauge, xmm1)`: `if x > 100.0f: x = 100.0f;` then
  `movss [gauge + 0x28], x`. The clamp constant at RVA `0xA9A068` is the `f32` `100.0`.

  **Therefore `*(f32*)(CWndStatus + {0x2168,0x2194,0x21C0} + 0x28)` is the live HP/MP/FP
  percentage as a clamped `0..100` float**, written every render tick from the client's own
  `MulDiv(current, 100, maximum)` — it already incorporates the runtime-resolved maximum that
  ADR-010 established cannot be read directly.

### There is no fingerprint-stable anchor to the CWndStatus instance

- `sub_6BB730` (OnDraw): 0 direct callers (virtual dispatch).
- Constructor `sub_6BD2D0`: only caller is its own deleting-destructor wrapper `sub_130CB0`.
- `sub_130CB0`: **0 direct callers** — it is invoked from a class factory table, so the built
  instance is placed in the window manager's child collection, never in a flat global.
- No `lea`/`mov` to a writable `.data` global holds a `CWndStatus*`; no statically initialised
  pointer to the object or its vtable exists.

Reaching `this` at runtime requires walking `CWndManager`'s polymorphic window collection —
unbounded pointer chasing outside [ADR-006](../decisions/ADR-006-read-only-process-memory-access.md)
(one fixed pointer read plus one bounded structure read). The gauge value is present in memory but
not reachable by a bounded fingerprinted read on this build.

### Corrections to prior notes

- BUG-038 "Remaining follow-up" and ADR-010 §Consequences describe the gauge floats as
  "each a 0..1 float" and as "the candidate bounded read for a later implementation". Both are
  inaccurate: the stored value is a `0..100` float, and no bounded read to it exists.

## Part 2 — player world-position member offset

- Player pointer global: RVA `0xB7C908` (`12044552`), pointer size 8. `GetPlayer` getter
  `sub_0E18E0` (`mov rax,[rip+0xB7C908]; ret`). This matches the committed camera / dungeon /
  player-stat profiles and `PLAYER_POSITION_PROFILES` in `live_position.py`.
- The player `D3DXVECTOR3` world position is at **`CMover + 0x188`** (x `+0x188`, y `+0x18C`,
  z `+0x190`): 14 corroborating `movups`/`movss` sites, e.g. `movups xmm0,[rbx+0x188]` at
  `0x3003F5` / `0x3004EB`, `movss [rax+0x188],xmm0` at `0x3E87C3` / `0x3EAC03`,
  `movss xmm2,[rcx+0x18C]` at `0x85CFF2`. This equals `PLAYER_POSITION_OFFSET = 0x188` in
  `src/flyff_bot/features/navigation/live_position.py` and the position unit tests.
- `ClientBinaryProfiler._discover_player` instead emits `position_offset = 184` (`0xB8`) for this
  binary. Its heuristic searches a 160-byte window after a `GetPlayer` call for the byte pair
  `48 05` and reads the following dword as an `add rax, imm32` immediate. In this binary that byte
  pair matches inside an unrelated instruction; the `GetPlayer` copy site at `sub_8BE4B0`
  (`call GetPlayer; mov rcx,rax; call sub_094800; mov rsi,rax; mov ecx,0xC; rep movsb`) copies 12
  bytes from a **helper return value**, not from `player + 0xB8`. `0xB8` is a separate, unrelated
  vec3 (7 unrelated `movups`/`movss` sites). The generated `184` is a false positive.

### Consequence

The generated position profile for `8079c88f…` is not trustworthy as produced. The verified
offset is `0x188` (`392`). No committed `data/navigation/client_profiles.json` exists (the
directory is `.gitignore`d), so the bad value is not exercised in the repository, but the setup
wizard's `persist_profile_bundle` call installs it verbatim on an operator setup run. Tracked in
[BUG-039](../bugs/BUG-039-generated-position-offset-false-positive-and-empty-position-world-id-registries.md).

## Reproduction notes

Analysis scripts were ad-hoc and are not committed. The load-bearing facts above can be
re-derived with `flyff_bot.features.client_profiling.pe.PeImage` for section/`.pdata` parsing and
`capstone` (`CS_ARCH_X86 / CS_MODE_64`) for per-function disassembly of the RVAs cited.
