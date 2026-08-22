"""Typed quest NPC interaction states and read-only dialogue evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from flyff_bot.features.automation.combat_execution import CombatInputAdapter
from flyff_bot.features.automation.controllers import (
    DEFAULT_KEY_PRESS_DURATION_SECONDS,
    VIRTUAL_KEY_C,
)
from flyff_bot.features.automation.models import Position, WorldState
from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.quests.goals import QuestNpc, QuestResolution
from flyff_bot.features.vision.models import CapturedFrame

DEFAULT_QUEST_INTERACTION_TIMEOUT_SECONDS = 10.0
DEFAULT_QUEST_RETRY_BASE_SECONDS = 2.0
MAXIMUM_QUEST_INTERACTION_ATTEMPTS = 3
QUEST_INTERACTION_KEY_LABEL = "c"


class QuestInteractionMode(StrEnum):
    """The observable phases of one configured NPC quest cycle."""

    NAVIGATING_TO_ACCEPT = "navigating_to_accept"
    INTERACTING = "interacting"
    AWAITING_ACCEPT_CONFIRMATION = "awaiting_accept_confirmation"
    FARMING_OBJECTIVES = "farming_objectives"
    NAVIGATING_TO_TURN_IN = "navigating_to_turn_in"
    INTERACTING_FOR_TURN_IN = "interacting_for_turn_in"
    AWAITING_REWARD_CLAIM = "awaiting_reward_claim"
    RETREATING = "retreating"
    FAILED = "failed"


class QuestInputKind(StrEnum):
    """The only input categories a dialogue sequence may request."""

    NONE = "none"
    CLICK = "click"
    KEY = "key"


@dataclass(frozen=True, slots=True)
class QuestInteractionDecision:
    """One guarded NPC or observed dialogue action, if this phase has one."""

    mode: QuestInteractionMode
    input_kind: QuestInputKind = QuestInputKind.NONE
    position: Position | None = None
    virtual_key: int | None = None
    key_press_duration_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class DialogueObservation:
    """A read-only frame observation of the client's quest dialogue."""

    is_open: bool = False
    can_accept: bool = False
    can_turn_in: bool = False
    reward_pending: bool = False
    option_position: Position | None = None
    detail: str = ""


class DialoguePerceiver(Protocol):
    """The minimal read-only evidence needed before clicking a dialogue option."""

    def observe_dialogue(
        self, state: WorldState, frame: CapturedFrame | None
    ) -> DialogueObservation:
        """Return what the latest client frame proves about an open quest dialogue."""


CombatInputAdapterLike = CombatInputAdapter


@dataclass(frozen=True, slots=True)
class QuestInteractionConfig:
    """Bounded timing and the one documented keyboard fallback for opening dialogue."""

    interaction_timeout_seconds: float = DEFAULT_QUEST_INTERACTION_TIMEOUT_SECONDS
    retry_base_seconds: float = DEFAULT_QUEST_RETRY_BASE_SECONDS
    maximum_attempts: int = MAXIMUM_QUEST_INTERACTION_ATTEMPTS
    interact_key: int = VIRTUAL_KEY_C
    key_press_duration_seconds: float = DEFAULT_KEY_PRESS_DURATION_SECONDS

    def __post_init__(self) -> None:
        if self.interaction_timeout_seconds <= 0.0:
            raise ValueError("Quest interaction timeout must be positive.")
        if self.retry_base_seconds <= 0.0:
            raise ValueError("Quest retry backoff base must be positive.")
        if self.maximum_attempts <= 0:
            raise ValueError("Quest interaction attempts must be positive.")
        if self.key_press_duration_seconds <= 0.0:
            raise ValueError("Quest key press duration must be positive.")


