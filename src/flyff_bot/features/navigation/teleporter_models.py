"""Typed teleporter destinations extracted from the client's own declarations."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TeleporterDestination:
    """One destination the client's teleporter can request."""

    destination_id: int
    name: str
    search_text: str
    world_id: int
    anchor_x: float = 0.0
    anchor_z: float = 0.0
    description: str = ""
    minimum_level: int = 0
    maximum_level: int | None = None
    category: str = "general"

    def __post_init__(self) -> None:
        if self.destination_id < 0:
            raise ValueError("A teleporter destination ID cannot be negative.")
        if not self.name:
            raise ValueError("A teleporter destination must have a name.")
        if not self.search_text:
            raise ValueError("A teleporter destination must have searchable text.")
        if self.world_id < 0:
            raise ValueError("A teleporter world ID cannot be negative.")
        if not math.isfinite(self.anchor_x) or not math.isfinite(self.anchor_z):
            raise ValueError("A teleporter anchor must have finite coordinates.")
        if self.minimum_level < 0:
            raise ValueError("A teleporter minimum level cannot be negative.")
        if self.maximum_level is not None and self.maximum_level < self.minimum_level:
            raise ValueError("A teleporter maximum level cannot precede its minimum level.")


@dataclass(frozen=True, slots=True)
class TeleporterCatalog:
    """Destinations declared by one readable client asset."""

    destinations: tuple[TeleporterDestination, ...]

    def __post_init__(self) -> None:
        identifiers = {destination.destination_id for destination in self.destinations}
        if len(identifiers) != len(self.destinations):
            raise ValueError("Teleporter destination IDs must be unique.")

    def find_exact(self, name: str) -> TeleporterDestination | None:
        """Return a destination by its case-insensitive display or search text."""

        normalized = name.casefold()
        return next(
            (
                destination
                for destination in self.destinations
                if destination.name.casefold() == normalized
                or destination.search_text.casefold() == normalized
            ),
            None,
        )
