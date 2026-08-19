"""Disk persistence and profile management for learned navigation graphs and spawn heatmaps."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from flyff_bot.features.navigation.anchoring import MapAnchor
from flyff_bot.features.navigation.spatial import SpatialMap, SpatialMapConfig, WorldPoint

JSON_INDENT_SPACES = 2
DEFAULT_NAVIGATION_DIR = Path("data/navigation")
INVALID_FILENAME_CHARS = frozenset(r'\/:*?"<>|')
PROFILE_ANCHOR_KEY = "anchor"
PROFILE_SPAWN_POINT_KEY = "spawn_point"
SPAWN_POINT_X_KEY = "x"
SPAWN_POINT_Y_KEY = "y"
# Named so the handlers below stay single-name `except` clauses. The pinned formatter
# rewrites an inline `except (A, B):` into invalid Python, and a named tuple also says
# what the group of failures means.
PROFILE_READ_ERRORS = (json.JSONDecodeError, OSError, UnicodeDecodeError, ValueError, TypeError)
SPAWN_POINT_FIELD_ERRORS = (KeyError, ValueError, TypeError)


@dataclass(frozen=True, slots=True)
class NavigationProfile:
    """One persisted map profile: the learned map, its landmark, and its spawn anchor."""

    spatial_map: SpatialMap
    anchor: MapAnchor | None = None
    # The town or respawn point an emergency teleport arrives at, in this profile's own
    # coordinate frame. ``None`` means the operator mapped none for this map (US-040).
    spawn_point: WorldPoint | None = None


@dataclass(frozen=True, slots=True)
class NavigationProfileSummary:
    """Metadata summary of one persisted map profile on disk."""

    name: str
    path: Path
    cell_count: int


def sanitize_profile_name(name: str) -> str:
    """Strip invalid Windows filename characters, extra whitespace, and trailing extension."""

    cleaned = "".join(c for c in name if c not in INVALID_FILENAME_CHARS)
    cleaned = cleaned.strip()
    if cleaned.lower().endswith(".json"):
        cleaned = cleaned[:-5].rstrip()
    return cleaned


def count_cells_in_profile(path: Path) -> int:
    """Return the number of cells recorded in a map file, or 0 if unreadable."""

    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("cells"), list):
            return len(data["cells"])
    except PROFILE_READ_ERRORS:
        pass
    return 0


def list_navigation_profiles(
    directory: Path = DEFAULT_NAVIGATION_DIR,
) -> list[NavigationProfileSummary]:
    """Scan and return all map profiles in the target directory."""

    if not directory.is_dir():
        return []
    profiles: list[NavigationProfileSummary] = []
    for file_path in sorted(directory.glob("*.json")):
        if file_path.is_file():
            profiles.append(
                NavigationProfileSummary(
                    name=file_path.name,
                    path=file_path,
                    cell_count=count_cells_in_profile(file_path),
                )
            )
    return profiles


def save_profile(profile: NavigationProfile, path: Path) -> None:
    """Write the learned map and its landmark so a later session can restore both."""

    document = profile.spatial_map.to_dict()
    if profile.anchor is not None:
        document[PROFILE_ANCHOR_KEY] = profile.anchor.to_dict()
    if profile.spawn_point is not None:
        document[PROFILE_SPAWN_POINT_KEY] = {
            SPAWN_POINT_X_KEY: profile.spawn_point.x,
            SPAWN_POINT_Y_KEY: profile.spawn_point.y,
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=JSON_INDENT_SPACES, sort_keys=True),
        encoding="utf-8",
    )


def load_profile(path: Path, config: SpatialMapConfig | None = None) -> NavigationProfile:
    """Restore a profile, returning an empty unanchored one when no snapshot exists yet.

    An unsupported schema version or an unreadable map is an explicit failure (ADR-003), but
    a corrupted anchor record only costs the profile its landmark: it then loads unanchored,
    exactly as one saved while tracking was degraded does (US-036). An unreadable spawn
    anchor is treated the same way and only costs the profile its mapped spawn point.
    """

    if not path.is_file():
        return NavigationProfile(SpatialMap(config))
    document: object = json.loads(path.read_text(encoding="utf-8"))
    spatial_map = SpatialMap.from_dict(document, config)
    anchor: MapAnchor | None = None
    if isinstance(document, dict) and PROFILE_ANCHOR_KEY in document:
        try:
            anchor = MapAnchor.from_dict(document[PROFILE_ANCHOR_KEY])
        except ValueError:
            anchor = None
    spawn_point: WorldPoint | None = None
    if isinstance(document, dict):
        spawn_point = _spawn_point_from(document.get(PROFILE_SPAWN_POINT_KEY))
    return NavigationProfile(spatial_map, anchor, spawn_point)


def _spawn_point_from(value: object) -> WorldPoint | None:
    """Read one stored spawn anchor, or return ``None`` when it is absent or unusable."""

    if not isinstance(value, dict):
        return None
    try:
        return WorldPoint(float(value[SPAWN_POINT_X_KEY]), float(value[SPAWN_POINT_Y_KEY]))
    except SPAWN_POINT_FIELD_ERRORS:
        return None
