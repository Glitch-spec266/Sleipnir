"""Frozen entry point for the desktop core sidecar."""

from __future__ import annotations

import sys

from sleipnir.cli import main as cli_main
from sleipnir.gui import main as gui_main
from sleipnir.gui_agent import main as agent_main
from sleipnir.gui_history import main as history_main
from sleipnir.gui_project import main as project_main
from sleipnir.voice.transcription import main as transcription_main
from sleipnir.voice.synthesis import main as synthesis_main


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "gui":
        raise SystemExit(gui_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "agent":
        raise SystemExit(agent_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "history":
        raise SystemExit(history_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "project":
        raise SystemExit(project_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "transcribe":
        raise SystemExit(transcription_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "speak":
        raise SystemExit(synthesis_main(sys.argv[2:]))
    raise SystemExit(cli_main())
