# ADR-003: Clean code and schema simplicity over legacy backward compatibility

- Status: accepted
- Date: 2026-08-18
- Related stories: [US-036](../user-stories/US-036-navigation-profile-anchoring-across-sessions.md)

## Context

Earlier iterations of persistence schemas (such as `SpatialMap` schema version 1) were created
prior to measured minimap odometry ([US-035](../user-stories/completed/US-035-measured-minimap-odometry-and-tracking-quality.md)).
They used arbitrary dead-reckoning coordinates without spatial anchoring, zoom level, or physical scale.

Retaining compatibility layers, multi-version loaders, and read-only legacy shims for experimental
or obsolete prototypes increases complexity, expands API surface, and complicates invariants across the
navigation pipeline.

## Decision

Prioritize clean code, clear invariants, and strict validation over backward compatibility for obsolete
data formats.

1. Do not build or maintain backward compatibility shims for pre-odometry artifacts (such as schema v1 profiles).
2. Schema version 2 is the single authoritative spatial map format. Profiles with outdated or mismatched
   schema versions are rejected explicitly with a clear error rather than loaded through fallback paths.
3. Obsolete migration branches and compatibility layers are deleted (per `AGENTS.md`: "Delete obsolete paths
   after a verified migration").

## Alternatives

- **Support legacy v1 profiles as unanchored read-only maps:** Rejected because it introduces permanent
  dual-mode execution paths, dead-reckoning legacy code, and untested edge cases for files that lack physical
  scale.
- **Automatic mathematical migration from v1 to v2:** Rejected because v1 coordinates carry no physical
  ground truth and cannot be soundly remapped to minimap pixels.

## Consequences

- The navigation persistence and controller code stays lean, maintainable, and free of legacy branches (KISS, YAGNI).
- Profiles created with pre-odometry prototypes are invalid and must be newly recorded.
- Automated tests only need to verify the active schema format and strict rejection of invalid schemas.

## Verification

Persistence tests verify schema version 2 serialization and assert that unsupported schema versions
raise clear, handled validation errors.
