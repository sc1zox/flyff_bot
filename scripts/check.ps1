$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
