---
id: US-033
title: Automated Tesseract OCR installation via winget and live reload
status: draft
created: 2026-08-18
updated: 2026-08-18
---

# US-033: Automated Tesseract OCR installation via winget and live reload

## Story

As a **bot operator on Windows**, I want **the desktop UI to detect a missing Tesseract OCR engine, inform me, and offer a one-click automated background installation via `winget` as well as live re-detection**, so that **I can enable OCR capabilities (target name verification and monster kill stats) without manually tracking down installers, configuring system paths, or restarting the bot**.

## Context and assumptions

- [Architecture](../../wiki/architecture.md) (US-005, US-030, US-032, BUG-011, BUG-012).
- Windows 10 / 11 is the sole target platform, and `winget` (Windows Package Manager) is pre-installed on supported Windows builds.
- Tesseract OCR is provided via the official UB-Mannheim Windows package ID `UB-Mannheim.TesseractOCR` (`winget install --id UB-Mannheim.TesseractOCR --exact --accept-source-agreements --accept-package-agreements`).
- Standard installation places `tesseract.exe` into `C:\Program Files\Tesseract-OCR\tesseract.exe` (probed by `resolve_tesseract_executable()`).
- Only the standard English (`eng`) language dataset is required for target name and monster statistics OCR.
- The installation process must run asynchronously (e.g. in a background thread / QThread) so the PySide6 Qt GUI thread remains responsive.
- Once installation finishes, active OCR readers (`MonsterStatsReader`, `TargetVerifier`, `LootReader`) should automatically re-evaluate executable availability without requiring an application restart.

## Acceptance criteria

- [ ] When an OCR feature encounters `LootOcrErrorCode.ENGINE_UNAVAILABLE` or `MonsterStatsStatus.ENGINE_UNAVAILABLE`, the UI provides an actionable prompt/action indicating that Tesseract OCR is not installed.
- [ ] The UI offers a direct action (e.g., "Install Tesseract OCR" / "Tesseract OCR installieren") to trigger automated background installation via `winget`.
- [ ] The UI also displays or allows copying the manual installation command (`winget install --id UB-Mannheim.TesseractOCR --exact --accept-source-agreements --accept-package-agreements`) as a fallback reference.
- [ ] When the operator initiates automated installation, the execution runs in a non-blocking background worker without freezing the dashboard UI or perception loop.
- [ ] The UI provides visual status feedback during installation (e.g., "Installing OCR engine...", "Installation completed successfully", or "Installation failed").
- [ ] If `winget` is missing, permissions are denied (UAC cancelled), or the process exits with an error, the failure is reported clearly to the operator with actionable guidance.
- [ ] Upon successful installation, the application triggers a live reload/re-check of `resolve_tesseract_executable()`, transitioning the OCR status from `ENGINE_UNAVAILABLE` to ready without restarting the application.
- [ ] All user-visible dialog messages, buttons, and status labels are synchronized in German and English in `../../../src/flyff_bot/locales/de.json` and `../../../src/flyff_bot/locales/en.json`.

## Out of scope

- Bundling static Tesseract binary files or `.traineddata` packages inside the Git repository.
- Supporting third-party Linux/macOS package managers (Windows with `winget` is the exclusive target).
- Downloading or managing multilingual language packs beyond the default English (`eng`) model.
- Automatically elevating permissions without standard Windows UAC user confirmation prompts.

## Verification

- Automated:
  - Unit tests in `../../../tests/unit` for the installation worker / runner with mocked `subprocess` / `winget` outcomes (success, UAC cancellation, missing executable).
  - Unit tests verifying live re-evaluation of `resolve_tesseract_executable()` and dynamic recovery of `MonsterStatsReader` / `TargetVerifier` without restarting the process.
  - Locale synchronization check in `../../../tests/unit/test_i18n.py`.
- Manual (Windows):
  - On a clean Windows machine without Tesseract installed, launch `flyff-bot ui`.
  - Verify that the UI displays the missing OCR engine prompt and the install button.
  - Click "Install Tesseract OCR", approve the Windows UAC prompt, and verify successful background installation.
  - Verify that the dashboard status transitions to ready and monster stats / target OCR begin functioning immediately without restarting the application.
