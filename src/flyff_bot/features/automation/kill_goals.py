"""Per-monster kill quotas, attribution, and dynamic targeting whitelists."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

# A quota of zero kills means "farm this monster without an upper bound", which is how the
# dashboard represents an activated monster whose quota field was left empty.
UNLIMITED_KILL_QUOTA = 0


@dataclass(frozen=True, slots=True)
class MobKillQuota:
    """One activated monster class and how many of it the session should kill."""

    class_name: str
    required_kills: int = UNLIMITED_KILL_QUOTA

    def __post_init__(self) -> None:
        if not self.class_name.strip():
            raise ValueError("Kill quota monster class name must not be empty.")
        if self.required_kills < UNLIMITED_KILL_QUOTA:
            raise ValueError("Kill quota must not be negative.")


@dataclass(frozen=True, slots=True)
class KillGoalConfig:
    """The operator's monster selection and the optional shutdown that follows it."""

    quotas: tuple[MobKillQuota, ...] = ()
    close_client_on_completion: bool = False

    def __post_init__(self) -> None:
        names = [quota.class_name for quota in self.quotas]
        if len(set(names)) != len(names):
            raise ValueError("Kill quotas must not repeat a monster class.")

    @property
    def has_quotas(self) -> bool:
        """Return whether any monster class was selected at all."""

        return bool(self.quotas)


@dataclass(frozen=True, slots=True)
class MobKillProgress:
    """One monster class as the dashboard displays it."""

    class_name: str
    kills: int
    required_kills: int

    @property
    def is_unlimited(self) -> bool:
        """Return whether this monster is farmed without a completion threshold."""

        return self.required_kills == UNLIMITED_KILL_QUOTA

    @property
    def is_completed(self) -> bool:
        """Return whether this monster reached its configured quota."""

        return not self.is_unlimited and self.kills >= self.required_kills


class KillEventRecorder(Protocol):
    """The durable log a session writes verified kills and its quotas into."""

    def record_kill(self, session_id: str, class_name: str, recorded_at: datetime) -> None:
        """Append one verified kill to the log."""

    def record_quotas(self, session_id: str, quotas: Iterable[MobKillQuota]) -> None:
        """Store the quotas a session is currently working towards."""

    def kill_counts(self, session_id: str) -> Mapping[str, int]:
        """Return the kills already logged per monster class for a session."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


class KillGoalTracker:
    """Attribute verified kills to monster classes and retire completed quotas.

    The tracker owns the session's answer to "which monsters are still worth targeting",
    which both the combat candidate selection and the perception class filter follow.
    """

    def __init__(
        self,
        config: KillGoalConfig | None = None,
        *,
        session_id: str | None = None,
        recorder: KillEventRecorder | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._config = config or KillGoalConfig()
        self._session_id = session_id or uuid4().hex
        self._recorder = recorder
        self._clock = clock
        self._kills: dict[str, int] = {}
        if self._recorder is not None:
            # A session identifier that was farmed before keeps its progress, so a pause,
            # a reconnect, or a restarted window never re-farms a satisfied quota.
            self._kills = dict(self._recorder.kill_counts(self._session_id))
            self._recorder.record_quotas(self._session_id, self._config.quotas)

    @property
    def config(self) -> KillGoalConfig:
        """Return the currently configured monster selection."""

        return self._config

    @property
    def has_quotas(self) -> bool:
        """Return whether the operator restricted the session to specific monsters."""

        return self._config.has_quotas

    @property
    def close_client_on_completion(self) -> bool:
        """Return whether a finished session should ask the game client to close."""

        return self._config.close_client_on_completion

    @property
    def progress(self) -> tuple[MobKillProgress, ...]:
        """Return one progress entry per selected monster, in the configured order."""

        return tuple(
            MobKillProgress(
                quota.class_name, self._kills.get(quota.class_name, 0), quota.required_kills
            )
            for quota in self._config.quotas
        )

    @property
    def active_class_names(self) -> frozenset[str]:
        """Return the monsters still worth targeting.

        An unconfigured tracker returns the empty set, which every filtering boundary
        already reads as "no restriction at all".
        """

        if not self.has_quotas:
            return frozenset()
        return frozenset(entry.class_name for entry in self.progress if not entry.is_completed)

    @property
    def is_completed(self) -> bool:
        """Return whether every selected monster reached a bounded quota."""

        return self.has_quotas and all(entry.is_completed for entry in self.progress)

    def update_config(self, config: KillGoalConfig) -> None:
        """Apply a new monster selection without discarding the kills already counted."""

        self._config = config
        if self._recorder is not None:
            self._recorder.record_quotas(self._session_id, config.quotas)

    def record_kill(self, class_name: str | None) -> bool:
        """Count one verified kill against its monster class and log it.

        Returns whether the kill was attributable: an engagement whose candidate class is
        unknown is never counted, because guessing would corrupt a quota.
        """

        if not class_name:
            return False
        self._kills[class_name] = self._kills.get(class_name, 0) + 1
        if self._recorder is not None:
            self._recorder.record_kill(self._session_id, class_name, self._clock())
        return True

    def kills_for(self, class_name: str) -> int:
        """Return how many kills of one monster class this session counted."""

        return self._kills.get(class_name, 0)
