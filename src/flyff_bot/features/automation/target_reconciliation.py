"""Reconcile the client's authoritative selected target with the YOLO instance (US-083).

Two independent things claim to know what the character is fighting. The client states it
exactly, in memory: a mover id, a current and maximum HP, and a lifecycle state. Perception
infers it visually: a detection, joined through the extracted catalog to the mover the client
declares that class to be. Neither is redundant -- the visual instance is the one a policy
ranked and can navigate to, and the client identity is the only one that is authoritative.

When both are available they must agree, and when they disagree the disagreement is the
finding. Silently preferring either one is what produces a session that attacks the mob it can
see while reporting the HP of the mob the client has selected, which is how a kill gets
attributed to the wrong monster and a quota advances on evidence that was never observed.

A session with no exact profile is not in disagreement; it simply has no authoritative identity
to check against, and keeps running on the visual evidence it has always used. Failing closed
there would disable every install that has not fingerprinted its client, which is the majority
of them and not a defect.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from flyff_bot.features.player_stats.models import (
    ClientPlayerStatsSnapshot,
    ClientTargetSnapshot,
    ClientTargetState,
    PlayerStatsSource,
)


class TargetAgreement(StrEnum):
    """Whether the client and the visual instance describe the same actor."""

    #: Both sources state a mover id and it is the same one.
    AGREED = "agreed"
    #: No exact profile is configured, so there is no authoritative identity to check.
    NO_AUTHORITATIVE_PROFILE = "no_authoritative_profile"
    #: The profile is present but the client currently has nothing selected.
    NO_CLIENT_TARGET = "no_client_target"
    #: Nothing was visually engaged this tick.
    NO_VISUAL_TARGET = "no_visual_target"
    #: The engaged detection never joined to an authoritative mover, so it cannot be compared.
    UNJOINED_VISUAL_TARGET = "unjoined_visual_target"
    #: Both stated an identity and they are different actors.
    IDENTITY_MISMATCH = "identity_mismatch"


@dataclass(frozen=True, slots=True)
class TargetReconciliation:
    """What the two sources said about the selected target, and whether they agree."""

    agreement: TargetAgreement
    client_mover_id: int | None = None
    visual_mover_id: int | None = None
    candidate_index: int | None = None
    client_hp_percentage: float | None = None
    client_state: ClientTargetState | None = None

    @property
    def has_authoritative_identity(self) -> bool:
        """Return whether the client confirmed the identity of the engaged instance."""

        return self.agreement is TargetAgreement.AGREED

    @property
    def blocks_identity_dependent_action(self) -> bool:
        """Return whether an action needing a proven identity must not be dispatched.

        Only a stated disagreement blocks. An absent profile, an unselected client target,
        and an unjoined detection all mean "not proven", which leaves the session exactly
        where it was before an authoritative source existed rather than halting it.
        """

        return self.agreement is TargetAgreement.IDENTITY_MISMATCH


def reconcile_selected_target(
    snapshot: ClientPlayerStatsSnapshot | None,
    *,
    candidate_index: int | None,
    visual_mover_id: int | None,
    has_visual_target: bool,
) -> TargetReconciliation:
    """Compare the client's selected target with the detection the session engaged.

    Deliberately a pure function over the two sources rather than something that reaches into
    a world state: it is the world state that carries the result, so taking one as an argument
    would make the snapshot depend on its own field.
    """

    client_target = _client_target(snapshot)
    if client_target is None:
        return TargetReconciliation(
            TargetAgreement.NO_AUTHORITATIVE_PROFILE, candidate_index=candidate_index
        )

    hp_percentage = _hp_percentage(client_target)
    if not has_visual_target:
        return TargetReconciliation(
            TargetAgreement.NO_VISUAL_TARGET,
            client_mover_id=client_target.mover_id,
            client_hp_percentage=hp_percentage,
            client_state=client_target.state,
        )

    if client_target.mover_id is None or client_target.state is ClientTargetState.NONE:
        agreement = TargetAgreement.NO_CLIENT_TARGET
    elif visual_mover_id is None:
        agreement = TargetAgreement.UNJOINED_VISUAL_TARGET
    elif visual_mover_id == client_target.mover_id:
        agreement = TargetAgreement.AGREED
    else:
        agreement = TargetAgreement.IDENTITY_MISMATCH

    return TargetReconciliation(
        agreement,
        client_mover_id=client_target.mover_id,
        visual_mover_id=visual_mover_id,
        candidate_index=candidate_index,
        client_hp_percentage=hp_percentage,
        client_state=client_target.state,
    )


def _client_target(
    snapshot: ClientPlayerStatsSnapshot | None,
) -> ClientTargetSnapshot | None:
    """Return the bounded client target, or ``None`` when no profile proved one."""

    if snapshot is None or snapshot.source is not PlayerStatsSource.CLIENT_MEMORY:
        return None
    return snapshot.target


def _hp_percentage(target: ClientTargetSnapshot) -> float | None:
    """Return the client target's HP as a percentage, or ``None`` when unmeasured."""

    current, maximum = target.current_hp, target.max_hp
    if current is None or maximum is None or maximum <= 0.0:
        return None
    return max(0.0, min(1.0, current / maximum)) * 100.0
