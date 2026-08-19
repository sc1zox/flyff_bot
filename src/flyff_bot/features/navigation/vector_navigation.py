"""Goal-driven navigation over an extracted world vector map.

The extracted map speaks client world units; every position the session measures is a
minimap pixel relative to wherever it started (US-035). :class:`WorldRegistration` is the one
place those two frames meet. It carries no rotation, because the minimap is north-up and the
client's ground plane is axis-aligned, and it recovers its translation from a single stated
correspondence: the operator names the spawn zone the character is standing in, and the
position measured at that moment becomes that zone's anchor.

What the registration cannot measure is its scale. Deriving minimap pixels per world unit
would need a run speed the client does not display, exactly as US-035 records for every other
world-unit conversion, so the scale is a named provisional constant the operator can correct
rather than a fitted quantity presented as one.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from flyff_bot.features.navigation.spatial import WorldPoint
from flyff_bot.features.navigation.vector_routing import (
    VectorRouteConfig,
    VectorRoutePlanner,
)
from flyff_bot.features.navigation.world_extractor import (
    VectorSpawnZone,
    WorldCoordinate,
    WorldVectorMap,
    nearest_zone,
)

# Minimap pixels covered by one client world unit. This is an operator-correctable estimate,
# not a measurement: no recorded quantity relates the two units, so it is named here rather
# than buried as a literal, exactly like the provisional spawn-distance constants.
PROVISIONAL_MINIMAP_PIXELS_PER_WORLD_UNIT = 1.0

# The minimap is drawn north-up and the client's z axis grows northwards, so one world z
# increase and one session y increase point the same way (US-035 defines session +y as north).
WORLD_NORTH_AXIS_SIGN = 1.0

# Patrol stations are pulled this far in from the zone's bounding rectangle, as a fraction of
# its half-extent, so a sweep of the zone never rides its outer edge.
ZONE_PATROL_INSET_FRACTION = 0.6
# A zone smaller than this in world units is swept from its anchor alone; ringing it would
# only produce waypoints inside each other's arrival radius.
MINIMUM_PATROL_RING_EXTENT_UNITS = 8.0


@dataclass(frozen=True, slots=True)
class WorldRegistration:
    """The affine map between client world coordinates and session minimap pixels."""

    origin: WorldCoordinate
    pixels_per_world_unit: float = PROVISIONAL_MINIMAP_PIXELS_PER_WORLD_UNIT

    def __post_init__(self) -> None:
        if self.pixels_per_world_unit <= 0.0:
            raise ValueError("Minimap pixels per world unit must be positive.")

    @classmethod
    def anchored(
        cls,
        session_position: WorldPoint,
        world_position: WorldCoordinate,
        pixels_per_world_unit: float = PROVISIONAL_MINIMAP_PIXELS_PER_WORLD_UNIT,
    ) -> WorldRegistration:
        """Return the registration that puts one measured position at one world position."""

        if pixels_per_world_unit <= 0.0:
            raise ValueError("Minimap pixels per world unit must be positive.")
        return cls(
            WorldCoordinate(
                world_position.x - session_position.x / pixels_per_world_unit,
                world_position.z
                - session_position.y / (pixels_per_world_unit * WORLD_NORTH_AXIS_SIGN),
            ),
            pixels_per_world_unit,
        )

    def to_session(self, point: WorldCoordinate) -> WorldPoint:
        """Return one world position expressed in this session's minimap-pixel frame."""

        return WorldPoint(
            (point.x - self.origin.x) * self.pixels_per_world_unit,
            (point.z - self.origin.z) * self.pixels_per_world_unit * WORLD_NORTH_AXIS_SIGN,
        )

    def to_world(self, point: WorldPoint) -> WorldCoordinate:
        """Return one measured session position expressed in client world coordinates."""

        return WorldCoordinate(
            self.origin.x + point.x / self.pixels_per_world_unit,
            self.origin.z + point.y / (self.pixels_per_world_unit * WORLD_NORTH_AXIS_SIGN),
        )

    def to_session_distance(self, units: float) -> float:
        """Return one world-unit distance expressed in minimap pixels."""

        return units * self.pixels_per_world_unit


@dataclass(frozen=True, slots=True)
class ZoneGoal:
    """One monster class to farm and, optionally, the kill count that completes it."""

    monster_name: str
    kill_quota: int | None = None

    def __post_init__(self) -> None:
        if not self.monster_name.strip():
            raise ValueError("A zone goal must name a monster class.")
        if self.kill_quota is not None and self.kill_quota <= 0:
            raise ValueError("A zone goal's kill quota must be positive when it is set.")


