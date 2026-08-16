# Verify Suite Command

Run the full project verification suite to ensure code quality, formatting, type checking, and test coverage:

```powershell
pwsh -File .\scripts\check.ps1
```

Or individual checks:
- `uv sync --locked`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy`
- `uv run pytest`
