"""A session-lifetime credential cache, held in a process that outlives sudo.

``sudo -A`` spawns its askpass helper **fresh for every prompt**.  An in-process
cache therefore remembers nothing: the operator would be asked for the same
password on every single call, which is precisely the thing this feature exists
to stop.  Remembering across those spawns needs a process that stays, so this
module is the same shape as ``ssh-agent`` and ``gpg-agent``, for the same
reason.

What it is not: a password manager. Nothing is written to disk, ever. Retained
buffers live in anonymous locked, non-dumpable mappings, are wiped on expiry,
and die with the session. A reboot, a logout, or ``sleipnir agent stop`` loses
them, and that is the intended behaviour rather than a limitation to fix later.

Three guards stand between a caller and the plaintext:

* the socket directory and the socket are ``0700``/``0600``;
* every connection's ``SO_PEERCRED`` uid must equal the agent's own; and
* the value is length-capped, so the socket cannot be repurposed as a data
  channel out of a sandbox.

    # ponytail: one global dict under one lock. Contention is measured in
    # passwords per hour; per-label locks would be pure ceremony.
"""

from __future__ import annotations

import base64
import binascii
import json
import mmap
import os
import subprocess
import socket
import stat
import struct
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

try:  # resource is absent on Windows; the credential agent is Unix-only today.
    import resource
except ImportError:  # pragma: no cover - Windows import surface
    resource = None  # type: ignore[assignment]

DEFAULT_IDLE_TIMEOUT_S = 900.0
MAX_SECRET_BYTES = 4_096
MAX_SECRET_ENTRIES = 64
MAX_LABEL_CHARS = 80
MAX_REQUEST_LINE_BYTES = 8_192
# LIST can contain all 64 bounded labels. Its base64-encoded JSON is larger
# than a SET request even though it contains metadata only.
MAX_RESPONSE_LINE_BYTES = 32_768
_SWEEP_INTERVAL_S = 5.0
WORKER_MARKER_ENV = "SLEIPNIR_WORKER"
_WORKER_MARKER = (WORKER_MARKER_ENV + "=").encode()


class AgentError(RuntimeError):
    """The agent refused a request, or could not be reached."""


def _protect_process_memory() -> None:
    """Keep retained credentials out of core dumps and ptrace snapshots.

    The socket permissions protect the protocol; this protects the process
    heap.  Linux's dumpable bit also prevents same-user ptrace and `/proc/pid`
    memory reads. Core dumps are disabled wherever ``resource`` is available;
    on Linux a failure to disable dumpability aborts agent startup.
    """
    if resource is not None:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if sys.platform.startswith("linux"):
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(4, 0, 0, 0, 0):  # PR_SET_DUMPABLE = 4
            errno = ctypes.get_errno()
            raise AgentError(f"could not disable credential-agent dumps (errno {errno})")


def default_socket_path() -> Path:
    """Prefer ``XDG_RUNTIME_DIR``: it is a tmpfs, per-user, and wiped on logout.

    A path under ``$HOME`` would put the socket on a disk that survives the
    session, which is the wrong lifetime for something holding credentials —
    even though only the socket, never a value, would ever be written there.
    """
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime else Path.home() / ".sleipnir"
    return base / "sleipnir" / "agent.sock" if runtime else base / "agent.sock"


def daemon_env() -> dict[str, str]:
    """Environment for the long-lived cache process, without unrelated secrets."""
    allowed = frozenset(
        {
            "HOME",
            "PATH",
            "PYTHONHOME",
            "PYTHONPATH",
            "LD_LIBRARY_PATH",
            "DYLD_LIBRARY_PATH",
            "XDG_RUNTIME_DIR",
            "TMPDIR",
            "LANG",
            "LANGUAGE",
            "TZ",
        }
    )
    return {
        name: value
        for name, value in os.environ.items()
        if name in allowed or name.startswith("LC_")
    }