@dataclass(frozen=True, slots=True)
class VectorNavigationPlan:
    """One planned vector route with the goal and zone it was planned for."""

    points: tuple[WorldPoint, ...] = ()
    goal: ZoneGoal | None = None
    zone: VectorSpawnZone | None = None
    # True when every remaining leg was obstructed, so the caller falls back to learned
    # pathing rather than steering into terrain the visibility graph could not route around.
    blocked: bool = False

    @property
    def is_empty(self) -> bool:
        """Return whether this plan requires no movement."""

        return not self.points


@dataclass(frozen=True, slots=True)
class ZoneSelection:
    """The zone the session is currently bound to and why it was chosen."""

    goal: ZoneGoal
    zone: VectorSpawnZone


@dataclass
class _GoalProgress:
    """Mutable per-monster kill tally behind the quota check."""

    kills: dict[str, int] = field(default_factory=dict)

    def record(self, monster_name: str) -> int:
        """Add one kill for a monster class and return its new total."""

        total = self.kills.get(monster_name, 0) + 1
        self.kills[monster_name] = total
        return total

    def count(self, monster_name: str) -> int:
        """Return how many kills have been attributed to a monster class."""

        return self.kills.get(monster_name, 0)


class VectorZoneNavigator:
    """Bind farming goals to extracted spawn zones and route between them.

    The navigator owns three decisions: which goal is still unfinished, which of that
    monster's zones the session should be in, and what obstacle-free polyline leads there.
    It measures nothing and dispatches nothing; positions are handed to it and routes are
    handed back in the session's own minimap-pixel frame.
    """

    def __init__(
        self,
        world_map: WorldVectorMap,
        registration: WorldRegistration,
        *,
        goals: Iterable[ZoneGoal] = (),
        route_config: VectorRouteConfig | None = None,
    ) -> None:
        self._map = world_map
        self._registration = registration
        self._planner = VectorRoutePlanner(world_map.obstacles, route_config)
        self._goals: tuple[ZoneGoal, ...] = tuple(goals)
        self._progress = _GoalProgress()
        self._selection: ZoneSelection | None = None

    @property
    def world_map(self) -> WorldVectorMap:
        """Return the extracted map this navigator routes over."""

        return self._map

    @property
    def registration(self) -> WorldRegistration:
        """Return the world-to-session frame registration in force."""

        return self._registration

    @property
    def route_planner(self) -> VectorRoutePlanner:
        """Return the visibility-graph planner backing every route."""

        return self._planner

    @property
    def goals(self) -> tuple[ZoneGoal, ...]:
        """Return the configured farming goals in the order they are worked through."""

        return self._goals

    @property
    def active_goal(self) -> ZoneGoal | None:
        """Return the first goal whose quota is not yet satisfied."""

        for goal in self._goals:
            if not self.is_complete(goal):
                return goal
        return None

    @property
    def active_zone(self) -> VectorSpawnZone | None:
        """Return the spawn zone the session is currently bound to."""

        selection = self._selection
        return selection.zone if selection is not None else None

    @property
    def is_active(self) -> bool:
        """Return whether an unfinished goal has at least one extracted zone to work in."""

        goal = self.active_goal
        return goal is not None and bool(self._map.zones_for(goal.monster_name))

    def set_goals(self, goals: Iterable[ZoneGoal]) -> None:
        """Replace the goal list and drop the zone selection made for the previous one."""

        self._goals = tuple(goals)
        self._selection = None

    def kills(self, monster_name: str) -> int:
        """Return how many kills have been attributed to one monster class."""

        return self._progress.count(monster_name)

    def is_complete(self, goal: ZoneGoal) -> bool:
        """Return whether a goal's kill quota has been reached."""

        return (
            goal.kill_quota is not None
            and self._progress.count(goal.monster_name) >= goal.kill_quota
        )

    def record_kill(self, monster_name: str) -> bool:
        """Attribute one confirmed kill and report whether it completed the active goal.

        Completing a goal drops the zone selection, so the next plan binds to the nearest
        zone of the next unfinished monster without the session being restarted.
        """

        previous = self.active_goal
        self._progress.record(monster_name)
        if previous is not None and self.is_complete(previous):
            self._selection = None
            return True
        return False

    def select_zone(self, position: WorldPoint) -> ZoneSelection | None:
        """Bind the session to the active goal's zone nearest one measured position.

        The selection is sticky: once bound, the session keeps working that zone until its
        goal completes or the goals change, so a route in progress is never abandoned merely
        because the character drifted closer to a neighbouring zone.
        """

        goal = self.active_goal
        if goal is None:
            return None
        selection = self._selection
        if selection is not None and selection.goal == goal:
            return selection
        zones = self._map.zones_for(goal.monster_name)
        chosen = nearest_zone(zones, self._registration.to_world(position))
        if chosen is None:
            return None
        self._selection = ZoneSelection(goal, chosen)
        return self._selection

    def plan_route(self, position: WorldPoint) -> VectorNavigationPlan:
        """Return the obstacle-free route the active goal wants walked from here."""

        selection = self.select_zone(position)
        if selection is None:
            return VectorNavigationPlan()
        origin = self._registration.to_world(position)
        stations = self._stations(selection.zone, origin)
        points: list[WorldPoint] = []
        blocked = False
        current = origin
        for station in stations:
            leg = self._planner.plan(current, station)
            if leg.blocked or leg.is_empty:
                blocked = blocked or leg.blocked
                continue
            points.extend(self._registration.to_session(point) for point in leg.waypoints)
            current = station
        return VectorNavigationPlan(
            tuple(points), selection.goal, selection.zone, blocked and not points
        )

    def zone_contains(self, position: WorldPoint) -> bool:
        """Return whether a measured position lies inside the bound zone's rectangle."""

        zone = self.active_zone
        if zone is None:
            return False
        return zone.contains(self._registration.to_world(position))

    def _stations(
        self, zone: VectorSpawnZone, origin: WorldCoordinate
    ) -> tuple[WorldCoordinate, ...]:
        """Return the patrol stations of one zone, starting with the one nearest the origin.

        A zone is the patrol boundary rather than a single destination, so the route sweeps
        an inset ring of it. Starting at the nearest station keeps the approach from crossing
        the whole zone before the sweep begins.
        """

        ring = _patrol_ring(zone)
        if len(ring) < 2:
            return ring
        nearest_index = min(
            range(len(ring)),
            key=lambda index: math.hypot(ring[index].x - origin.x, ring[index].z - origin.z),
        )
        return ring[nearest_index:] + ring[:nearest_index]


