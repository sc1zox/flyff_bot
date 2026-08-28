"""Every entry point must import from a cold interpreter (US-086).

`flyff_bot.cli` and `flyff_bot.ui.app` were both unimportable on their own: the automation
package re-exported the orchestrator, and the navigation feature imported the UI layer, so the
import graph closed a cycle that only a test conftest importing navigation first ever hid.
Each module is imported in its own subprocess, because once one of them succeeds inside this
process `sys.modules` would mask the very failure being guarded against.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

ENTRY_POINTS = (
    "flyff_bot.cli",
    "flyff_bot.ui.app",
    "flyff_bot.ui.main_window",
    "flyff_bot.features.automation",
    "flyff_bot.features.automation.autopilot",
    "flyff_bot.features.automation.orchestrator",
    "flyff_bot.features.navigation",
    "flyff_bot.features.policy",
    "flyff_bot.features.quests",
    "flyff_bot.features.rl",
    "flyff_bot.features.telemetry",
    "flyff_bot.features.vision",
)
IMPORT_TIMEOUT_SECONDS = 120.0


@pytest.mark.parametrize("module", ENTRY_POINTS)
def test_module_imports_from_a_cold_interpreter(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=IMPORT_TIMEOUT_SECONDS,
        check=False,
    )

    assert result.returncode == 0, result.stderr
