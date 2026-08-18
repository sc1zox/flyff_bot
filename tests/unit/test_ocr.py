"""Unit tests for OCR text recognition, executable resolution, and UTF-8 decoding."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from flyff_bot.features.vision.ocr import (
    TESSERACT_EXECUTABLE,
    OcrError,
    OcrErrorCode,
    TesseractTextRecognizer,
    resolve_tesseract_executable,
)


def test_recognizer_prefers_an_executable_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/tesseract")

    assert resolve_tesseract_executable() == "/usr/bin/tesseract"


def test_recognizer_falls_back_to_a_known_windows_install_location(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The official Windows installer does not extend PATH, which is BUG-012's root cause."""

    installed = tmp_path / "tesseract.exe"
    installed.write_bytes(b"")
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr("flyff_bot.features.vision.ocr.TESSERACT_INSTALL_CANDIDATES", (installed,))

    assert resolve_tesseract_executable() == str(installed)


def test_recognizer_falls_back_to_the_bare_command_when_nothing_is_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        "flyff_bot.features.vision.ocr.TESSERACT_INSTALL_CANDIDATES", (tmp_path / "absent.exe",)
    )

    assert resolve_tesseract_executable() == TESSERACT_EXECUTABLE


def test_recognizer_reports_an_unavailable_engine_for_a_missing_executable(
    tmp_path: Path,
) -> None:
    recognizer = TesseractTextRecognizer(str(tmp_path / "absent.exe"))

    try:
        recognizer.recognize(np.full((32, 64), 255, dtype=np.uint8))
    except OcrError as error:
        assert error.code is OcrErrorCode.ENGINE_UNAVAILABLE
    else:
        raise AssertionError("A missing Tesseract executable was not reported as unavailable.")


def test_recognizer_decodes_engine_output_as_utf_8_with_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BUG-013: the engine invocation must not inherit the platform ANSI code page."""

    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "Flame <Lvl 175>\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    lines = TesseractTextRecognizer("tesseract").recognize(np.full((32, 64), 255, dtype=np.uint8))

    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    assert lines == ("Flame <Lvl 175>",)


@pytest.mark.skipif(
    sys.platform == "win32", reason="The stub engine requires a POSIX executable script."
)
def test_recognizer_survives_undecodable_engine_output(tmp_path: Path) -> None:
    """Byte 0x9d is neither valid UTF-8 nor mapped by CP1252, which is BUG-013's trigger."""

    stub = tmp_path / "tesseract-stub"
    stub.write_text(
        f"#!{sys.executable}\nimport os, sys\nos.write(1, b'Item \\x9d name\\n')\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)

    lines = TesseractTextRecognizer(str(stub)).recognize(np.full((32, 64), 255, dtype=np.uint8))

    assert lines == ("Item  name",)