def _patrol_ring(zone: VectorSpawnZone) -> tuple[WorldCoordinate, ...]:
    """Return the inset corner ring one zone is swept along."""

    anchor = zone.anchor
    half_width = (zone.maximum_x - zone.minimum_x) / 2.0 * ZONE_PATROL_INSET_FRACTION
    half_depth = (zone.maximum_z - zone.minimum_z) / 2.0 * ZONE_PATROL_INSET_FRACTION
    if (
        half_width < MINIMUM_PATROL_RING_EXTENT_UNITS
        and half_depth < MINIMUM_PATROL_RING_EXTENT_UNITS
    ):
        return (anchor,)
    return (
        WorldCoordinate(anchor.x - half_width, anchor.z - half_depth),
        WorldCoordinate(anchor.x + half_width, anchor.z - half_depth),
        WorldCoordinate(anchor.x + half_width, anchor.z + half_depth),
        WorldCoordinate(anchor.x - half_width, anchor.z + half_depth),
    )


@dataclass(frozen=True, slots=True)
class VectorNavigationRequest:
    """Everything an operator states before an extracted map may steer a session.

    The one thing it deliberately does not carry is where the character is: the frame
    registration is only valid against a position measured at the moment it is applied, so
    the caller supplies that when it turns this request into a navigator.
    """

    world_map: WorldVectorMap
    anchor_zone: VectorSpawnZone
    goals: tuple[ZoneGoal, ...] = ()
    pixels_per_world_unit: float = PROVISIONAL_MINIMAP_PIXELS_PER_WORLD_UNIT
    route_config: VectorRouteConfig | None = None

    def navigator(self, session_position: WorldPoint) -> VectorZoneNavigator:
        """Return the navigator this request describes, registered at one live position."""

        registration = WorldRegistration.anchored(
            session_position, self.anchor_zone.anchor, self.pixels_per_world_unit
        )
        return VectorZoneNavigator(
            self.world_map,
            registration,
            goals=self.goals,
            route_config=self.route_config,
        )


def zone_goals_from_selection(
    monster_names: Sequence[str], quotas: Sequence[int | None] | None = None
) -> tuple[ZoneGoal, ...]:
    """Return goals for a monster selection, pairing each name with its optional quota."""

    if quotas is not None and len(quotas) != len(monster_names):
        raise ValueError("Each selected monster needs exactly one quota entry.")
    resolved = quotas if quotas is not None else [None] * len(monster_names)
    return tuple(ZoneGoal(name, quota) for name, quota in zip(monster_names, resolved, strict=True))