class _ProtectedBuffer:
    """An anonymous, non-dumpable, locked allocation for one retained value."""

    def __init__(self, value: bytes | bytearray) -> None:
        if len(value) > MAX_SECRET_BYTES:
            raise AgentError("credential exceeds the agent's size limit")
        self._length = len(value)
        self._closed = False
        self._mapping = mmap.mmap(-1, max(1, self._length), access=mmap.ACCESS_WRITE)
        self._address = 0
        try:
            import ctypes

            self._address = ctypes.addressof(ctypes.c_char.from_buffer(self._mapping))
            libc = ctypes.CDLL(None, use_errno=True)
            if libc.mlock(ctypes.c_void_p(self._address), ctypes.c_size_t(max(1, self._length))):
                errno = ctypes.get_errno()
                raise AgentError(f"could not lock credential memory (errno {errno})")
            if hasattr(self._mapping, "madvise") and hasattr(mmap, "MADV_DONTDUMP"):
                self._mapping.madvise(mmap.MADV_DONTDUMP)
            self._mapping[: self._length] = value
        except Exception:
            self._mapping.close()
            self._length = 0
            raise
        finally:
            if isinstance(value, bytearray):
                _wipe_bytearray(value)

    def __len__(self) -> int:
        return self._length

    def __bytes__(self) -> bytes:
        return self._mapping[: self._length]

    def wipe(self) -> None:
        if self._closed:
            return
        allocation = max(1, self._length)
        self._mapping[:allocation] = b"\0" * allocation
        try:
            import ctypes

            ctypes.CDLL(None, use_errno=True).munlock(
                ctypes.c_void_p(self._address), ctypes.c_size_t(allocation)
            )
        finally:
            self._mapping.close()
            self._length = 0
            self._closed = True


def _wipe_bytearray(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0
    value.clear()


@dataclass
class _Entry:
    buffer: _ProtectedBuffer | bytes | bytearray = field(
        repr=False, default_factory=bytearray
    )
    last_used: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.buffer, _ProtectedBuffer):
            self.buffer = _ProtectedBuffer(self.buffer)

    def wipe(self) -> None:
        self.buffer.wipe()

    def __repr__(self) -> str:  # pragma: no cover - trivial but load-bearing
        return f"<_Entry len={len(self.buffer)}>"


def _peer_credentials(conn: socket.socket) -> tuple[int | None, int]:
    """The pid/uid on the other end, from the kernel rather than the caller."""
    if hasattr(socket, "SO_PEERCRED"):
        raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _pid, uid, _gid = struct.unpack("3i", raw)
        return _pid, uid
    getpeereid = getattr(conn, "getpeereid", None)
    if getpeereid is not None:  # macOS and BSD
        uid, _gid = getpeereid()
        return None, int(uid)
    raise OSError("peer credentials are unavailable on this platform")


def _ancestor_is_worker(pid: int | None) -> bool:
    """Detect a worker marker even when an immediate child removes it.

    The provider sandbox remains the kernel boundary. This ancestry check is a
    second lock: a task cannot recover the default socket path, run
    ``env -u SLEIPNIR_WORKER sleipnir askpass``, and thereby turn simple
    environment removal into credential access.
    """
    if pid is None or not sys.platform.startswith("linux"):
        return False
    seen: set[int] = set()
    current = pid
    for _ in range(64):
        if current <= 1 or current in seen:
            return False
        seen.add(current)
        proc = Path("/proc") / str(current)
        try:
            environ = (proc / "environ").read_bytes()
            if any(
                item.startswith(_WORKER_MARKER) and item != _WORKER_MARKER
                for item in environ.split(b"\0")
            ):
                return True
            stat_line = (proc / "stat").read_text(encoding="utf-8")
            # comm is parenthesised and may itself contain spaces or `)`.
            current = int(stat_line[stat_line.rfind(")") + 2 :].split()[1])
        except (OSError, ValueError, IndexError):
            # A short-lived ancestor may disappear during the walk. The
            # provider sandbox still guards the socket in that case.
            return False
    return False


def _valid_label(label: str) -> bool:
    """Labels share a line protocol and a bounded status response."""
    return bool(label) and len(label) <= MAX_LABEL_CHARS and all(
        char.isprintable() and not char.isspace() for char in label
    )


