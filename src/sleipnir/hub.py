"""A small LAN service so a phone can be a control surface for a run.

The hub is deliberately not a second orchestrator.  It reads what the desktop
already computes, performs the three operator actions that are worth walking
away from a desk for -- approve, deny, look -- and hands the one action it
cannot perform itself back to the desktop host as an event.

Three rules it keeps:

* **Every request carries a bearer token, including the first one.**  One of
  these endpoints returns a photograph of the operator's screen.  An
  unauthenticated service on a home network that does that is a screen-sharing
  server for everyone on the network, whatever it is called.
* **The response is counts and ids, never artifact content.**  Same rule as
  the dashboard snapshot and the manifest: a field that grows with task count
  is the bug, regardless of which surface reads it.
* **It never decides anything.**  Approving applies the existing revision path
  with its operator-review gate; denying renames a file.  The hub adds no new
  authority, only a new place to exercise the authority that exists.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import socket
import sys
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from sleipnir import platform

#: Where the shared token lives. Mode 0600, created once, never logged.
TOKEN_PATH = Path.home() / ".sleipnir" / "hub-token"

#: The phone's dashboard shows a summary and the newest work, not the plan.
#: Without this the response would grow with the plan and a thousand-task run
#: would send a megabyte to a phone on every poll.
MAX_TASKS = 20
MAX_REVIEWS = 20

#: Refused rather than truncated: a body larger than this is not a decision.
MAX_BODY_BYTES = 8 * 1024

DEFAULT_PORT = 8765


def load_token(path: Path = TOKEN_PATH) -> str:
    """Read the pairing token, creating one on first use.

    Written with ``0o600`` before any bytes reach it -- creating the file and
    then chmod'ing leaves a window where every account on the machine can read
    the credential.
    """
    path = path.expanduser()
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(24)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(token)
    # The mode above is the whole story on POSIX. Windows ignores it: the file
    # inherits its parent's ACL, which can hand this token to every local
    # account, so the restrictive ACL is applied explicitly there.
    platform.make_path_private(path)
    return token


def lan_address() -> str:
    """This machine's address on the local network, for the pairing screen.

    Asked of the routing table by opening a UDP socket to an address that is
    never contacted, because ``gethostbyname(gethostname())`` answers
    ``127.0.1.1`` on a Debian-style host and would print a URL the phone can
    never reach.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # TEST-NET-1: routable, never answered
        return str(probe.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def _emit(event: dict[str, Any]) -> None:
    """Hand the desktop host something only it can do.

    The hub cannot toggle the wake listener: the listener is a child of the
    Tauri host, and a second process writing a preferences file would be
    telling a running process something it is not listening for. The same
    stdout-event contract the voice listener already uses carries it back.
    """
    sys.stdout.write(json.dumps(event, separators=(",", ":")) + "\n")
    sys.stdout.flush()


@dataclass(frozen=True, slots=True)
class HubConfig:
    run_root: Path
    token: str
    preferences: Path | None = None


def _preferences(config: HubConfig) -> dict[str, Any]:
    if config.preferences is None or not config.preferences.is_file():
        return {}
    try:
        return json.loads(config.preferences.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def status_payload(config: HubConfig) -> dict[str, Any]:
    """What the phone's dashboard shows: totals, the newest work, and state."""
    from sleipnir.gui import load_dashboard

    dashboard = load_dashboard(config.run_root)
    tasks = dashboard.get("tasks") or []
    counts: dict[str, int] = {}
    for task in tasks:
        status = str(task.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    voice = dashboard.get("voice") or {}
    preferences = _preferences(config)
    settings = preferences.get("voice") if isinstance(preferences, dict) else {}
    listening = bool((settings or {}).get("listeningEnabled", False))
    return {
        "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "runtime": dashboard.get("runtime", {}),
        "run": dashboard.get("run"),
        "counts": counts,
        "taskTotal": len(tasks),
        # Bounded on purpose. The phone shows what is happening now; the plan
        # lives on the desktop.
        "tasks": [
            {
                "id": task.get("id"),
                "title": task.get("title"),
                "status": task.get("status"),
                "group": task.get("group"),
            }
            for task in tasks[:MAX_TASKS]
        ],
        "reviewCount": len(dashboard.get("reviews") or []),
        "voice": {"phase": voice.get("phase", "off"), "listening": listening},
    }


def review_payload(config: HubConfig) -> list[dict[str, Any]]:
    from sleipnir.gui import load_dashboard

    reviews = load_dashboard(config.run_root).get("reviews") or []
    return [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "kind": item.get("kind"),
            "summary": item.get("summary"),
        }
        for item in reviews[:MAX_REVIEWS]
    ]


def _safe_id(value: str) -> bool:
    return bool(value) and all(
        character.isalnum() or character in "._-" for character in value
    )


def decide(config: HubConfig, item_id: str, decision: str) -> tuple[int, dict[str, Any]]:
    """Apply an operator decision to one review proposal.

    ``approve`` runs the existing revision path rather than editing the plan
    here: the operator-review gate and the blast-radius rules live there, and a
    second implementation of them on a phone endpoint is a second set of rules
    to get wrong.
    """
    import subprocess  # nosec B404 - fixed argv, no shell

    if not _safe_id(item_id):
        return 400, {"error": "invalid review id"}
    proposal = config.run_root / "proposals" / f"{item_id}.json"
    if not proposal.is_file():
        return 404, {"error": "review proposal no longer exists"}
    if decision == "approve":
        result = subprocess.run(  # nosec B603
            [
                sys.executable,
                "-m",
                "sleipnir.cli",
                "--run-root",
                str(config.run_root),
                "apply-revision",
                str(proposal),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if result.returncode != 0:
            return 500, {"error": result.stderr.strip()[-240:] or "apply failed"}
        return 200, {"status": "approved"}
    # The suffix is appended to the whole name, not substituted for ".json":
    # the desktop marks these as ``<id>.json.rejected`` and the TUI counts
    # pending work by looking for names that still end in ``.json``.
    suffix = {"reject": "rejected", "request_changes": "changes-requested"}
    if decision not in suffix:
        return 400, {"error": "unknown review decision"}
    proposal.rename(proposal.with_name(f"{proposal.name}.{suffix[decision]}"))
    return 200, {"status": decision}


def screen_frame() -> bytes:
    """One audited desktop frame, at the size the voice lane already uses."""
    import asyncio

    from sleipnir.capabilities import audit
    from sleipnir.voice.local_agent import ScreenObserver

    audit.record("hub.screen", {"phase": "requested"})
    return asyncio.run(ScreenObserver().capture())


class _Handler(BaseHTTPRequestHandler):
    config: HubConfig

    server_version = "Sleipnir"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # The default handler writes the request line to stderr, which would
        # put review ids into the desktop host's log for every poll.
        return

    def _authorised(self) -> bool:
        header = self.headers.get("Authorization", "")
        prefix, _, presented = header.partition(" ")
        if prefix.lower() != "bearer":
            return False
        # Constant time: a plain == leaks the token one character at a time to
        # anyone on the network who can measure a few thousand requests.
        return hmac.compare_digest(presented.strip(), self.config.token)

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: Any) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def _guard(self) -> bool:
        if self._authorised():
            return True
        self._json(401, {"error": "pair this device in Sleipnir first"})
        return False

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's contract
        if not self._guard():
            return
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        try:
            if path == "/api/status":
                self._json(200, status_payload(self.config))
            elif path == "/api/reviews":
                self._json(200, review_payload(self.config))
            elif path == "/api/screen":
                self._send(200, screen_frame(), "image/jpeg")
            else:
                self._json(404, {"error": "unknown endpoint"})
        except Exception as error:  # noqa: BLE001 - a phone gets a message, not a stack
            self._json(500, {"error": str(error)[:240]})

    def do_POST(self) -> None:  # noqa: N802
        if not self._guard():
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            self._json(413, {"error": "request body is too large"})
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._json(400, {"error": "request body is not JSON"})
            return
        if not isinstance(body, dict):
            self._json(400, {"error": "request body must be an object"})
            return
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        try:
            if path == "/api/voice":
                enabled = bool(body.get("enabled"))
                _emit({"type": "voice", "enabled": enabled})
                self._json(200, {"status": "requested", "enabled": enabled})
            elif path.startswith("/api/reviews/"):
                code, payload = decide(
                    self.config,
                    path.rsplit("/", 1)[-1],
                    str(body.get("decision", "")),
                )
                self._json(code, payload)
            else:
                self._json(404, {"error": "unknown endpoint"})
        except Exception as error:  # noqa: BLE001
            self._json(500, {"error": str(error)[:240]})


def serve(
    config: HubConfig, *, host: str = "0.0.0.0", port: int = DEFAULT_PORT  # noqa: S104
) -> ThreadingHTTPServer:
    """Start the hub. Binding to every interface is the point of the hub."""
    handler = type("_BoundHandler", (_Handler,), {"config": config})
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sleipnir-hub")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--preferences", type=Path)
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--print-pairing",
        action="store_true",
        help="print the pairing URL and token for a phone to scan or type",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = HubConfig(
        run_root=args.run_root.resolve(),
        token=load_token(),
        preferences=args.preferences,
    )
    server = serve(config, host=args.host, port=args.port)
    address = f"http://{lan_address()}:{args.port}"
    if args.print_pairing:
        # The token is printed only on explicit request and only to the
        # operator's own terminal. It is never emitted as an event, because
        # events are logged.
        print(f"{address}\n{config.token}")
    _emit({"type": "ready", "address": address})
    try:
        # Closing stdin means the desktop host is gone; there is no
        # ``process_guard`` on this branch, so EOF is the orphan signal.
        sys.stdin.read()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0


__all__ = [
    "DEFAULT_PORT", "HubConfig", "MAX_REVIEWS", "MAX_TASKS", "TOKEN_PATH",
    "build_parser", "decide", "lan_address", "load_token", "main",
    "review_payload", "screen_frame", "serve", "status_payload",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
