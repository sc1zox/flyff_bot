# Flyff Bot

Windows-first Python tooling for controlling a visible Flyff client through documented Win32 input
APIs. The current feature is a small input-control proof of concept. Use it only where the server
rules explicitly permit automation.

## Setup (PowerShell)

Prerequisites: Windows, Git, and [uv](https://docs.astral.sh/uv/). The repository pins the current
stable Python 3.14 line in `.python-version`; `uv` installs it and creates `.venv` automatically.

```powershell
uv sync
uv run flyff-bot --list
```

Examples:

```powershell
# Press F1 after three seconds
uv run flyff-bot --key F1

# Hold W for one second
uv run flyff-bot --key W --duration 1

# Click a client-relative position
uv run flyff-bot --click 400 300

# Force English UI text
uv run flyff-bot --language en --list
```

Press `END` to abort a waiting or running action. If the client runs elevated, the terminal must
usually run elevated as well because Windows blocks lower-integrity processes from sending input to
higher-integrity processes.

## Mob-detector training

Place annotated screenshots in the standard YOLO dataset at `data/datasets/mobs/`: images and their
matching `.txt` annotations belong in the corresponding `images/train`, `images/val`,
`labels/train`, and `labels/val` directories. Each annotation line is
`class_id center_x center_y width height`, with normalized coordinates. Add each monster to the
numeric `names` registry in `data/datasets/mobs/data.yaml`; registry order becomes the model's
label order.

Validate the dataset before training. Training is an optional local dependency and writes the model
artifacts `models/mob_detector.onnx` and `models/labels.txt`.

```powershell
uv run flyff-bot --validate-mob-dataset
uv sync --extra training
uv run flyff-bot --train-mob-detector --epochs 100
```

The validation and training commands do not access or control a game window. To use the exported
model with live detection, supply both artifact paths to the existing detection command.

```powershell
uv run flyff-bot --detect-mobs --model models/mob_detector.onnx --labels models/labels.txt
```

## Repository map

```text
src/flyff_bot/             Application package
  features/input_control/  Feature-owned Win32 input implementation
  locales/                 German and English UI resources
tests/unit/                Fast, platform-independent unit tests
docs/sources/              Immutable source material for the LLM wiki
docs/wiki/                 Agent-maintained, linked project knowledge
docs/user-stories/         Feature requests and acceptance criteria
docs/bugs/                 Reproduction steps and regression criteria
docs/decisions/            Durable architecture decisions
scripts/check.ps1          Local quality gate
AGENTS.md                  Codex implementation and wiki contract
```

An HTTP server is intentionally absent: the current application has no HTTP use case. If a later
user story requires an API or browser UI, that story should define the boundary before adding
FastAPI/Uvicorn.

## Quality gate

```powershell
.\scripts\check.ps1
```

This syncs the locked environment, checks formatting and linting, runs strict type checks, and runs
the test suite with coverage.

Start at [`docs/index.md`](docs/index.md) for the project workflow and knowledge base.