class Agent:
    """Holds credentials in memory for one desktop session."""

    def __init__(
        self,
        *,
        socket_path: Path | None = None,
        idle_timeout_s: float = DEFAULT_IDLE_TIMEOUT_S,
    ) -> None:
        self.socket_path = Path(socket_path) if socket_path else default_socket_path()
        self.idle_timeout_s = float(idle_timeout_s)
        self._store: dict[str, _Entry] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._server: socket.socket | None = None

    # -- lifecycle ---------------------------------------------------------

    def _bind(self) -> socket.socket:
        folder = self.socket_path.parent
        if folder.exists() and (folder.is_symlink() or not folder.is_dir()):
            raise AgentError(f"unsafe credential-agent socket directory: {folder}")
        folder.mkdir(parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
        # A stale socket from a crashed agent must not block a new one, but an
        # existing *live* agent must: connect first and refuse if it answers.
        if self.socket_path.exists():
            try:
                mode = self.socket_path.lstat().st_mode
            except OSError as error:
                raise AgentError(f"could not inspect old agent socket {self.socket_path}") from error
            if not stat.S_ISSOCK(mode):
                raise AgentError(f"credential-agent path exists and is not a socket: {self.socket_path}")
            if _reachable(self.socket_path):
                raise AgentError(f"a Sleipnir agent is already listening on {self.socket_path}")
            self.socket_path.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old_mask = os.umask(0o077)
        try:
            server.bind(str(self.socket_path))
        finally:
            os.umask(old_mask)
        os.chmod(self.socket_path, 0o600)
        server.listen(16)
        server.settimeout(_SWEEP_INTERVAL_S)
        return server

    def serve_forever(self) -> None:
        _protect_process_memory()
        self._server = self._bind()
        try:
            while not self._stop.is_set():
                try:
                    conn, _ = self._server.accept()
                except socket.timeout:
                    self.sweep()
                    continue
                except OSError:
                    break
                with conn:
                    self._serve_one(conn)
                self.sweep()
        finally:
            self.drop_all()
            if self._server is not None:
                self._server.close()
            self.socket_path.unlink(missing_ok=True)

    def shutdown(self) -> None:
        self._stop.set()
        # Nudge accept() out of its timeout rather than waiting the full interval.
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as poke:
                poke.settimeout(0.5)
                poke.connect(str(self.socket_path))
        except OSError:
            pass

    # -- store -------------------------------------------------------------

    def sweep(self) -> None:
        """Wipe anything idle past the timeout.

        Wiping matters more than dropping: releasing the last reference to a
        ``bytes`` leaves the plaintext in the heap until the allocator happens
        to reuse the page.  The buffer is zeroed first.
        """
        now = time.monotonic()
        with self._lock:
            expired = [
                label
                for label, entry in self._store.items()
                if now - entry.last_used > self.idle_timeout_s
            ]
            for label in expired:
                self._store.pop(label).wipe()

    def drop_all(self) -> None:
        with self._lock:
            while self._store:
                _label, entry = self._store.popitem()
                entry.wipe()

    # -- protocol ----------------------------------------------------------

    def _serve_one(self, conn: socket.socket) -> None:
        try:
            peer_pid, peer_uid = _peer_credentials(conn)
            if peer_uid != os.getuid():
                _send(conn, "ERR peer uid mismatch")
                return
            if _ancestor_is_worker(peer_pid):
                _send(conn, "ERR worker processes may not access credentials")
                return
        except OSError:
            _send(conn, "ERR peer identity unavailable")
            return
        line = _recv_line(conn, limit=MAX_REQUEST_LINE_BYTES)
        if line is None:
            return
        try:
            _send(conn, self._dispatch(line))
        except Exception as error:  # noqa: BLE001 - one bad client must not end the agent
            _send(conn, f"ERR {type(error).__name__}")

    def _dispatch(self, line: str) -> str:
        verb, _, rest = line.partition(" ")
        verb = verb.upper()
        now = time.monotonic()
        if verb == "PING":
            return "OK"
        if verb == "GET":
            if not _valid_label(rest):
                return "ERR label rejected"
            with self._lock:
                entry = self._store.get(rest)
                if entry is None or now - entry.last_used > self.idle_timeout_s:
                    if entry is not None:
                        self._store.pop(rest).wipe()
                    return "NONE"
                entry.last_used = now
                return "OK " + base64.b64encode(bytes(entry.buffer)).decode("ascii")
        if verb == "SET":
            label, _, encoded = rest.partition(" ")
            try:
                value = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                return "ERR malformed value"
            if not _valid_label(label) or len(value) > MAX_SECRET_BYTES:
                return "ERR value rejected"
            self.sweep()
            with self._lock:
                previous = self._store.get(label)
                if previous is not None:
                    previous.wipe()
                elif len(self._store) >= MAX_SECRET_ENTRIES:
                    return "ERR credential cache is full"
                self._store[label] = _Entry(buffer=value, last_used=now)
            return "OK"
        if verb == "DROP":
            if not _valid_label(rest):
                return "ERR label rejected"
            with self._lock:
                entry = self._store.pop(rest, None)
            if entry is not None:
                entry.wipe()
            return "OK"
        if verb == "DROPALL":
            self.drop_all()
            return "OK"
        if verb == "LIST":
            self.sweep()
            with self._lock:
                rows = [
                    {
                        "label": label,
                        "age_s": round(now - entry.last_used, 1),
                        "length": len(entry.buffer),
                    }
                    for label, entry in sorted(self._store.items())
                ]
            return "OK " + base64.b64encode(json.dumps(rows).encode("utf-8")).decode("ascii")
        if verb == "STOP":
            self._stop.set()
            return "OK"
        return "ERR unknown verb"


def _send(conn: socket.socket, message: str) -> None:
    try:
        conn.sendall(message.encode("utf-8")[:MAX_RESPONSE_LINE_BYTES] + b"\n")
    except OSError:
        pass


def _recv_line(conn: socket.socket, *, limit: int = MAX_RESPONSE_LINE_BYTES) -> str | None:
    conn.settimeout(5.0)
    chunks = bytearray()
    while b"\n" not in chunks:
        if len(chunks) > limit:
            return None
        try:
            block = conn.recv(4096)
        except (OSError, socket.timeout):
            return None
        if not block:
            return None
        chunks += block
    return chunks.split(b"\n", 1)[0].decode("utf-8", errors="replace")


def _reachable(path: Path) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.5)
            probe.connect(str(path))
            probe.sendall(b"PING\n")
            return bool(probe.recv(64))
    except OSError:
        return False


