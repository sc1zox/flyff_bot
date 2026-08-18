---
id: BUG-002
title: TypeError on null foreground window handle during guarded search key dispatch
status: resolved
severity: high
created: 2026-08-16
updated: 2026-08-16
---

# BUG-002: TypeError on null foreground window handle during guarded search key dispatch

## Environment

- Windows version: Windows 10/11
- Python version: 3.14 (.venv)
- Application revision: HEAD (main)
- Client/server version: Entropia Flyff PServer (neuz.exe)

## Reproduction

1. Start the bot / farming session in search mode (`SEARCHING`).
2. Trigger a guarded key dispatch during search (e.g. `SearchInputDispatcher.dispatch(...)` calling `WindowsInputAdapter.send_key_while_guarded(...)`).
3. While the key is being held or when checking foreground status, switch windows or let the active window transition so `GetForegroundWindow()` returns `NULL` / `None`.
4. Observe the unhandled exception in the terminal:
   ```text
   TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType'
   ```

## Expected behavior

`is_foreground(window_handle)` in `WindowsInputAdapter` and `WindowsCaptureApi` should handle `None` / `0` / `NULL` handles safely and return `False` without raising an exception when no window is currently foregrounded.

## Actual behavior

`int(self._user32.GetForegroundWindow()) == window_handle` unconditionally calls `int(...)` on the return value of `GetForegroundWindow()`. When ctypes returns `None` (representing `HWND(0)` or `NULL`), Python raises a `TypeError`, terminating the orchestrator tick loop:
```text
Traceback (most recent call last):
  File "I:\coding projects\flyff_bot\src\flyff_bot\features\automation\orchestrator.py", line 180, in tick
    dispatched = self._advance(perception)
  File "I:\coding projects\flyff_bot\src\flyff_bot\features\automation\orchestrator.py", line 207, in _advance
    return self._search_dispatcher.dispatch(
        self._search.step(self._state.observed_at_seconds, radar_position)
    )
  File "I:\coding projects\flyff_bot\src\flyff_bot\features\automation\search_execution.py", line 39, in dispatch
    self._adapter.send_key_while_guarded(
        self._window_handle, decision.virtual_key, decision.key_press_duration_seconds
    )
  File "I:\coding projects\flyff_bot\src\flyff_bot\features\input_control\controller.py", line 228, in send_key_while_guarded
    and self.is_foreground(window_handle)
  File "I:\coding projects\flyff_bot\src\flyff_bot\features\input_control\controller.py", line 186, in is_foreground
    return int(self._user32.GetForegroundWindow()) == window_handle
TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType'
```

## Impact and frequency

- Impact: High. An asynchronous window transition or lost focus crashes the bot process instead of safely pausing or aborting key dispatch.
- Frequency: Occurs whenever focus shifts or `GetForegroundWindow()` returns `NULL` during active search or capture polling.

## Regression verification

- [x] A failing automated test reproducing `is_foreground` behavior when `GetForegroundWindow` returns `None`/`0`.
- [x] The check passes after the fix (returns `False` cleanly).
- [x] Related documentation is current.