class QuestInteractionController:
    """Sequence navigation, observed dialogue evidence, timeout, and bounded retry."""

    def __init__(
        self,
        resolution: QuestResolution,
        *,
        config: QuestInteractionConfig | None = None,
        dialogue_perceiver: DialoguePerceiver | None = None,
    ) -> None:
        self._resolution = resolution
        self._config = config or QuestInteractionConfig()
        self._dialogue_perceiver = dialogue_perceiver
        self.reset()

    @property
    def mode(self) -> QuestInteractionMode:
        """Return the current quest-interaction phase."""

        return self._mode

    @property
    def is_failed(self) -> bool:
        """Return whether every bounded attempt has failed."""

        return self._mode is QuestInteractionMode.FAILED

    @property
    def active_npc(self) -> QuestNpc | None:
        """Return the configured NPC this phase is navigating or interacting with."""

        return self._active_npc()

    def reset(self) -> None:
        """Start a fresh cycle at the active quest's configured accept NPC."""

        self._mode = QuestInteractionMode.NAVIGATING_TO_ACCEPT
        self._at_seconds = 0.0
        self._attempt_started_at_seconds: float | None = None
        self._attempts = 0
        self._failures = 0
        self._retry_after_seconds: float | None = None
        self._turn_in_requested = False

    def begin_turn_in(self) -> None:
        """Route to the configured turn-in NPC once objectives are independently complete."""

        if not _has_targets(self._resolution):
            raise RuntimeError("A quest with no objectives cannot be turned in.")
        self._mode = QuestInteractionMode.NAVIGATING_TO_TURN_IN
        self._turn_in_requested = True
        self._begin_attempt()

    def begin_interaction(self, at_seconds: float) -> None:
        """Start one bounded dialogue attempt after NavMesh arrival."""

        if self._mode not in {
            QuestInteractionMode.NAVIGATING_TO_ACCEPT,
            QuestInteractionMode.NAVIGATING_TO_TURN_IN,
        }:
            return
        self._mode = (
            QuestInteractionMode.INTERACTING_FOR_TURN_IN
            if self._mode is QuestInteractionMode.NAVIGATING_TO_TURN_IN
            else QuestInteractionMode.INTERACTING
        )
        self._begin_attempt(at_seconds)

    def retry_if_due(self, at_seconds: float) -> bool:
        """End safe retreat and restart the same bounded interaction once backoff ends."""

        ready_at = self._retry_after_seconds
        if self._mode is not QuestInteractionMode.RETREATING or ready_at is None:
            return False
        if at_seconds < ready_at:
            return False
        self._reset_timing()
        self._mode = (
            QuestInteractionMode.NAVIGATING_TO_TURN_IN
            if self._turn_in_requested
            else QuestInteractionMode.NAVIGATING_TO_ACCEPT
        )
        return True

    def observe_navigation(
        self,
        target: WorldPosition | None,
        in_interaction_range: bool,
        route_available: bool,
        at_seconds: float,
    ) -> bool:
        """Advance a NavMesh approach and report whether interaction may begin."""

        del target
        if self.mode not in {
            QuestInteractionMode.NAVIGATING_TO_ACCEPT,
            QuestInteractionMode.NAVIGATING_TO_TURN_IN,
        }:
            return False
        self._at_seconds = at_seconds
        if in_interaction_range:
            self.begin_interaction(at_seconds)
            return True
        if not route_available and self._attempt_started_at_seconds is None:
            self._begin_attempt(at_seconds)
        if self._timed_out(at_seconds):
            self._fail_or_retry(at_seconds)
        return False

    def step(
        self, state: WorldState, frame: CapturedFrame | None = None
    ) -> QuestInteractionDecision:
        """Return one guarded input request based only on read-only observations."""

        at_seconds = state.observed_at_seconds
        self._at_seconds = at_seconds
        if self._mode is QuestInteractionMode.RETREATING:
            return QuestInteractionDecision(self._mode)
        npc = self._active_npc()
        if npc is None or self._mode in {
            QuestInteractionMode.FARMING_OBJECTIVES,
            QuestInteractionMode.FAILED,
        }:
            return QuestInteractionDecision(self._mode)
        observation = (
            self._dialogue_perceiver.observe_dialogue(state, frame)
            if self._dialogue_perceiver is not None
            else DialogueObservation(detail="dialogue_perception_unavailable")
        )
        if self._confirmed_observation(observation):
            return QuestInteractionDecision(self._mode)
        option_position = observation.option_position
        if option_position is not None and (
            (self._is_accepting and observation.can_accept)
            or (not self._is_accepting and observation.can_turn_in)
        ):
            self._confirm_action(True, at_seconds)
            return QuestInteractionDecision(
                self._mode,
                QuestInputKind.CLICK,
                position=option_position,
            )
        if self._mode in {
            QuestInteractionMode.INTERACTING,
            QuestInteractionMode.INTERACTING_FOR_TURN_IN,
        }:
            self._confirm_action(observation.is_open, at_seconds)
            return QuestInteractionDecision(
                self._mode,
                QuestInputKind.KEY,
                virtual_key=self._config.interact_key,
                key_press_duration_seconds=self._config.key_press_duration_seconds,
            )
        if self._timed_out(at_seconds):
            self._fail_or_retry(at_seconds)
        return QuestInteractionDecision(self._mode)

    def timeout_navigation(self, at_seconds: float) -> bool:
        """Apply one bounded timeout while a route is still pending."""

        if self._mode not in {
            QuestInteractionMode.NAVIGATING_TO_ACCEPT,
            QuestInteractionMode.NAVIGATING_TO_TURN_IN,
        }:
            return False
        if self._attempt_started_at_seconds is None:
            self._begin_attempt(self._at_seconds)
        if not self._timed_out(at_seconds):
            return False
        self._fail_or_retry(at_seconds)
        return True

    def _active_npc(self) -> QuestNpc | None:
        if self._mode in {
            QuestInteractionMode.NAVIGATING_TO_ACCEPT,
            QuestInteractionMode.INTERACTING,
            QuestInteractionMode.AWAITING_ACCEPT_CONFIRMATION,
        }:
            return self._resolution.accept_npc
        if self._mode in {
            QuestInteractionMode.NAVIGATING_TO_TURN_IN,
            QuestInteractionMode.INTERACTING_FOR_TURN_IN,
            QuestInteractionMode.AWAITING_REWARD_CLAIM,
        }:
            return self._resolution.turn_in_npc
        return None

    @property
    def _is_accepting(self) -> bool:
        return self._mode in {
            QuestInteractionMode.INTERACTING,
            QuestInteractionMode.AWAITING_ACCEPT_CONFIRMATION,
        }

    def _confirmed_observation(self, observation: DialogueObservation) -> bool:
        if (
            self._mode is QuestInteractionMode.AWAITING_ACCEPT_CONFIRMATION
            and observation.is_open
            and observation.can_accept
        ):
            self._mode = QuestInteractionMode.FARMING_OBJECTIVES
            self._reset_timing()
            return True
        if self._mode is QuestInteractionMode.AWAITING_REWARD_CLAIM and observation.reward_pending:
            self._mode = QuestInteractionMode.FARMING_OBJECTIVES
            self._reset_timing()
            return True
        return False

    def _confirm_action(self, opened_dialogue: bool, at_seconds: float) -> None:
        if opened_dialogue:
            self._mode = (
                QuestInteractionMode.AWAITING_REWARD_CLAIM
                if self._mode is QuestInteractionMode.INTERACTING_FOR_TURN_IN
                else QuestInteractionMode.AWAITING_ACCEPT_CONFIRMATION
            )
        self._restart_attempt(at_seconds)

    def _begin_attempt(self, at_seconds: float | None = None) -> None:
        started = self._at_seconds if at_seconds is None else at_seconds
        self._attempt_started_at_seconds = started
        self._attempts += 1

    def _restart_attempt(self, at_seconds: float) -> None:
        self._attempt_started_at_seconds = at_seconds

    def _reset_timing(self) -> None:
        self._attempt_started_at_seconds = None
        self._retry_after_seconds = None
        self._attempts = 0

    def _timed_out(self, at_seconds: float) -> bool:
        started = self._attempt_started_at_seconds
        if started is None:
            return False
        return at_seconds - started >= self._config.interaction_timeout_seconds

    def _fail_or_retry(self, at_seconds: float) -> None:
        failures = self._failures + 1
        self._reset_timing()
        self._failures = failures
        if failures >= self._config.maximum_attempts:
            self._mode = QuestInteractionMode.FAILED
            return
        backoff_exponent = max(0, failures - 1)
        self._retry_after_seconds = at_seconds + (
            self._config.retry_base_seconds * (2**backoff_exponent)
        )
        self._mode = QuestInteractionMode.RETREATING

    @property
    def retry_ready_at_seconds(self) -> float | None:
        """Return when retreat ends and the same bounded interaction may retry."""

        return self._retry_after_seconds


def _has_targets(resolution: QuestResolution) -> bool:
    return bool(resolution.targets)
