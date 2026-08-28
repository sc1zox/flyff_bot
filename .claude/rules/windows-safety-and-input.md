---
description: Win32 API usage, input simulation, foreground checks, and emergency stop safety
globs: src/**/input_control/**/*.py,src/**/platform/**/*.py
alwaysApply: false
---

# Windows Safety & Input

Strict safety and platform interaction rules for Windows Win32 API.

## 1. Foreground Window Enforcement

- **Foreground Check**: Before sending any keyboard or mouse event via `SendInput` / Win32, verify that the game window is currently the foreground window (`GetForegroundWindow` matching game window title/PID).
- **Auto-Pause**: If the game window loses focus, immediately release all pressed keys and pause reactive execution.

## 2. Emergency Stop (Killswitch)

- The global `F12` hotkey must immediately halt all bot actions. It is read with both held and pressed-since-last-query state so a short press is not missed; `ESC` is never a killswitch because it is an ordinary dialogue key.
- The dashboard and map windows bind the same `F12` key, so the operator never has to remember
  a second shortcut depending on which window has focus.
- The emergency stop must release all held virtual keys, stop worker loops, and update status to halted.

## 3. Explicit Safety Boundaries

- **NO Process Memory Injection**: Never use `OpenProcess` with `PROCESS_VM_WRITE`, `WriteProcessMemory`, or inject DLLs.
- **NO Anti-Cheat Evasion**: Do not implement hook-hiding, driver manipulation, or stealth bypasses.
- **Documented APIs Only**: Use standard Windows APIs with proper error checks and typed `ctypes` structures.
