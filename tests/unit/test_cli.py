"""Unit tests for command orchestration without sending real Windows input."""

from __future__ import annotations

from pathlib import Path

from _pytest.capture import CaptureFixture
from _pytest.monkeypatch import MonkeyPatch
from world_fixtures import (
    flat_heights,
    respawn_record,
    unsupported_archive_index,
    write_world_directory,
)

import flyff_bot.cli as cli
from flyff_bot.constants import ExitCode
from flyff_bot.features.automation.orchestrator import FarmingMode
from flyff_bot.features.input_control.models import WindowRef
from flyff_bot.features.vision import (
    FrameCaptureError,
    FrameCaptureErrorCode,
    OpenCVDnnYoloDetector,
)
from flyff_bot.i18n import Language, Translator


class FakeController:
    """Record CLI calls while avoiding interaction with another process."""

    def __init__(self, windows: list[WindowRef] | None = None, *, aborted: bool = False) -> None:
        self.windows = windows or []
        self.aborted = aborted
        self.focused_handle: int | None = None
        self.sent_key: tuple[int, float] | None = None
        self.sent_click: tuple[int, int, int] | None = None

    def find_windows(self, _process_name: str) -> list[WindowRef]:
        return self.windows

    def focus_window(self, window_handle: int) -> None:
        self.focused_handle = window_handle

    def is_aborted(self) -> bool:
        return self.aborted

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        self.sent_key = (virtual_key, duration_seconds)

    def click_client(self, window_handle: int, x_coordinate: int, y_coordinate: int) -> None:
        self.sent_click = (window_handle, x_coordinate, y_coordinate)


def _use_controller(monkeypatch: MonkeyPatch, controller: FakeController) -> None:
    monkeypatch.setattr(cli, "WindowsInputController", lambda: controller)


