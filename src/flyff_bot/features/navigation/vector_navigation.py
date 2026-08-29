"""GPS-only goal-driven navigation over an extracted world vector map."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.navmesh import BakedNavMesh
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
# A patrol leg is refused when its route passes this close to a node that already stalled the
# character, so the replan walks around the obstacle instead of back into it.
TEMPORARY_BLOCK_CLEARANCE_UNITS = 3.0


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
    world_waypoints: tuple[WorldPosition, ...] = ()

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
        navmesh: BakedNavMesh | None = None,
    ) -> None:
        self._map = world_map
        self._navmesh = navmesh
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
    def navmesh(self) -> BakedNavMesh | None:
        """Return the baked collision mesh patrol legs are routed over, when one is loaded."""

        return self._navmesh

    def attach_navmesh(self, navmesh: BakedNavMesh | None) -> None:
        """Adopt the same baked mesh combat approaches route over.

        Zone travel and combat approaches read one authoritative mesh: a patrol can no longer
        walk a line the approach planner considers solid. A session whose world has no baked
        mesh has no route at all and blocks rather than steering into unverified terrain
        (US-093).
        """

        self._navmesh = navmesh

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
        """Return whether the session still has somewhere to farm.

        An operator-selected camp keeps the extracted map steering even once every quota is
        satisfied, which is what an unlimited (quota-free) selection means.
        """

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
        """Cycle to the next selected spawn zone, or report that there is no other one.

        A selection of one camp has nowhere to advance to, so it stays bound instead of
        re-binding to itself and restarting the route it is already following.
        """

        if len(self._preferred_zones) < 2:
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
        waypoints: list[WorldPosition] = []
        current = position
        blocked = False
        for station in stations:
            height = self._map.terrain.height_at(station)
            destination = WorldPosition(
                station.x,
                selection.zone.center_y if height is None else height,
                station.z,
            )
            leg = self._plan_leg(current, destination, temporary_blocks)
            if leg is None:
                blocked = True
                continue
            if waypoints and waypoints[-1] == leg[0]:
                waypoints.extend(leg[1:])
            else:
                waypoints.extend(leg)
            current = leg[-1]
        points = tuple(WorldCoordinate(item.x, item.z) for item in waypoints)
        return VectorNavigationPlan(
            points=points,
            goal=selection.goal,
            zone=selection.zone,
            blocked=blocked and not points,
            world_waypoints=tuple(waypoints),
        )

    def _plan_leg(
        self,
        start: WorldPosition,
        destination: WorldPosition,
        temporary_blocks: tuple[WorldPosition, ...],
    ) -> tuple[WorldPosition, ...] | None:
        """Return one walkable leg of the patrol, or ``None`` when it is impassable.

        Every leg is routed over the authoritative baked mesh; a world with no baked mesh has
        no walkable route and every leg is refused (US-093).
        """

        mesh = self._navmesh
        if mesh is None or not mesh.polygons:
            return None
        obstacles = tuple((block, TEMPORARY_BLOCK_CLEARANCE_UNITS) for block in temporary_blocks)
        route = mesh.find_path(start, destination, obstacles=obstacles)
        if not route or _crosses_block(route, temporary_blocks):
            return None
        return route

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


def _crosses_block(route: tuple[WorldPosition, ...], blocks: tuple[WorldPosition, ...]) -> bool:
    """Return whether a planned leg still runs through a recorded stall spot.

    The leg's own start is skipped: the character is standing there and the whole point of
    the replan is to route away from it, not to refuse the only way out (US-093).
    """

    return any(
        math.hypot(point.x - block.x, point.z - block.z) <= TEMPORARY_BLOCK_CLEARANCE_UNITS
        for point in route[1:]
        for block in blocks
    )


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
    navmesh: BakedNavMesh | None = None

    @property
    def selected_zones(self) -> tuple[VectorSpawnZone, ...]:
        """Return the operator's camp selection, anchor first."""

        zones = list(self.active_zones)
        if self.anchor_zone is not None and self.anchor_zone not in zones:
            zones.insert(0, self.anchor_zone)
        return tuple(zones)

    def navigator(self) -> VectorZoneNavigator:
        """Return a navigator that plans entirely in client world units."""

        return VectorZoneNavigator(
            self.world_map,
            goals=zone_locked_goals(self.goals, self.selected_zones),
            preferred_zone=self.anchor_zone,
            preferred_zones=self.active_zones,
            navmesh=self.navmesh,
        )


def zone_monster_name(zone: VectorSpawnZone) -> str:
    """Return the monster class a spawn zone declares, falling back to its mover id."""

    return zone.monster_name or str(zone.monster_id)


def zone_locked_goals(
    goals: Sequence[ZoneGoal], zones: Sequence[VectorSpawnZone]
) -> tuple[ZoneGoal, ...]:
    """Return one goal per selected camp, in the order the camps were selected.

    The camp selection is the operator's whole statement of what to farm, so a preset that
    also lists other monsters must not add a goal no selected camp can satisfy, and a
    selected camp must not be left without one. A camp whose monster carries a quota keeps
    that quota; every other camp is farmed without an upper bound (US-091).
    """

    names = tuple(dict.fromkeys(zone_monster_name(zone) for zone in zones))
    if not names:
        return tuple(goals)
    quotas = {goal.monster_name: goal.kill_quota for goal in goals}
    return tuple(ZoneGoal(name, quotas.get(name)) for name in names)


def zone_goals_from_selection(
    monster_names: Sequence[str], quotas: Sequence[int | None] | None = None
) -> tuple[ZoneGoal, ...]:
    """Return goals for a monster selection, pairing each name with its optional quota."""

    if quotas is not None and len(quotas) != len(monster_names):
        raise ValueError("Each selected monster needs exactly one quota entry.")
    resolved = quotas if quotas is not None else [None] * len(monster_names)
    return tuple(ZoneGoal(name, quota) for name, quota in zip(monster_names, resolved, strict=True))
