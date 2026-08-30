"""Tests for first-run setup autostart, artifact autoload, and HUD fallback (US-085)."""

from __future__ import annotations

import ast
import ctypes
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from test_perception_pipeline import (
    OBSERVED_AT_SECONDS,
    _Detector,
    _FrameSource,
    _previous_state,
    _TargetVerifier,
)

from flyff_bot.features.automation.models import (
    PlayerVitals,
    Position,
    SelectedTarget,
    TargetState,
    Viewport,
    WorldState,
)
from flyff_bot.features.automation.orchestrator import (
    PLAYER_STATS_FALLBACK_GRACE_SECONDS,
    PLAYER_STATS_HUD_FALLBACK_REASON,
    FarmingMode,
    FarmingOrchestrator,
)
from flyff_bot.features.automation.readiness import (
    CapabilityRequirement,
    LiveProviderSample,
    LiveReadinessGate,
    LiveStateSource,
    ProviderHealth,
    ProviderRegistration,
    ReadinessState,
    SessionCapability,
)
from flyff_bot.features.diagnostics import SessionEventKind, SessionEventLogger
from flyff_bot.features.input_control.controller import (
    KEY_EVENT_KEY_UP,
    Input,
    WindowsInputController,
)
from flyff_bot.features.input_control.keymap import (
    VIRTUAL_KEY_A,
    VIRTUAL_KEY_W,
)
from flyff_bot.features.navigation.execution import PathingInputDispatcher
from flyff_bot.features.navigation.pathing import PathingDecision, PathingMode
from flyff_bot.features.perception.pipeline import (
    PerceptionPipeline,
    PerceptionTick,
)
from flyff_bot.features.player_stats.models import (
    ClientPlayerStatsSnapshot,
    PlayerStatsReadError,
    PlayerStatsReadErrorCode,
    PlayerStatsSource,
)
from flyff_bot.features.setup.extraction import UnifiedClientExtractor
from flyff_bot.features.vision.target_verification import (
    TargetStatus,
    TargetVerificationResult,
)
from flyff_bot.i18n import Language, Message, Translator
from flyff_bot.ui.main_window import MainWindow
from flyff_bot.ui.readiness_panel import ReadinessPanel

WINDOW_HANDLE = 42
PRODUCTION_ROOT = Path(__file__).resolve().parents[2] / "src" / "flyff_bot"


# --------------------------------------------------------------------------------------
# Acceptance criterion 3: no bare assert survives optimized Python.
# --------------------------------------------------------------------------------------


