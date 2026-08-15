"""Unit tests for command orchestration without sending real Windows input."""

from __future__ import annotations

from _pytest.capture import CaptureFixture
from _pytest.monkeypatch import MonkeyPatch

import flyff_bot.cli as cli
from flyff_bot.constants import ExitCode
from flyff_bot.features.input_control.models import WindowRef


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
