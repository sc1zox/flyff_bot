"""Small deterministic STRIPS-style planner for high-level goals."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Goal:
    """Facts that must hold for a plan to be complete."""

    required_facts: frozenset[str]


@dataclass(frozen=True, slots=True)
class PlanningAction:
    """A STRIPS operator with preconditions and add/delete effects."""

    identifier: str
    preconditions: frozenset[str]
    add_effects: frozenset[str]
    delete_effects: frozenset[str] = frozenset()


class Planner:
    """Produce the shortest deterministic sequence of applicable planning actions."""

    def plan(
        self,
        initial_facts: frozenset[str],
        goal: Goal,
        actions: tuple[PlanningAction, ...],
    ) -> tuple[PlanningAction, ...] | None:
        """Return a plan, or ``None`` when the goal cannot be reached."""

        queue: deque[tuple[frozenset[str], tuple[PlanningAction, ...]]] = deque(
            [(initial_facts, ())]
        )
        visited = {initial_facts}
        while queue:
            facts, steps = queue.popleft()
            if goal.required_facts <= facts:
                return steps
            for action in actions:
                if not action.preconditions <= facts:
                    continue
                next_facts = (facts - action.delete_effects) | action.add_effects
                if next_facts in visited:
                    continue
                visited.add(next_facts)
                queue.append((next_facts, (*steps, action)))
        return None