class AgentClient:
    """One request, one connection. Values are base64 on the wire, never logged."""

    def __init__(self, socket_path: Path | None = None) -> None:
        self.socket_path = Path(socket_path) if socket_path else default_socket_path()

    def _ask(self, line: str) -> str:
        if len(line.encode("utf-8")) > MAX_REQUEST_LINE_BYTES:
            raise AgentError("credential-agent request is too large")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                conn.settimeout(10.0)
                conn.connect(str(self.socket_path))
                conn.sendall(line.encode("utf-8") + b"\n")
                reply = _recv_line(conn)
        except OSError as error:
            raise AgentError(f"no Sleipnir agent at {self.socket_path}") from error
        if reply is None:
            raise AgentError("the Sleipnir agent closed the connection")
        if reply.startswith("ERR"):
            raise AgentError(reply[4:].strip() or "agent refused the request")
        return reply

    def alive(self) -> bool:
        try:
            return self._ask("PING") == "OK"
        except AgentError:
            return False

    def get(self, label: str) -> bytearray | None:
        if not _valid_label(label):
            raise AgentError("credential label is invalid")
        reply = self._ask(f"GET {label}")
        if reply == "NONE":
            return None
        return bytearray(base64.b64decode(reply[3:]))

    def set(self, label: str, value: bytes | bytearray) -> None:
        if not _valid_label(label):
            raise AgentError("credential label is invalid")
        if len(value) > MAX_SECRET_BYTES:
            raise AgentError("credential exceeds the agent's size limit")
        self._ask(f"SET {label} " + base64.b64encode(value).decode("ascii"))

    def drop(self, label: str) -> None:
        if not _valid_label(label):
            raise AgentError("credential label is invalid")
        self._ask(f"DROP {label}")

    def drop_all(self) -> None:
        self._ask("DROPALL")

    def stop(self) -> None:
        self._ask("STOP")

    def list(self) -> list[dict[str, object]]:
        reply = self._ask("LIST")
        return json.loads(base64.b64decode(reply[3:]).decode("utf-8"))


def ensure_running(
    *,
    socket_path: Path | None = None,
    idle_timeout_s: float = DEFAULT_IDLE_TIMEOUT_S,
) -> AgentClient:
    """Return the session agent, starting it detached when necessary.

    No credential is involved in this spawn: the socket path and timeout are
    configuration, and actual secret bytes only cross the private socket after
    the agent has disabled dumps and opened it with peer-identity checks.
    """
    if os.environ.get(WORKER_MARKER_ENV):
        raise AgentError("a dispatched worker may not start or use the credential agent")
    path = Path(socket_path) if socket_path else default_socket_path()
    client = AgentClient(path)
    if client.alive():
        return client
    if socket_path is not None:
        raise AgentError(f"no Sleipnir agent at the explicit socket {path}")
    subprocess.Popen(
        [
            sys.executable,
            "-m",
            "sleipnir.cli",
            "agent",
            "start",
            "--foreground",
            "--idle-timeout",
            str(float(idle_timeout_s)),
        ],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=daemon_env(),
    )
    for _ in range(100):
        if client.alive():
            return client
        time.sleep(0.05)
    raise AgentError("the protected Sleipnir credential agent did not start")


__all__ = [
    "DEFAULT_IDLE_TIMEOUT_S",
    "MAX_SECRET_ENTRIES",
    "MAX_SECRET_BYTES",
    "MAX_LABEL_CHARS",
    "Agent",
    "AgentClient",
    "AgentError",
    "WORKER_MARKER_ENV",
    "daemon_env",
    "default_socket_path",
    "ensure_running",
]
