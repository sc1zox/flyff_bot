---
id: BUG-013
title: Tesseract OCR subprocess UnicodeDecodeError on Windows CP1252
status: reported
severity: medium
created: 2026-08-18
updated: 2026-08-18
---

# BUG-013: Tesseract OCR subprocess UnicodeDecodeError on Windows CP1252

## Environment

- Windows version: Windows 10 / 11 (64-bit)
- Python version: 3.14.7
- Application revision: main
- Client/server version: Flyff Universe / Flyff PC Client with PySide6 desktop dashboard

## Reproduction

1. On a Windows host with system ANSI code page set to CP1252, launch the desktop UI (`uv run python -m flyff_bot ui`).
2. Run the application in standby preview mode or active farming with an active game window.
3. When Tesseract OCR processes a target name, monster stats, or loot region containing visual noise or non-ASCII characters that output multi-byte UTF-8 byte sequences (e.g. byte `0x9d`), observe the terminal output.

## Expected behavior

`TesseractTextRecognizer.recognize()` should decode `subprocess.run()` output explicitly as UTF-8 (with resilient error handling such as `errors="replace"`), avoiding platform-dependent ANSI (`cp1252`) decoding failures and unhandled `_readerthread` exceptions on Windows.

## Actual behavior

`TesseractTextRecognizer.recognize()` in `src/flyff_bot/features/vision/loot_ocr.py` calls `subprocess.run()` with `text=True` but omits `encoding="utf-8"`:
```python
result = subprocess.run(
    [
        self._executable,
        str(image_path),
        _TESSERACT_OUTPUT_FORMAT,
        "-l",
        TESSERACT_LANGUAGE,
        _TESSERACT_CONFIG_ARGUMENT,
        str(TESSERACT_PAGE_SEGMENTATION_MODE),
    ],
    capture_output=True,
    check=True,
    text=True,
    timeout=TESSERACT_TIMEOUT_SECONDS,
)
```
On Windows, Python's `subprocess.Popen` / `subprocess.run` falls back to `locale.getpreferredencoding()` (CP1252 / charmap). When Tesseract outputs UTF-8 characters that contain bytes not present in CP1252 (such as `0x9d`), `subprocess.py`'s internal `_readerthread` raises:
```
Exception in thread Thread-XXXX (_readerthread):
Traceback (most recent call last):
  File "threading.py", line 1082, in _bootstrap_inner
    self._context.run(self.run)
  File "threading.py", line 1024, in run
    self._target(*self._args, **self._kwargs)
  File "subprocess.py", line 1614, in _readerthread
    buffer.append(fh.read())
  File "encodings\cp1252.py", line 23, in decode
    return codecs.charmap_decode(input,self.errors,decoding_table)[0]
UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d in position ...: character maps to <undefined>
```
Because the UI standby tick continuously executes perception feeds, hundreds of thread exceptions spam stderr.

## Impact and frequency

- **Impact:** Terminal stderr is flooded with unhandled background thread stack traces, and OCR-based features (monster stats kill count tracking, target name verification, and loot log OCR) fail to read text whenever non-ASCII or multi-byte UTF-8 characters are returned by Tesseract.
- **Frequency:** 100% reproducible on Windows systems when Tesseract emits non-CP1252 UTF-8 byte sequences.

## Regression verification

- [ ] `TesseractTextRecognizer.recognize()` specifies `encoding="utf-8"` and `errors="replace"` in `subprocess.run()`.
- [ ] Automated unit tests in `tests/unit/test_loot_ocr.py` verify that `TesseractTextRecognizer` successfully decodes UTF-8 and non-CP1252 character streams without raising `UnicodeDecodeError`.
- [ ] Related documentation is current.
