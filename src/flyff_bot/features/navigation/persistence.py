"""Disk persistence for learned navigation graphs and spawn heatmaps."""

from __future__ import annotations

import json
from pathlib import Path

from flyff_bot.features.navigation.spatial import SpatialMap, SpatialMapConfig

JSON_INDENT_SPACES = 2


def save_spatial_map(spatial_map: SpatialMap, path: Path) -> None:
    """Write the learned map so a later session can restore it."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(spatial_map.to_dict(), indent=JSON_INDENT_SPACES, sort_keys=True),
        encoding="utf-8",
    )


def load_spatial_map(path: Path, config: SpatialMapConfig | None = None) -> SpatialMap:
    """Restore a learned map, returning an empty one when no snapshot exists yet."""

    if not path.is_file():
        return SpatialMap(config)
    return SpatialMap.from_dict(json.loads(path.read_text(encoding="utf-8")), config)
