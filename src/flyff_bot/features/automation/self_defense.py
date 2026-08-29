"""Bounded relaxation of the target whitelist while the character is being attacked."""

from __future__ import annotations

from dataclasses import dataclass

# A single HP tick is enough evidence: the session only ever loses health to something that
# decided to attack it, and the guard is bounded in time rather than in damage.
DEFAULT_SELF_DEFENSE_HEALTH_DROP_PERCENTAGE = 1.0
# Long enough to finish the attacker off, short enough that one ambush cannot turn a
# zone-locked session into an unrestricted one for the rest of the run (US-091).
DEFAULT_SELF_DEFENSE_WINDOW_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class SelfDefenseConfig:
    """How much unexplained damage opens a defence window, and for how long."""

    health_drop_percentage: float = DEFAULT_SELF_DEFENSE_HEALTH_DROP_PERCENTAGE
    window_seconds: float = DEFAULT_SELF_DEFENSE_WINDOW_SECONDS

    def __post_init__(self) -> None:
        if self.health_drop_percentage <= 0.0:
            raise ValueError("Self-defence health drop threshold must be positive.")
        if self.window_seconds <= 0.0:
            raise ValueError("Self-defence window must be positive.")


class SelfDefenseGuard:
    """Report whether an unselected attacker may currently be fought back.

    A zone-locked session ignores every monster class its selected camps do not spawn. That
    restriction has one exception: something that is already hitting the character has to be
    answerable, or the session stands still and dies. The guard opens for a bounded window
    when health drops while no engagement is in progress (US-091).
    """

    def __init__(self, config: SelfDefenseConfig | None = None) -> None:
        self._config = config or SelfDefenseConfig()
        self._previous_health_percentage: float | None = None
        self._expires_at_seconds: float | None = None
        self._observed_at_seconds = 0.0

    @property
    def is_active(self) -> bool:
        """Return whether the defence window observed last is still open."""

        expires_at = self._expires_at_seconds
        return expires_at is not None and self._observed_at_seconds < expires_at

    def reset(self) -> None:
        """Forget the health baseline and close any open window."""

        self._previous_health_percentage = None
        self._expires_at_seconds = None
        self._observed_at_seconds = 0.0

    def observe(self, health_percentage: float, *, engaged: bool, at_seconds: float) -> bool:
        """Record one health sample and return whether self-defence is currently allowed.

        Damage taken during an engagement is the fight the session chose, so it never opens
        the window; only damage arriving outside one is evidence of being attacked.
        """

        self._observed_at_seconds = at_seconds
        previous = self._previous_health_percentage
        self._previous_health_percentage = health_percentage
        if (
            not engaged
            and previous is not None
            and previous - health_percentage >= self._config.health_drop_percentage
        ):
            self._expires_at_seconds = at_seconds + self._config.window_seconds
        return self.is_active