def test_no_production_module_relies_on_a_bare_assert_statement() -> None:
    offenders: list[str] = []
    for module in sorted(PRODUCTION_ROOT.rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        offenders.extend(
            f"{module.relative_to(PRODUCTION_ROOT)}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Assert)
        )

    assert offenders == []


# --------------------------------------------------------------------------------------
# Acceptance criteria 1 and 2: first-run detection, wizard autostart, artifact autoload.
# --------------------------------------------------------------------------------------


def _install(root: Path, *, complete: bool) -> dict[str, Path]:
    """Return the artifact paths of a fresh or fully extracted installation."""

    worlds = root / "worlds"
    worlds.mkdir(parents=True, exist_ok=True)
    paths = {
        "world_map_dir": worlds,
        "quest_database_path": root / "quests.json",
        "dungeon_database_path": root / "dungeons.json",
        "player_profiles_path": root / "profiles.json",
        "position_profiles_path": root / "position_profiles.json",
        "camera_profiles_path": root / "camera_profiles.json",
        "dungeon_profiles_path": root / "dungeon_profiles.json",
        "client_catalog_path": root / "catalog.json",
        "source_manifest_path": root / "source_manifest.json",
    }
    if complete:
        (worlds / "TestWorld.json").write_text("{}", encoding="utf-8")
        for key, path in paths.items():
            if key != "world_map_dir":
                path.write_text("{}", encoding="utf-8")
    return paths


def _dispose(window: MainWindow) -> None:
    """Tear the window down completely so no widget tree outlives its test."""

    window.close()
    window.deleteLater()
    application = QApplication.instance()
    if application is not None:
        application.processEvents()


def _window(tmp_path: Path, paths: dict[str, Path]) -> MainWindow:
    QApplication.instance() or QApplication([])
    return MainWindow(
        Translator(Language.ENGLISH),
        vitals_config_path=tmp_path / "vitals.json",
        powerup_config_path=tmp_path / "powerups.json",
        emergency_config_path=tmp_path / "emergency.json",
        teleporter_database_path=tmp_path / "teleporters.json",
        quest_npc_positions_path=tmp_path / "npcs.json",
        **paths,
    )


def test_an_incomplete_install_requires_setup_and_refuses_to_arm_farming(tmp_path: Path) -> None:
    window = _window(tmp_path, _install(tmp_path, complete=False))
    try:
        window.reload_client_data()

        assert window.is_setup_required()
        assert not window.start_button.isEnabled()
        assert window.start_button.toolTip() == Translator(Language.ENGLISH).text(
            Message.UI_SETUP_REQUIRED_STATUS
        )

        window._language_selector.setCurrentIndex(
            window._language_selector.findData(Language.GERMAN)
        )

        # The tooltip explains a disabled control, so it has to follow the language.
        assert window.start_button.toolTip() == Translator(Language.GERMAN).text(
            Message.UI_SETUP_REQUIRED_STATUS
        )
    finally:
        _dispose(window)


def test_a_complete_install_autoloads_its_artifacts_and_allows_arming(tmp_path: Path) -> None:
    window = _window(tmp_path, _install(tmp_path, complete=True))
    try:
        published: list[object] = []
        window.client_data_reloaded.connect(published.append)

        window.reload_client_data()

        assert not window.is_setup_required()
        assert window.start_button.isEnabled()
        assert window.start_button.toolTip() == ""
        # The join is published even when it resolves to ``None``: the live pipeline has to
        # learn what this install currently offers either way.
        assert len(published) == 1
    finally:
        _dispose(window)


def test_a_finished_wizard_reloads_every_artifact_without_an_application_restart(
    tmp_path: Path,
) -> None:
    window = _window(tmp_path, _install(tmp_path, complete=False))
    try:
        window.reload_client_data()
        assert window.is_setup_required()
        published: list[object] = []
        window.client_data_reloaded.connect(published.append)

        window.show_setup_wizard()
        wizard = window.setup_wizard
        assert wizard is not None
        _install(tmp_path, complete=True)
        wizard.setup_completed.emit(None)

        assert not window.is_setup_required()
        assert window.start_button.isEnabled()
        assert len(published) == 1
    finally:
        _dispose(window)


def test_a_catalog_written_for_another_schema_keeps_the_install_in_setup(tmp_path: Path) -> None:
    paths = _install(tmp_path, complete=True)
    mapping_path = tmp_path / "mover_labels.json"
    mapping_path.write_text("{}", encoding="utf-8")
    paths["client_catalog_path"].write_text(
        json.dumps({"schema_version": 999, "movers": []}), encoding="utf-8"
    )
    window = _window(tmp_path, {**paths, "mover_label_mapping_path": mapping_path})
    try:
        window.reload_client_data()

        assert window.mob_catalog_join is None
        assert window.is_setup_required()
        assert not window.start_button.isEnabled()
    finally:
        _dispose(window)


def test_first_run_detection_names_the_catalog_and_its_manifest(tmp_path: Path) -> None:
    paths = _install(tmp_path, complete=True)
    arguments = {
        "world_map_directory": paths["world_map_dir"],
        "quest_database": paths["quest_database_path"],
        "dungeon_database": paths["dungeon_database_path"],
        "position_profiles": paths["player_profiles_path"],
        "player_stats_profiles": paths["player_profiles_path"],
        "camera_profiles": paths["player_profiles_path"],
        "dungeon_profiles": paths["player_profiles_path"],
        "client_catalog": paths["client_catalog_path"],
        "source_manifest": paths["source_manifest_path"],
    }

    assert not UnifiedClientExtractor.is_first_run_required(**arguments)

    paths["source_manifest_path"].unlink()

    assert UnifiedClientExtractor.is_first_run_required(**arguments)


def test_a_fresh_install_with_no_extracted_data_autostarts_the_wizard(tmp_path: Path) -> None:
    window = _window(tmp_path, _install(tmp_path, complete=False))
    try:
        window.reload_client_data()

        assert window.is_setup_autostart_required()
    finally:
        _dispose(window)


def test_a_partial_install_opens_the_dashboard_without_autostarting_the_wizard(
    tmp_path: Path,
) -> None:
    paths = _install(tmp_path, complete=False)
    # A single extracted artifact is enough to skip the forced popup on launch (US-088).
    paths["quest_database_path"].write_text("{}", encoding="utf-8")
    window = _window(tmp_path, paths)
    try:
        window.reload_client_data()

        assert not window.is_setup_autostart_required()
        # The install is still incomplete, so arming stays blocked and explained.
        assert window.is_setup_required()
        assert not window.start_button.isEnabled()
    finally:
        _dispose(window)


def test_a_complete_install_does_not_autostart_the_wizard(tmp_path: Path) -> None:
    window = _window(tmp_path, _install(tmp_path, complete=True))
    try:
        window.reload_client_data()

        assert not window.is_setup_autostart_required()
    finally:
        _dispose(window)


# --------------------------------------------------------------------------------------
# Acceptance criterion 2: resilient readiness when no memory profile fits this build.
# --------------------------------------------------------------------------------------


def _gate_with_player_stats() -> LiveReadinessGate:
    gate = LiveReadinessGate()
    for source in (LiveStateSource.WINDOW_FOREGROUND, LiveStateSource.PLAYER_STATS):
        gate.register_provider(ProviderRegistration(source, 5.0))
    gate.register_capability(
        CapabilityRequirement(
            SessionCapability.COMBAT,
            frozenset({LiveStateSource.WINDOW_FOREGROUND, LiveStateSource.PLAYER_STATS}),
        )
    )
    gate.register_capability(
        CapabilityRequirement(
            SessionCapability.VITALS,
            frozenset({LiveStateSource.PLAYER_STATS}),
        )
    )
    gate.update(
        LiveProviderSample(LiveStateSource.WINDOW_FOREGROUND, ProviderHealth.HEALTHY, 1.0, "ok")
    )
    gate.update(
        LiveProviderSample(
            LiveStateSource.PLAYER_STATS,
            ProviderHealth.UNSUPPORTED,
            1.0,
            "unsupported_build",
        )
    )
    return gate


def test_a_demoted_source_stops_blocking_and_drops_the_capability_it_solely_carried() -> None:
    gate = _gate_with_player_stats()
    assert gate.evaluate(1.0).state is ReadinessState.BLOCKED

    assert gate.demote_source(LiveStateSource.PLAYER_STATS)
    status = gate.evaluate(1.0)

    assert status.state is ReadinessState.READY
    assert not status.action_blocked
    assert status.is_degraded(LiveStateSource.PLAYER_STATS)
    # Combat keeps running on the sources it still has; vitals had nothing else to stand on.
    assert [item.capability for item in status.capabilities] == [SessionCapability.COMBAT]


def test_demoting_the_same_source_twice_changes_nothing() -> None:
    gate = _gate_with_player_stats()

    assert gate.demote_source(LiveStateSource.PLAYER_STATS)
    assert not gate.demote_source(LiveStateSource.PLAYER_STATS)
    assert gate.evaluate(1.0).degraded_sources == (LiveStateSource.PLAYER_STATS,)


def test_the_readiness_panel_names_the_active_fallback() -> None:
    QApplication.instance() or QApplication([])
    translator = Translator(Language.ENGLISH)
    panel = ReadinessPanel(translator)
    gate = _gate_with_player_stats()
    gate.demote_source(LiveStateSource.PLAYER_STATS)

    panel.set_status(gate.evaluate(1.0))

    cells = (panel.table.item(row, 4) for row in range(panel.table.rowCount()))
    consequences = [cell.text() for cell in cells if cell is not None]
    assert translator.text(Message.UI_READINESS_DEGRADED) in consequences
    assert panel.summary_label.text() == translator.text(
        Message.UI_READINESS_SUMMARY_DEGRADED,
        source=translator.text(Message.UI_READINESS_SOURCE_PLAYER_STATS),
    )


class _UnsupportedStatsPipeline:
    """A pipeline whose exact client-memory reader never fits the running client build."""

    has_player_stats_provider = True

    def __init__(self, states: list[WorldState]) -> None:
        self._states = iter(states)
        self.demote_calls = 0

    def tick(
        self,
        _window_handle: int,
        _previous: WorldState,
        *,
        poll_live_providers: bool = True,
    ) -> PerceptionTick:
        del poll_live_providers
        return PerceptionTick(next(self._states), (), frozenset(), frame=None)

    def demote_player_stats_provider(self) -> bool:
        self.demote_calls += 1
        return True

    def close(self) -> None:
        return None


class _Adapter:
    """The narrow input surface the orchestrator drives, recording every dispatch."""

    def __init__(self) -> None:
        self.keys: list[tuple[int, float]] = []
        self.clicks: list[tuple[int, int, int]] = []
        self.closed_windows: list[int] = []

    def is_aborted(self) -> bool:
        return False

    def is_foreground(self, _window_handle: int) -> bool:
        return True

    def close_window(self, window_handle: int) -> bool:
        self.closed_windows.append(window_handle)
        return True

    def click_client(self, window_handle: int, x_coordinate: int, y_coordinate: int) -> None:
        self.clicks.append((window_handle, x_coordinate, y_coordinate))

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        self.keys.append((virtual_key, duration_seconds))

    def send_key_while_guarded(
        self, _window_handle: int, virtual_key: int, duration_seconds: float
    ) -> None:
        self.keys.append((virtual_key, duration_seconds))

    def send_keys_while_guarded(
        self,
        _window_handle: int,
        virtual_keys: tuple[int, ...] | list[int] | int,
        duration_seconds: float,
    ) -> None:
        keys = (virtual_keys,) if isinstance(virtual_keys, int) else tuple(virtual_keys)
        for key in keys:
            self.keys.append((key, duration_seconds))


def _unavailable_state(at_seconds: float, code: PlayerStatsReadErrorCode) -> WorldState:
    return WorldState(
        observed_at_seconds=at_seconds,
        position=Position(0, 0),
        nearby_mob_count=0,
        progress_marker=0,
        selected_target=SelectedTarget(TargetState.NONE, None, 0),
        viewport=Viewport(100, 100),
        player_vitals=PlayerVitals(100.0, 100.0, 100.0),
        player_stats_snapshot=ClientPlayerStatsSnapshot(
            PlayerStatsSource.UNAVAILABLE,
            error=PlayerStatsReadError(code),
        ),
    )


def test_an_unfingerprinted_build_falls_back_to_the_hud_instead_of_deadlocking(
    tmp_path: Path,
) -> None:
    unsupported = PlayerStatsReadErrorCode.UNSUPPORTED_BUILD
    states = [
        _unavailable_state(1.0, unsupported),
        _unavailable_state(1.0 + PLAYER_STATS_FALLBACK_GRACE_SECONDS, unsupported),
    ]
    pipeline = _UnsupportedStatsPipeline(states)
    logger = SessionEventLogger(tmp_path / "events")
    orchestrator = FarmingOrchestrator(
        cast(PerceptionPipeline, pipeline),
        _Adapter(),
        WINDOW_HANDLE,
        event_logger=logger,
    )
    orchestrator.start()

    blocked = orchestrator.tick()
    assert blocked.mode is FarmingMode.PAUSED
    assert blocked.readiness.action_blocked

    recovered = orchestrator.tick()

    assert pipeline.demote_calls == 1
    assert not recovered.readiness.action_blocked
    assert recovered.readiness.is_degraded(LiveStateSource.PLAYER_STATS)
    assert recovered.mode is not FarmingMode.PAUSED
    degraded = [
        event
        for event in logger.recent_events
        if event.kind is SessionEventKind.CAPABILITY_DEGRADED
    ]
    assert [event.reason for event in degraded] == [PLAYER_STATS_HUD_FALLBACK_REASON]


def test_a_focus_loss_never_demotes_the_exact_client_memory_reader() -> None:
    not_foreground = PlayerStatsReadErrorCode.WINDOW_NOT_FOREGROUND
    first = _unavailable_state(1.0, not_foreground)
    later = replace(first, observed_at_seconds=1.0 + PLAYER_STATS_FALLBACK_GRACE_SECONDS * 4.0)
    pipeline = _UnsupportedStatsPipeline([first, later])
    orchestrator = FarmingOrchestrator(
        cast(PerceptionPipeline, pipeline), _Adapter(), WINDOW_HANDLE
    )
    orchestrator.start()

    orchestrator.tick()
    orchestrator.tick()

    assert pipeline.demote_calls == 0


# --------------------------------------------------------------------------------------
# Acceptance criterion 4: guarded dispatch releases every held key on stop or focus loss.
# --------------------------------------------------------------------------------------


class _GuardedAdapter:
    """Records guarded dispatches and reports whichever guard the test wants to fail."""

    def __init__(self, *, aborted: bool = False, foreground: bool = True) -> None:
        self.aborted = aborted
        self.foreground = foreground
        self.chords: list[tuple[tuple[int, ...], float]] = []

    def is_aborted(self) -> bool:
        return self.aborted

    def is_foreground(self, _window_handle: int) -> bool:
        return self.foreground

    def send_key_while_guarded(
        self, _window_handle: int, virtual_key: int, duration_seconds: float
    ) -> None:
        self.chords.append(((virtual_key,), duration_seconds))

    def send_keys_while_guarded(
        self,
        _window_handle: int,
        virtual_keys: tuple[int, ...] | list[int] | int,
        duration_seconds: float,
    ) -> None:
        keys = (virtual_keys,) if isinstance(virtual_keys, int) else tuple(virtual_keys)
        self.chords.append((keys, duration_seconds))


@pytest.mark.parametrize(
    ("aborted", "foreground"),
    [(True, True), (False, False)],
)
def test_a_stopped_or_unfocused_client_is_never_sent_a_movement_key(
    aborted: bool, foreground: bool
) -> None:
    adapter = _GuardedAdapter(aborted=aborted, foreground=foreground)
    dispatcher = PathingInputDispatcher(adapter, WINDOW_HANDLE)
    decision = PathingDecision(
        PathingMode.TRAVELING,
        virtual_keys=(VIRTUAL_KEY_W,),
        key_press_duration_seconds=0.2,
    )

    assert not dispatcher.dispatch(decision)
    assert adapter.chords == []


def test_a_safe_client_receives_the_whole_movement_chord_at_once() -> None:
    adapter = _GuardedAdapter()
    dispatcher = PathingInputDispatcher(adapter, WINDOW_HANDLE)
    decision = PathingDecision(
        PathingMode.TRAVELING,
        virtual_keys=(VIRTUAL_KEY_W, VIRTUAL_KEY_A),
        key_press_duration_seconds=0.2,
    )

    assert dispatcher.dispatch(decision)
    assert adapter.chords == [((VIRTUAL_KEY_W, VIRTUAL_KEY_A), 0.2)]


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Win32 platform")
@pytest.mark.parametrize("guard", ["aborted", "unfocused"])
def test_every_held_key_is_released_as_soon_as_a_guard_trips(
    monkeypatch: pytest.MonkeyPatch, guard: str
) -> None:
    controller = WindowsInputController()
    dispatched: list[tuple[list[int], list[int]]] = []

    def mock_send_input(count: int, events: ctypes.Array[Input], _size: int) -> int:
        dispatched.append(
            (
                [events[index].keyboard.wVk for index in range(count)],
                [events[index].keyboard.dwFlags for index in range(count)],
            )
        )
        return count

    monkeypatch.setattr(controller, "is_aborted", lambda: guard == "aborted")
    monkeypatch.setattr(controller, "is_foreground", lambda _handle: guard != "unfocused")
    monkeypatch.setattr(controller._user32, "SendInput", mock_send_input)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    controller.send_keys_while_guarded(WINDOW_HANDLE, (VIRTUAL_KEY_W, VIRTUAL_KEY_A), 30.0)

    # The hold never waits out its duration; both keys come back up in the same batch.
    keys_up, flags = dispatched[-1]
    assert keys_up == [VIRTUAL_KEY_W, VIRTUAL_KEY_A]
    assert set(flags) == {KEY_EVENT_KEY_UP}


# --------------------------------------------------------------------------------------
# Acceptance criterion 2: the demoted pipeline keeps reporting vitals from the HUD.
# --------------------------------------------------------------------------------------


class _HudVitalsReader:
    def __init__(self, vitals: PlayerVitals) -> None:
        self._vitals = vitals
        self.read_calls = 0

    def read(self, _frame: object) -> PlayerVitals:
        self.read_calls += 1
        return self._vitals


class _MemoryStatsReader:
    def __init__(self, snapshot: ClientPlayerStatsSnapshot) -> None:
        self._snapshot = snapshot
        self.close_calls = 0

    def poll(self, _at_seconds: float) -> ClientPlayerStatsSnapshot:
        return self._snapshot

    def close(self) -> None:
        self.close_calls += 1


def test_a_demoted_pipeline_reads_vitals_from_the_hud_and_releases_the_client_handle() -> None:
    hud = _HudVitalsReader(PlayerVitals(55.0, 44.0, 33.0))
    memory = _MemoryStatsReader(
        ClientPlayerStatsSnapshot(
            PlayerStatsSource.UNAVAILABLE,
            error=PlayerStatsReadError(PlayerStatsReadErrorCode.UNSUPPORTED_BUILD),
        )
    )
    pipeline = PerceptionPipeline(
        _FrameSource(),
        _Detector([]),
        _TargetVerifier(TargetVerificationResult(TargetStatus.NO_TARGET, None, 0)),
        vitals_reader=hud,
        player_stats_reader=memory,
        clock=lambda: OBSERVED_AT_SECONDS,
    )
    assert pipeline.has_player_stats_provider

    assert pipeline.demote_player_stats_provider()
    assert not pipeline.demote_player_stats_provider()
    tick = pipeline.tick(WINDOW_HANDLE, _previous_state())

    assert not pipeline.has_player_stats_provider
    assert memory.close_calls == 1
    assert hud.read_calls == 1
    assert tick.state.player_vitals == PlayerVitals(55.0, 44.0, 33.0)
