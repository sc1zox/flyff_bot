"""GPS-only goal-driven navigation over an extracted world vector map."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.terrain_routing import (
    TerrainRouteConfig,
    TerrainRoutePlanner,
    TerrainWaypoint,
)
from flyff_bot.features.navigation.world_extractor import (
    VectorSpawnZone,
    WorldCoordinate,
    WorldVectorMap,
    nearest_zone,
)

# Patrol stations are pulled this far in from the zone's bounding rectangle, as a fraction of
# its half-extent, so a sweep of the zone never rides its outer edge.
ZONE_PATROL_INSET_FRACTION = 0.6
# A zone smaller than this in world units is swept from its anchor alone; ringing it would
# only produce waypoints inside each other's arrival radius.
MINIMUM_PATROL_RING_EXTENT_UNITS = 8.0


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

    points: tuple[WorldCoordinate, ...] = ()
    goal: ZoneGoal | None = None
    zone: VectorSpawnZone | None = None
    # True when every remaining leg was obstructed, so the caller blocks rather than steering
    # into terrain the planner could not route around.
    blocked: bool = False
    world_waypoints: tuple[TerrainWaypoint, ...] = ()

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
    It measures nothing and dispatches nothing; live client GPS positions are handed to it and
    routes are returned in that same client world-coordinate frame.
    """

    def __init__(
        self,
        world_map: WorldVectorMap,
        *,
        goals: Iterable[ZoneGoal] = (),
        preferred_zone: VectorSpawnZone | None = None,
        preferred_zones: Iterable[VectorSpawnZone] = (),
        terrain_config: TerrainRouteConfig | None = None,
    ) -> None:
        self._map = world_map
        self._terrain_planner = TerrainRoutePlanner(world_map, terrain_config)
        self._terrain_samples = world_map.terrain.samples()
        self._goals: tuple[ZoneGoal, ...] = tuple(goals)
        self._progress = _GoalProgress()
        self._selection: ZoneSelection | None = None
        zones_list = list(preferred_zones)
        if preferred_zone is not None and preferred_zone not in zones_list:
            zones_list.insert(0, preferred_zone)
        self._preferred_zones: tuple[VectorSpawnZone, ...] = tuple(zones_list)
        self._active_zone_index: int = 0

    @property
    def world_map(self) -> WorldVectorMap:
        """Return the extracted map this navigator routes over."""

        return self._map

    @property
    def terrain_samples(self) -> tuple[tuple[float, float, float], ...]:
        """Return cached topographic samples for the 10 Hz inspector feed."""

        return self._terrain_samples

    @property
    def goals(self) -> tuple[ZoneGoal, ...]:
        """Return the configured farming goals in the order they are worked through."""

        return self._goals

    @property
    def preferred_zones(self) -> tuple[VectorSpawnZone, ...]:
        """Return all user-selected preferred spawn zones."""

        return self._preferred_zones

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
        if selection is not None:
            return selection.zone
        if self._preferred_zones:
            return self._preferred_zones[self._active_zone_index % len(self._preferred_zones)]
        return None

    @property
    def configured_zone(self) -> VectorSpawnZone | None:
        """Return the operator-selected zone before the first GPS route binds it."""

        if self.active_zone is not None:
            return self.active_zone
        if self._preferred_zones:
            index = min(self._active_zone_index, len(self._preferred_zones) - 1)
            return self._preferred_zones[index]
        return None

    @property
    def is_active(self) -> bool:
        """Return whether an unfinished goal has at least one extracted zone to work in."""

        goal = self.active_goal
        if goal is not None and bool(self._map.zones_for(goal.monster_name)):
            return True
        return bool(self._preferred_zones)

    def set_goals(self, goals: Iterable[ZoneGoal]) -> None:
        """Replace the goal list and drop the zone selection made for the previous one."""

        self._goals = tuple(goals)
        self._selection = None

    def set_preferred_zones(self, zones: Iterable[VectorSpawnZone]) -> None:
        """Replace the active preferred zones and reset the active zone index."""

        self._preferred_zones = tuple(zones)
        self._active_zone_index = 0
        self._selection = None

    def advance_to_next_zone(self) -> VectorSpawnZone | None:
        """Cycle to the next selected spawn zone and drop the current selection."""

        if not self._preferred_zones:
            return None
        self._active_zone_index = (self._active_zone_index + 1) % len(self._preferred_zones)
        self._selection = None
        return self._preferred_zones[self._active_zone_index]

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
            if self._preferred_zones:
                self._active_zone_index = (self._active_zone_index + 1) % len(self._preferred_zones)
            return True
        return False

    def select_world_zone(self, position: WorldPosition) -> ZoneSelection | None:
        """Bind to the active goal's nearest zone using authoritative world coordinates."""

        goal = self.active_goal
        if goal is None and not self._preferred_zones:
            return None
        if goal is None:
            # When no monster quota goal is active, create a synthetic goal
            # from the active preferred zone
            active_pzone = self._preferred_zones[
                self._active_zone_index % len(self._preferred_zones)
            ]
            goal = ZoneGoal(active_pzone.monster_name or str(active_pzone.monster_id))
        selection = self._selection
        if selection is not None and selection.goal == goal:
            return selection
        zones = self._map.zones_for(goal.monster_name)
        chosen: VectorSpawnZone | None
        if self._preferred_zones:
            active_pzone = self._preferred_zones[
                self._active_zone_index % len(self._preferred_zones)
            ]
            if active_pzone in zones or not zones:
                chosen = active_pzone
            else:
                chosen = nearest_zone(zones, WorldCoordinate(position.x, position.z))
        else:
            chosen = nearest_zone(zones, WorldCoordinate(position.x, position.z))
        if chosen is None:
            return None
        self._selection = ZoneSelection(goal, chosen)
        return self._selection

    def plan_live_route(
        self,
        position: WorldPosition,
        *,
        temporary_blocks: tuple[WorldPosition, ...] = (),
    ) -> VectorNavigationPlan:
        """Return an elevation-aware world-space route from the current live position."""

        selection = self.select_world_zone(position)
        if selection is None:
            return VectorNavigationPlan()
        origin = WorldCoordinate(position.x, position.z)
        stations = self._stations(selection.zone, origin)
        waypoints: list[TerrainWaypoint] = []
        current = position
        blocked = False
        for station in stations:
            height = self._map.terrain.height_at(station)
            destination = WorldPosition(
                station.x,
                selection.zone.center_y if height is None else height,
                station.z,
            )
            leg = self._terrain_planner.plan(
                current, destination, temporary_blocks=temporary_blocks
            )
            if leg.blocked or leg.is_empty:
                blocked = blocked or leg.blocked
                continue
            if waypoints and leg.waypoints and waypoints[-1].position == leg.waypoints[0].position:
                waypoints.extend(leg.waypoints[1:])
            else:
                waypoints.extend(leg.waypoints)
            current = destination
        points = tuple(WorldCoordinate(item.position.x, item.position.z) for item in waypoints)
        return VectorNavigationPlan(
            points=points,
            goal=selection.goal,
            zone=selection.zone,
            blocked=blocked and not points,
            world_waypoints=tuple(waypoints),
        )

    def zone_contains_world(self, position: WorldPosition) -> bool:
        """Return whether a live world position lies in the selected spawn rectangle."""

        zone = self.active_zone
        return zone is not None and zone.contains(WorldCoordinate(position.x, position.z))

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

    The selected zones are operator preferences for patrol; the navigator still
    receives authoritative live GPS before it can plan or dispatch movement.
    """

    world_map: WorldVectorMap
    anchor_zone: VectorSpawnZone | None = None
    active_zones: tuple[VectorSpawnZone, ...] = ()
    goals: tuple[ZoneGoal, ...] = ()

    def navigator(self) -> VectorZoneNavigator:
        """Return a navigator that plans entirely in client world units."""

        return VectorZoneNavigator(
            self.world_map,
            goals=self.goals,
            preferred_zone=self.anchor_zone,
            preferred_zones=self.active_zones,
        )


def zone_goals_from_selection(
    monster_names: Sequence[str], quotas: Sequence[int | None] | None = None
) -> tuple[ZoneGoal, ...]:
    """Return goals for a monster selection, pairing each name with its optional quota."""

    if quotas is not None and len(quotas) != len(monster_names):
        raise ValueError("Each selected monster needs exactly one quota entry.")
    resolved = quotas if quotas is not None else [None] * len(monster_names)
    return tuple(ZoneGoal(name, quota) for name, quota in zip(monster_names, resolved, strict=True))
