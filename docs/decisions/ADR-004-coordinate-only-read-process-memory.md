# ADR-004: Fingerprinted, coordinate-only read access to the Flyff client

- Status: accepted
- Date: 2026-08-19
- Related story: [US-048](../user-stories/completed/US-048-3d-world-navigation-teleport-dispatch-and-terrain-aware-pathing.md)
- Evidence: [Entropia client navigation data extraction](../sources/2026-08-19-entropia-client-navigation-data-extraction.md)

## Context

US-048 needs drift-free live world coordinates. The local Entropia x86 and x64 clients have
different player-global addresses despite sharing file version 6.0.0.0. Broad memory scans,
game-state reads, writes, injection, and hooks are outside the project's safety boundary.

## Decision

1. Identify a supported client only by its complete SHA-256 fingerprint.
2. Resolve the player pointer from the one verified module-relative global for that fingerprint.
3. Read exactly the pointer width, then exactly the 12-byte player XYZ float32 struct at player
   offset `0x188`.
4. Open the process with `PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ` only.
5. Do not scan memory, follow any other pointer, read actors or state, write memory, inject code,
   hook functions, or add stealth/evasion behavior.
6. On any process, build, handle, short-read, or malformed-value failure, close the handle and
   expose minimap fallback. Polling may retry so a restarted supported client can recover.
7. Emergency stop and application teardown close the handle idempotently.

## Alternatives

- **Absolute addresses:** rejected because ASLR makes module-relative addresses necessary.
- **Version-string profiles:** rejected because both verified binaries report 6.0.0.0.
- **Signature or memory scanning:** rejected as broader and less auditable than two exact reads.
- **Minimap-only positioning:** retained as fallback, but rejected as primary because it drifts
  across long runs and cannot confirm teleport completion.

## Consequences

- Supported local builds have a small, testable memory boundary.
- Unknown or changed builds remain amber/minimap-only until a new static profile is verified.
- A green GPS indicator means the configured supported build returned finite XYZ; it does not
  claim the terrain, collision model, server state, or intended world is infallible.
