"""Client-versus-visual selected-target agreement and its fail-closed rule (US-083 AC5)."""

from __future__ import annotations

from flyff_bot.features.automation.models import (
    InventoryEntry,
    Position,
    VisibleMob,
    WorldState,
)
from flyff_bot.features.automation.target_reconciliation import (
    TargetAgreement,
    reconcile_selected_target,
)
from flyff_bot.features.client_data.label_mapping import JoinedMoverCandidate
from flyff_bot.features.client_data.models import MoverCombatProperties
from flyff_bot.features.player_stats.models import (
    ClientPlayerStatsSnapshot,
    ClientTargetSnapshot,
    ClientTargetState,
    PlayerStatField,
    PlayerStatsReadError,
    PlayerStatsReadErrorCode,
    PlayerStatsSource,
)

OBSERVED_AT_SECONDS = 5.0
CANDIDATE_INDEX = 3
AIBATT_MOVER_ID = 1101
BURNT_MOVER_ID = 1102
CLIENT_DIGEST = "a" * 64
MAPPING_VERSION = "1"


def _mob(candidate_index: int | None = CANDIDATE_INDEX) -> VisibleMob:
    return VisibleMob(1, "Aibatt", 0.9, 10, 10, 20, 20, candidate_index=candidate_index)


def _join(mover_id: int, candidate_index: int = CANDIDATE_INDEX) -> JoinedMoverCandidate:
    return JoinedMoverCandidate(
        candidate_index=candidate_index,
        detector_label="Aibatt",
        mover_id=mover_id,
        mover_symbol="MI_AIBATT",
        display_name="Aibatt",
        combat=MoverCombatProperties(),
        drops=(),
        mapping_version=MAPPING_VERSION,
        client_digest=CLIENT_DIGEST,
    )


def _client_snapshot(target: ClientTargetSnapshot | None) -> ClientPlayerStatsSnapshot:
    return ClientPlayerStatsSnapshot(
        source=PlayerStatsSource.CLIENT_MEMORY,
        sampled_at_seconds=OBSERVED_AT_SECONDS,
        client_sha256=CLIENT_DIGEST,
        fields=(PlayerStatField("hp", 100.0, False),),
        target=target,
    )


def _state(
    snapshot: ClientPlayerStatsSnapshot | None,
    joins: tuple[JoinedMoverCandidate, ...] = (),
) -> WorldState:
    return WorldState(
        observed_at_seconds=OBSERVED_AT_SECONDS,
        position=Position(0, 0),
        nearby_mob_count=1,
        inventory=(InventoryEntry("penya", 0),),
        progress_marker=0,
        player_stats_snapshot=snapshot,
        mob_catalog_joins=joins,
    )


def test_matching_mover_identities_agree() -> None:
    state = _state(
        _client_snapshot(
            ClientTargetSnapshot(
                mover_id=AIBATT_MOVER_ID,
                current_hp=50.0,
                max_hp=200.0,
                state=ClientTargetState.ALIVE,
            )
        ),
        joins=(_join(AIBATT_MOVER_ID),),
    )

    reconciliation = reconcile_selected_target(state, _mob())

    assert reconciliation.agreement is TargetAgreement.AGREED
    assert reconciliation.has_authoritative_identity
    assert not reconciliation.blocks_identity_dependent_action
    assert reconciliation.client_hp_percentage == 25.0


def test_a_stated_disagreement_blocks_an_identity_dependent_action() -> None:
    # The client has one actor selected; the box the session engaged is a different mover.
    state = _state(
        _client_snapshot(
            ClientTargetSnapshot(mover_id=BURNT_MOVER_ID, state=ClientTargetState.ALIVE)
        ),
        joins=(_join(AIBATT_MOVER_ID),),
    )

    reconciliation = reconcile_selected_target(state, _mob())

    assert reconciliation.agreement is TargetAgreement.IDENTITY_MISMATCH
    assert reconciliation.blocks_identity_dependent_action
    assert (reconciliation.client_mover_id, reconciliation.visual_mover_id) == (
        BURNT_MOVER_ID,
        AIBATT_MOVER_ID,
    )


def test_an_install_without_an_exact_profile_is_not_in_disagreement() -> None:
    unavailable = ClientPlayerStatsSnapshot(
        source=PlayerStatsSource.UNAVAILABLE,
        error=PlayerStatsReadError(PlayerStatsReadErrorCode.NO_PROFILE),
    )

    reconciliation = reconcile_selected_target(_state(unavailable), _mob())

    assert reconciliation.agreement is TargetAgreement.NO_AUTHORITATIVE_PROFILE
    assert not reconciliation.blocks_identity_dependent_action


def test_an_unjoined_detection_cannot_be_compared_and_does_not_block() -> None:
    state = _state(
        _client_snapshot(
            ClientTargetSnapshot(mover_id=AIBATT_MOVER_ID, state=ClientTargetState.ALIVE)
        )
    )

    reconciliation = reconcile_selected_target(state, _mob())

    assert reconciliation.agreement is TargetAgreement.UNJOINED_VISUAL_TARGET
    assert not reconciliation.blocks_identity_dependent_action


def test_no_client_selection_is_reported_separately_from_a_mismatch() -> None:
    state = _state(
        _client_snapshot(ClientTargetSnapshot(state=ClientTargetState.NONE)),
        joins=(_join(AIBATT_MOVER_ID),),
    )

    reconciliation = reconcile_selected_target(state, _mob())

    assert reconciliation.agreement is TargetAgreement.NO_CLIENT_TARGET
    assert not reconciliation.blocks_identity_dependent_action


def test_nothing_engaged_reports_no_visual_target() -> None:
    state = _state(
        _client_snapshot(
            ClientTargetSnapshot(mover_id=AIBATT_MOVER_ID, state=ClientTargetState.ALIVE)
        )
    )

    reconciliation = reconcile_selected_target(state, None)

    assert reconciliation.agreement is TargetAgreement.NO_VISUAL_TARGET
    assert reconciliation.client_mover_id == AIBATT_MOVER_ID


def test_client_hp_is_missing_rather_than_zero_when_the_maximum_is_unknown() -> None:
    state = _state(
        _client_snapshot(
            ClientTargetSnapshot(
                mover_id=AIBATT_MOVER_ID, current_hp=50.0, state=ClientTargetState.ALIVE
            )
        ),
        joins=(_join(AIBATT_MOVER_ID),),
    )

    reconciliation = reconcile_selected_target(state, _mob())

    assert reconciliation.client_hp_percentage is None
