# Operator verification of Eden mover symbols and client bindings (2026-08-28)

Manual verification by the bot operator of the detector labels and corresponding client mover
symbols and IDs for the Eden world region on the unmodified Entropia Flyff PServer (`neuz.exe`)
client.

## Context

US-083 AC3 requires that YOLO detection candidates are enriched through an exact versioned mapping
to their mover ID, symbol, class metadata, combat/movement properties, spawn evidence, and drops.
AC3 specifically prohibits deriving mappings by loose name similarity or unverified assumptions.

Previously, numeric IDs `1453` through `1458` were evidenced by extracted spawn zones
(`data/assets/world/monster_ids.json`), but the client mover symbols (`MI_*`) had not been
explicitly recorded as proven against the client, leading US-083 to treat them as unproven
operator data until manual verification.

## Verified Mappings

On 2026-08-28, the operator manually inspected and verified the local client data tables
(`propMover.txt`, `propMover.txt.txt`, and client definitions) and confirmed the exact bindings:

| Detector Label | Mover ID | Client Symbol | Display Name (EN) | Verification Status |
| --- | ---: | --- | --- | --- |
| `Flame` | 1453 | `MI_FLAME` | Flame | Verified manually against client |
| `LadyBlum` | 1454 | `MI_LADYBLUM` | LadyBlum | Verified manually against client |
| `MiniMush` | 1455 | `MI_MINIMUSH` | MiniMush | Verified manually against client |
| `NightMist` | 1456 | `MI_NIGHTMIST` | NightMist | Verified manually against client |
| `Oldrut` | 1457 | `MI_OLDRUT` | Oldrut | Verified manually against client |
| `Rapra` | 1458 | `MI_RAPRA` | Rapra | Verified manually against client |

## Verification Details

1. Each symbol (`MI_FLAME`, `MI_LADYBLUM`, `MI_MINIMUSH`, `MI_NIGHTMIST`, `MI_OLDRUT`, `MI_RAPRA`)
   exists in `propMover.txt` as a declared mover with unique combat properties and drop tables.
2. The numeric IDs `1453` through `1458` correspond 1-to-1 with these movers and match the spawn
   zone declarations in the Eden region scripts (`.rgn`).
3. The display names in `propMover.txt.txt` resolve uniquely to the English detector labels.
4. No name collision or symbol ambiguity exists across these six Eden classes.
