"""Frozen entry point for the desktop core sidecar."""

from __future__ import annotations

import sys

from sleipnir.cli import main as cli_main
from sleipnir.gui import main as gui_main


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "gui":
        raise SystemExit(gui_main(sys.argv[2:]))
    raise SystemExit(cli_main())
