$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$repositoryRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$env:UV_CACHE_DIR = Join-Path $repositoryRoot ".uv-cache"
$pytestTemp = Join-Path ([IO.Path]::GetTempPath()) "flyff-bot-pytest"
$env:PYTEST_ADDOPTS = "--basetemp=""$pytestTemp"""

uv sync --locked
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy
uv run pytest
