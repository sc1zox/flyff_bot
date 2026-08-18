"""OCR engine interface and Tesseract adapter for vision features."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
import numpy.typing as npt

TESSERACT_EXECUTABLE = "tesseract"
# The official Windows installer does not extend the system PATH, so its documented default
# install directories are probed before the engine is declared unavailable.
TESSERACT_INSTALL_CANDIDATES = (
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
)
# For regions rendered in English only (e.g. HUD stats).
TESSERACT_LANGUAGE_ENGLISH = "eng"
TESSERACT_LANGUAGE = "eng+deu"
TESSERACT_PAGE_SEGMENTATION_MODE = 6
TESSERACT_TIMEOUT_SECONDS = 10.0
_TESSERACT_INPUT_FILENAME = "ocr-roi.png"
_TESSERACT_CONFIG_ARGUMENT = "--psm"
_TESSERACT_OUTPUT_FORMAT = "stdout"
# Tesseract writes UTF-8, while Python decodes pipes with the platform ANSI code page
# (CP1252 on Windows). Both are pinned so recognition never fails on a stray byte.
_TESSERACT_OUTPUT_ENCODING = "utf-8"
_TESSERACT_DECODE_ERROR_STRATEGY = "replace"


class OcrErrorCode(StrEnum):
    """Known OCR failures that presentation code can localize."""

    ENGINE_UNAVAILABLE = "engine_unavailable"
    RECOGNITION_FAILED = "recognition_failed"


# Backward compatibility aliases
LootOcrErrorCode = OcrErrorCode


class OcrError(RuntimeError):
    """A failure while turning an image region into text via OCR."""

    def __init__(self, code: OcrErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


# Backward compatibility alias
LootOcrError = OcrError


class TextRecognizer(Protocol):
    """An OCR engine capable of reading text from an image region."""

    def recognize(self, image: npt.NDArray[np.uint8]) -> Iterable[str]:
        """Return recognized text lines from a monochrome or colour image."""


def resolve_tesseract_executable() -> str:
    """Return the Tesseract command to invoke, probing the known install locations.

    PATH wins, then the documented Windows install directories. When nothing is found the
    bare command name is returned so the invocation still fails with `ENGINE_UNAVAILABLE`
    rather than this lookup raising on its own.
    """

    located = shutil.which(TESSERACT_EXECUTABLE)
    if located is not None:
        return located
    for candidate in TESSERACT_INSTALL_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    return TESSERACT_EXECUTABLE


class TesseractTextRecognizer:
    """Production OCR adapter for a locally installed Tesseract executable."""

    def __init__(self, executable: str | None = None, language: str = TESSERACT_LANGUAGE) -> None:
        self._executable = executable or resolve_tesseract_executable()
        self._language = language

    def recognize(self, image: npt.NDArray[np.uint8]) -> tuple[str, ...]:
        success, encoded_image = cv2.imencode(".png", image)
        if not success:
            raise OcrError(OcrErrorCode.RECOGNITION_FAILED)
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory, _TESSERACT_INPUT_FILENAME)
            image_path.write_bytes(encoded_image.tobytes())
            try:
                result = subprocess.run(
                    [
                        self._executable,
                        str(image_path),
                        _TESSERACT_OUTPUT_FORMAT,
                        "-l",
                        self._language,
                        _TESSERACT_CONFIG_ARGUMENT,
                        str(TESSERACT_PAGE_SEGMENTATION_MODE),
                    ],
                    capture_output=True,
                    check=True,
                    text=True,
                    encoding=_TESSERACT_OUTPUT_ENCODING,
                    errors=_TESSERACT_DECODE_ERROR_STRATEGY,
                    timeout=TESSERACT_TIMEOUT_SECONDS,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                raise OcrError(OcrErrorCode.RECOGNITION_FAILED) from error
            except OSError as error:
                # A missing binary raises FileNotFoundError; one that exists but cannot be
                # executed raises another OSError. Both mean the engine is unusable.
                raise OcrError(OcrErrorCode.ENGINE_UNAVAILABLE) from error
        return tuple(line for line in result.stdout.splitlines() if line.strip())
