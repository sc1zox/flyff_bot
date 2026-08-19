# Entropia client navigation data extraction (2026-08-19)

Raw static-analysis evidence collected from the operator's local Entropia client for US-048.
Immutable after ingestion. No client file was modified or copied into the repository.

## Fingerprinted live player-coordinate layouts

| Client | Size | PE | SHA-256 | Player global RVA | Pointer | Position |
| --- | ---: | --- | --- | ---: | ---: | --- |
| `Entropia/Entropia/bin32/neuz.exe` | 10,327,552 | i386 | `3446FFEB5D104A68D187E9E2ECFA216E1BDB88CE3F9201A046AA900525B6C07E` | `0x94F698` | 4 bytes | player `+0x188`, 12-byte XYZ float32 |
| `Entropia/Entropia/bin64/neuz.exe` | 12,777,472 | x86-64 | `8079C88F4C4E35A0B5ACD117995125BEE528C175D5B621E0533D85A4458DADA5` | `0xB7C908` | 8 bytes | player `+0x188`, 12-byte XYZ float32 |

For x86, the global is VA `0xD4F698`; the getter at `0x4B6763` loads it. The position
accessor at `0x483EC0` returns player `+0x188`, and caller `0x82D835..0x82D874` copies
offsets 0, 4, and 8.

For x64, the global is VA `0x140B7C908`; the getter is at `0x1400E18E0`. The accessor at
`0x140094800` adds `0x188`, and caller `0x1408D6F97..0x1408D6FC1` copies exactly 12 bytes.
RVA `0x77C908` is not a player pointer in this binary: it lies inside the displacement of a
`CALL` instruction at VA `0x14077C905`.

Both executables report file version `6.0.0.0`, so the version string cannot distinguish the
layouts. The complete SHA-256 is the build identity.

## World and terrain inventory

`Entropia/Entropia/Data/World` contains 16 `.wld`, 14 `.wld.cnt`, 28 `.rgn`, 14 `.dyo`,
154 loose `.lnd`, and 123 `.one` plus 123 `.hdr` archive pairs. The declared `.wld` grids
total 3,861 terrain blocks. Only 153 have a matching loose `.lnd` (3.96%); one further loose
`.lnd` is in a directory without a loose `.wld`.

All 154 loose `.lnd` files decode with this prefix:

```text
int32 little-endian version = 3
int32 little-endian block_x
int32 little-endian block_z
129 * 129 little-endian float32 heights
```

The prefix is 66,576 bytes and observed heights span 0 through 3,300. The complete files are
133,915 through 1,995,599 bytes, proving that height decoding does not consume their other
layers.

`WdEden/WdEden03-02.lnd` is 760,813 bytes. Its height prefix ends at `0x10410`. At
`0xB94A9` an integer count of 29 is followed at `0xB94AD` by 29 contiguous 64-byte records.
The first contains plausible local XYZ `(1.150238, 106.299973, 78.607971)`, three values of
`17.52`, and resource ID 1929. The last contains `(20.067413, 100.0, 61.686371)`, three
values of `8.8`, and ID 1930. This supports an inference of placed object or terrain
metadata, but the field semantics, transforms, and resource mapping are not verified.

The `.wld` scripts provide grid size and metres-per-unit plus world policy, not a navigation
mesh. `WdEden/wdeden.wld` declares size 5 by 5 and MPU 4. The `.wld.cnt` files provide 3D
region polygons and IDs, but do not prove ground passability.

## Spawn, placement, teleport, and model evidence

All 28 `.rgn` files parse into 7,312 `respawn7` zones for 677 distinct monster IDs. Records
include centre X/Y/Z, capacity, respawn interval, and an X/Z rectangle. Eden has 83 zones for
six IDs; Madrigal has 1,875 zones for 356 IDs. These are static spawn priors, not evidence of
current server-side actors.

The common `.dyo` layout begins with a 4-byte count and uses 200-byte records, with position
at offset 16 and a 32-byte name at offset 156. Madrigal has 379 records and 203 names; Eden
has one (`MaEw_Rukas`). Three files do not fit this layout, so format variants exist. The
names do not match the 209 loose `.o3d` names and are not a complete collision index.

`NavPosition.inc` defines four 32 by 32 UI sprites from `ImgNavPos.tga`, centred at 16,16. It
contains no world coordinate or transformation.

`teleport.bin` is 828 bytes, exactly 207 little-endian int32 values: sentinel `-1`, option
IDs 0 through 85, and seven groups of IDs. It contains no names, world IDs, XYZ, cost,
access requirement, or cooldown. Executable strings include `%sTeleportOption.inc`,
`AddTeleportOptions`, `/teleport %d %f %f`, and `/teleport "%s"`; no loose
`TeleportOption.inc` exists. These strings do not prove that the server will accept a given
destination.

`Data/MasqueradePre.prj` references missing loose `mdlObj.inc`, `world.inc`, and
`terrain.inc`. Without those indices, `.lnd` resource IDs and world/model mappings are not
resolved. Render meshes also cannot be assumed to equal physics collision.

## Reliability boundary

The strongest available authorities are a hash-matched live XYZ sample, `.wld` grid/MPU,
and decoded loose `.lnd` heights. `.rgn`, `.wld.cnt`, `.dyo`, illustrated monster maps, and
compiled resource-path strings are useful but static or incomplete.

Unresolved inputs include roughly 96% of declared terrain blocks, collision hulls and flags,
model/world/terrain ID mappings, teleport requirements and destinations, current world ID,
doors/scripts, dynamic actors, and server state. Build changes, loading transitions, latency,
and client/server physics remain runtime uncertainties. The evidence supports closed-loop
navigation with live confirmation, bounded recovery, fallback, and abort; it cannot support a
literal guarantee of 100% fault-free autonomous navigation.