def test_list_prints_matching_windows(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    controller = FakeController([WindowRef(handle=42, title="Flyff")])
    _use_controller(monkeypatch, controller)

    exit_code = cli.main(["--language", "en", "--list"])

    output = capsys.readouterr()
    assert exit_code == ExitCode.SUCCESS
    assert "HWND=42" in output.out
    assert controller.focused_handle is None


def test_missing_window_returns_stable_error(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    _use_controller(monkeypatch, FakeController())

    exit_code = cli.main(["--language", "en", "--process", "missing.exe", "--list"])

    output = capsys.readouterr()
    assert exit_code == ExitCode.WINDOW_NOT_FOUND
    assert "missing.exe" in output.err


def test_key_action_focuses_window_and_sends_parsed_key(monkeypatch: MonkeyPatch) -> None:
    controller = FakeController([WindowRef(handle=42, title="Flyff")])
    _use_controller(monkeypatch, controller)

    exit_code = cli.main(["--language", "en", "--key", "F2", "--delay", "0", "--duration", "0.2"])

    assert exit_code == ExitCode.SUCCESS
    assert controller.focused_handle == 42
    assert controller.sent_key == (0x71, 0.2)


def test_farm_rotation_key_accepts_function_keys() -> None:
    arguments = cli._argument_parser(Translator(Language.ENGLISH)).parse_args(
        ["--farm", "--rotation-key", "F3"]
    )

    assert arguments.rotation_key == [0x72]


def test_click_action_sends_client_coordinates(monkeypatch: MonkeyPatch) -> None:
    controller = FakeController([WindowRef(handle=42, title="Flyff")])
    _use_controller(monkeypatch, controller)

    exit_code = cli.main(["--language", "de", "--click", "10", "20", "--delay", "0"])

    assert exit_code == ExitCode.SUCCESS
    assert controller.sent_click == (42, 10, 20)


def test_emergency_stop_aborts_before_input(monkeypatch: MonkeyPatch) -> None:
    controller = FakeController([WindowRef(handle=42, title="Flyff")], aborted=True)
    _use_controller(monkeypatch, controller)

    exit_code = cli.main(["--language", "en", "--key", "W", "--delay", "0"])

    assert exit_code == ExitCode.ABORTED
    assert controller.sent_key is None


def test_validate_dataset_does_not_access_a_game_window(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    _use_controller(monkeypatch, FakeController())
    monkeypatch.setattr(
        cli, "validate_dataset", lambda _path: type("Result", (), {"is_valid": True})()
    )

    exit_code = cli.main(["--language", "en", "--validate-mob-dataset"])

    assert exit_code == ExitCode.SUCCESS
    assert "Mob dataset is valid" in capsys.readouterr().out


def test_detect_mobs_handles_minimized_window_gracefully(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    controller = FakeController([WindowRef(handle=42, title="Flyff")])
    _use_controller(monkeypatch, controller)

    class FailingFrameSource:
        def capture(self, _handle: int) -> None:
            raise FrameCaptureError(FrameCaptureErrorCode.MINIMIZED)

    monkeypatch.setattr(cli, "WindowsFrameSource", FailingFrameSource)
    monkeypatch.setattr(OpenCVDnnYoloDetector, "from_files", lambda *args, **kwargs: object())

    exit_code = cli.main(
        [
            "--language",
            "de",
            "--detect-mobs",
            "--model",
            "dummy.onnx",
            "--labels",
            "dummy.txt",
            "--delay",
            "0",
        ]
    )

    assert exit_code == ExitCode.DETECTION_FAILURE
    assert "Das Flyff-Fenster ist minimiert" in capsys.readouterr().err


def test_auto_alias_starts_the_farming_orchestrator(monkeypatch: MonkeyPatch) -> None:
    controller = FakeController([WindowRef(handle=42, title="Flyff")])
    _use_controller(monkeypatch, controller)

    class FakeOrchestrator:
        mode = FarmingMode.COMPLETED

        def __init__(self) -> None:
            self.started = False
            self.closed = False

        def start(self) -> None:
            self.started = True

        async def run(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    orchestrator = FakeOrchestrator()
    monkeypatch.setattr(cli, "_farming_orchestrator", lambda *_args: orchestrator)

    exit_code = cli.main(["--language", "en", "--auto", "--delay", "0"])

    assert exit_code == ExitCode.SUCCESS
    assert orchestrator.started
    assert orchestrator.closed


def test_search_settle_cli_options() -> None:
    arguments = cli._argument_parser(Translator(Language.ENGLISH)).parse_args(
        [
            "--farm",
            "--search-settle-pause",
            "0.35",
        ]
    )

    assert arguments.search_settle_pause == 0.35


def test_extract_world_writes_a_map_and_its_height_fields_without_a_game_window(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    root = tmp_path / "client"
    write_world_directory(
        root,
        "wdtest",
        region_records=[respawn_record(1453, (10.0, 0.0, 10.0), (0, 0, 20, 20), 4, 30)],
        archived_blocks=[
            (block_x, block_z, flat_heights(50.0)) for block_x in range(2) for block_z in range(2)
        ],
    )
    output = tmp_path / "worlds"

    exit_code = cli.main(
        [
            "--extract-world",
            "--client-world-root",
            str(root),
            "--world-map-directory",
            str(output),
            "--language",
            "en",
        ]
    )

    assert exit_code == ExitCode.SUCCESS
    assert (output / "wdtest.json").is_file()
    assert len(list((output / "wdtest").glob("*.lnd"))) == 4
    printed = capsys.readouterr().out
    assert "4 of 4 terrain blocks" in printed
    assert "1 regions extracted" in printed


def test_extract_world_optionally_bakes_a_persisted_navmesh_without_a_game_window(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: MonkeyPatch
) -> None:
    root = tmp_path / "client"
    write_world_directory(root, "wdtest", blocks=[(0, 0, flat_heights(50.0))])
    output = tmp_path / "worlds"
    monkeypatch.setattr(cli, "terrain_triangles", lambda _blocks, _dimensions: ())

    exit_code = cli.main(
        [
            "--extract-world",
            "--bake-navmesh",
            "--client-world-root",
            str(root),
            "--world-map-directory",
            str(output),
            "--language",
            "en",
        ]
    )

    assert exit_code == ExitCode.SUCCESS
    assert (output / "wdtest.navmesh.json").is_file()
    assert "baked 0 NavMesh polygons" in capsys.readouterr().out


def test_extract_world_reports_an_unreadable_archive_and_keeps_going(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    root = tmp_path / "client"
    directory = write_world_directory(root, "wdtest", blocks=[(0, 0, flat_heights(50.0))])
    (directory / "wdtest.hdr").write_bytes(unsupported_archive_index())
    (directory / "wdtest.one").write_bytes(b"")

    exit_code = cli.main(
        [
            "--extract-world",
            "--client-world-root",
            str(root),
            "--world-map-directory",
            str(tmp_path / "worlds"),
            "--language",
            "en",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == ExitCode.SUCCESS
    assert "unsupported layout" in captured.err
    assert "1 of 4 terrain blocks" in captured.out


def test_extract_world_without_a_client_region_fails_with_a_localized_reason(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    exit_code = cli.main(
        [
            "--extract-world",
            "--client-world-root",
            str(tmp_path / "missing"),
            "--world-map-directory",
            str(tmp_path / "worlds"),
            "--language",
            "de",
        ]
    )

    assert exit_code == ExitCode.WORLD_EXTRACTION_FAILURE
    assert "keine Client-Region" in capsys.readouterr().err
