"""Run the command-line adapter or native desktop dashboard."""

import sys

from flyff_bot.cli import main
from flyff_bot.ui.app import run_desktop

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "ui":
        raise SystemExit(run_desktop([sys.argv[0], *sys.argv[2:]]))
    raise SystemExit(main())
