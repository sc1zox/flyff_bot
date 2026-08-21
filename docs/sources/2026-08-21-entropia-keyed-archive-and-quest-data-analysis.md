# Entropia keyed archive format and quest data static analysis (2026-08-21)

Local static analysis of the operator's unmodified Entropia PServer client for US-061. Collected
2026-08-21 by repository maintainers from the local installation. No process was started, no client
file was modified, and no client binary or asset is included in this repository.

## Two archive generations ship side by side

Every packed client directory holds `<name>.hdr` (index) plus `<name>.one` (payload). Two index
layouts exist across the installation, distinguished by the first field after the entry count:

| Generation | Index record | Payload key | Regions/directories |
| --- | --- | --- | --- |
| Name-keyed (US-052) | `int32 name_length`, identity, `int32 offset`, `int32 size` | plain file name | 718 `.hdr` files |
| Keyed (this source) | `int32 -1`, `int32 name_length`, identity, `int32 -offset`, `int32 size` | derived, see below | 663 `.hdr` files |

US-052 reported the second layout as `UNSUPPORTED_ARCHIVE_INDEX` and skipped it. All quest data —
`Data/System2/data1..3.one` — is in that second generation, as are 25 world regions.

In the keyed layout the offset field stores the negated absolute start of the entry, and the size
field stores the file length minus 10. Entries are laid out contiguously: for every archive checked,
`sum(size) + 10 * entry_count` equals the exact `.one` file size.

## Index identity is a salted digest of the file name

The 64-character identity is not the file name and not a plain hash of it:

```text
identity(name) = sha256("m1k3d3RS945TI!" + name.lower()).hexdigest()
```

The salt is a literal in `neuz.exe`, stored immediately after the `.one` / `.hdr` extension
strings (x86 image, string block near offset `0x88F4E0`). A second literal,
`m3ntu5d3rHur3ns00hn`, sits beside the `.res` / `.hdr` pair and is the salt the *name-keyed*
world archives use; both were confirmed against known entries.

This makes a keyed archive name-addressable: an entry is found by digesting its file name, instead
of by the US-052 known-plaintext-prefix search.

## Keyed payload transform

Entry bytes are obfuscated with a position-advancing keystream seeded from the file name's
adjacent-character XOR and the file's own length:

```text
n         = len(name)                                   # lower-case file name
seed      = (length - 1 + (name[i % n] ^ name[(i + 1) % n]) + i) & 0xFF
stored[i] = swap_nibbles(plain[i]) ^ seed
```

`length` is the entry's full byte length (index `size` + 10). The name index wraps, so the last
character is mixed with the first. Because `swap_nibbles` and XOR are their own inverses, decoding
uses the same expression.

### How it was derived

1. XORing two same-size entries of one archive cancels the keystream, showing it depends on byte
   position rather than on content — and that entries of one archive share a keystream except where
   their names differ, with the difference repeating at `len(name)`.
2. Three files exist both loose on disk and packed at exactly `size + 10` bytes
   (`wdverux.dyo`, `wdverux.wld`, `wdverux.txt.txt`), giving exact keystreams. `ks[i] - i` is
   perfectly periodic at `len(name)` across the whole 11,004-byte `.dyo`.
3. Comparing files with shared name prefixes isolated `d[j] = C + (name[j] ^ name[(j+1) % n])`.
4. Across 53 loose/packed pairs, `C - (index size & 0xFF)` is the constant `0x09`, i.e.
   `C = (length - 1) & 0xFF`.

### Verification

Decoding was checked against every loose file that matches its packed entry byte-for-byte:
**55 exact round-trips**. A further 20 loose files decode into valid headers (`DDS `, O3D, UTF-16
`.rgn`, `// World`) but differ in content — those are newer patched copies of an older packed
version, which is exactly what the client's loose-file preference implies.

## Quest data reachable through the keyed archives

| File | Archive | Bytes | Content |
| --- | --- | ---: | --- |
| `propQuest.inc` | `System2/data2.one` | 4,087,308 | UTF-16 quest script, 1,151 titles |
| `propQuest-RequestBox.inc` | `System2/data2.one` | 851,204 | request-board quests |
| `propQuest-Scenario.inc` | `System2/data2.one` | 242,566 | scenario quests |
| `propQuest-RequestBox2.inc` | `System2/data1.one` | 21,802 | request-board quests |
| `propQuest-DungeonandPK.inc` | `System2/data2.one` | 183,298 | dungeon and PvP quests |
| `propMover.txt` | `System2/data1.one` | 1,293,479 | `MI_*` to `IDS_PROPMOVER_TXT_*` |
| `Spec_Item.txt` | `System2/data3.one` | 28,614,568 | `II_*` to `IDS_PROPITEM_TXT_*` |
| `propQuest*.txt.txt` | `System2/Lang/<Language>/<language>.one` | — | localized quest text |
| `propMover.txt.txt`, `propItem.txt.txt` | same | — | localized monster and item names |

`masquerade.prj` is loose on disk and declares the quest script names, so the whole set is
addressable without enumerating the opaque index.

## Quest script grammar actually used

`<identifier> { SetTitle( IDS ); setting { ... } state N { ... } }`, where a bare-number identifier
is a quest *group* heading rather than a quest. The calls a farming session can act on:

- `SetEndCondKillNPC( flag, MI_SYMBOL | numeric_id, count [, x, z, destination ] )` — the fourth and
  fifth arguments are world coordinates of the objective, and both symbolic and numeric monster
  identifiers occur.
- `SetEndCondItem( a, b, c, II_SYMBOL, count [, ... ] )` paired with
  `QuestItem( MI_SYMBOL, II_SYMBOL, drop_rate, count )` declaring which monsters drop it.
- `SetBeginCondLevel( minimum, maximum )`, `SetHeadQuest( group_id )`, `SetCond( IDS )`,
  `SetEndRewardItem/Gold/Exp`.

The client does not ship the `MI_*` to numeric monster-id table; those constants are compiled into
`neuz.exe`. Spawn zones are therefore resolved by monster display name, by the numeric identifier
when a quest states one directly, and by proximity to the quest's own stated coordinates.

## Extraction result against this installation

`uv run python -m flyff_bot --extract-quests` produced 1,434 quests, 563 of them farmable, in a
971 KB `data/quests/quests.json`, with no extraction diagnostics.
