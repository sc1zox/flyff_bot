"""Typed operator intent for a bounded, NavMesh-only navigation test."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from flyff_bot.features.navigation.live_position import WorldPosition

if TYPE_CHECKING:
    from flyff_bot.features.navigation.navmesh import BakedNavMesh


@dataclass(frozen=True, slots=True)
class NavigationTestRequest:
    """One map-selected destination, optionally associated with an extracted spawn zone."""

    target: WorldPosition
    zone_identifier: int | None = None
    navmesh: BakedNavMesh | None = None
