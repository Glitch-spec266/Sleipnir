"""The askpass GUI, the session credential cache, and the agent that holds it.

Two rules are load-bearing here and every test below exists to pin one of them:

* the plaintext must never be reachable from a log, an audit record, a
  ``repr``, or a command line; and
* nothing in this suite may talk to the real desktop, the real agent socket,
  or the operator's real credentials.  The same rule the rest of the capability
  suite follows: every subprocess boundary is intercepted.
"""

from __future__ import annotations

import base64
import argparse
import asyncio
import json
import os
import socket
import stat
import sys
import threading
import time
from pathlib import Path

import pytest

from sleipnir import platform
from sleipnir.capabilities import agent, askpass


class _FakePinentry:
    """Stands in for the pinentry process at the pipe, not above it.

    The same rule the provider fakes follow: intercept at the spawn boundary so
    the Assuan write/read/parse code under test is the code that actually runs.
    A test that replaced `prompt_gui` wholesale would exercise none of it.
    """

    def __init__(self) -> None:
        self.reply = "D x\nOK\n"
        self.sent = ""
        self.argv: list[str] = []

    def __call__(self, argv, **kwargs):  # noqa: ANN001 - mirrors subprocess.run
        self.argv = list(argv)

        class _Result:
            returncode = 0

        sent = kwargs.get("input", b"")
        self.sent = sent.decode("utf-8") if isinstance(sent, bytes) else sent
        result = _Result()
        output = "OK Pleased to meet you\n" + self.reply
        result.stdout = output.encode("utf-8") if isinstance(sent, bytes) else output
        result.stderr = b"" if isinstance(sent, bytes) else ""
        return result


@pytest.fixture()
def fake_pinentry(monkeypatch: pytest.MonkeyPatch) -> _FakePinentry:
    fake = _FakePinentry()
    monkeypatch.setattr(askpass.subprocess, "run", fake)
    monkeypatch.setattr(askpass, "find_pinentry", lambda: "/usr/bin/pinentry-gtk")
    return fake


# --------------------------------------------------------------------------
# label normalisation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("[sudo] password for prahladv: ", "sudo"),
        ("[sudo] password for root:", "sudo"),
        ("Password:", "sudo"),
        ("prahladv's password:", "sudo"),
        ("Password for git@github.com:", "git@github.com"),
        ("Enter passphrase for key '/home/x/.ssh/id_ed25519':", "ssh:/home/x/.ssh/id_ed25519"),
        ("", "credential"),
    ],
)
def test_sudo_prompts_all_normalise_to_one_label(prompt: str, expected: str) -> None:
    """sudo varies its prompt by user, locale and config; the cache must not.

    Without this, `[sudo] password for prahladv:` and `Password:` are two
    different cache entries and the operator is asked twice for one password.
    """
    assert askpass.normalise_label(prompt) == expected


def test_label_normalisation_is_bounded_and_printable() -> None:
    """A prompt is attacker-influenced text; it becomes a dict key and a label."""
    label = askpass.normalise_label("Password for \x1b[31mevil\x00\n" + "x" * 500)
    assert len(label) <= askpass.MAX_LABEL_CHARS
    assert all(ch.isprintable() for ch in label)
    assert "\x1b" not in label and "\n" not in label


# --------------------------------------------------------------------------
# the agent
# --------------------------------------------------------------------------


@pytest.fixture()
def running_agent(tmp_path: Path):
    """A real agent on a real UNIX socket, in a temporary directory."""
    sock = tmp_path / "agent.sock"
    server = agent.Agent(socket_path=sock, idle_timeout_s=60.0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    for _ in range(200):
        if sock.exists():
            break
        time.sleep(0.01)
    yield server
    server.shutdown()
    thread.join(timeout=5)


@pytest.mark.skipif(platform.IS_WINDOWS, reason="a named pipe has no file mode; the Windows equivalent is the DACL assertion in test_credential_agent_transport.py")
def test_agent_socket_is_private(running_agent: agent.Agent) -> None:
    """A socket that hands out plaintext may not be reachable by other users."""
    mode = running_agent.socket_path.stat().st_mode
    assert not mode & stat.S_IRWXG
    assert not mode & stat.S_IRWXO
    assert not running_agent.socket_path.parent.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO)


def test_agent_stores_and_returns_a_secret(running_agent: agent.Agent) -> None:
    client = agent.AgentClient(running_agent.socket_path)
    assert client.get("sudo") is None
    client.set("sudo", b"hunter2")
    assert client.get("sudo") == b"hunter2"


def test_agent_get_refreshes_the_idle_deadline(tmp_path: Path) -> None:
    """The operator chose an *idle* timeout: use keeps it alive, silence kills it."""
    server = agent.Agent(socket_path=tmp_path / "a.sock", idle_timeout_s=0.30)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.socket_path.exists():
                break
            time.sleep(0.01)
        client = agent.AgentClient(server.socket_path)
        client.set("sudo", b"hunter2")
        for _ in range(4):
            time.sleep(0.12)
            assert client.get("sudo") == b"hunter2", "use should have refreshed the deadline"
        time.sleep(0.5)
        assert client.get("sudo") is None, "an idle secret must expire"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_expiry_wipes_the_buffer_it_does_not_merely_drop_it(tmp_path: Path) -> None:
    """Dropping a reference leaves the plaintext in the heap until GC feels like it."""
    server = agent.Agent(socket_path=tmp_path / "a.sock", idle_timeout_s=0.05)
    buffer = bytearray(b"hunter2")
    server._store["sudo"] = agent._Entry(buffer=buffer, last_used=time.monotonic())
    time.sleep(0.1)
    server.sweep()
    assert bytes(buffer) == b"\x00" * 7 or len(buffer) == 0
    assert "sudo" not in server._store


def test_retained_secret_uses_locked_nondumpable_memory() -> None:
    original = bytearray(b"not-a-real-password")
    entry = agent._Entry(buffer=original, last_used=time.monotonic())
    try:
        assert isinstance(entry.buffer, agent._ProtectedBuffer)
        assert bytes(entry.buffer) == b"not-a-real-password"
        assert original == bytearray(), "the unprotected source buffer must be wiped"
    finally:
        entry.wipe()
    assert len(entry.buffer) == 0


def test_agent_refuses_a_peer_owned_by_another_user(
    running_agent: agent.Agent, monkeypatch: pytest.MonkeyPatch
) -> None:
    """0600 on the socket is the first lock; the peer-credential check is the second."""
    monkeypatch.setattr(agent, "_peer_credentials", lambda _conn: (123, os.getuid() + 1))
    client = agent.AgentClient(running_agent.socket_path)
    with pytest.raises(agent.AgentError):
        client.set("sudo", b"hunter2")


def test_agent_refuses_a_worker_marked_in_the_peer_ancestry(
    running_agent: agent.Agent, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent, "_ancestor_is_worker", lambda _pid: True)
    client = agent.AgentClient(running_agent.socket_path)
    with pytest.raises(agent.AgentError, match="worker"):
        client.get("sudo")


def test_linux_worker_ancestry_survives_marker_removal_from_the_leaf(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proc = tmp_path / "proc"
    (proc / "300").mkdir(parents=True)
    (proc / "200").mkdir()
    (proc / "300" / "environ").write_bytes(b"PATH=/bin\0")
    (proc / "300" / "stat").write_text("300 (helper) S 200 0 0 0\n", encoding="utf-8")
    (proc / "200" / "environ").write_bytes(b"SLEIPNIR_WORKER=1\0PATH=/bin\0")
    (proc / "200" / "stat").write_text("200 (provider) S 1 0 0 0\n", encoding="utf-8")

    real_path = agent.Path

    def fake_path(*parts):
        if parts and parts[0] == "/proc":
            return proc.joinpath(*map(str, parts[1:]))
        return real_path(*parts)

    monkeypatch.setattr(agent.sys, "platform", "linux")
    monkeypatch.setattr(agent, "Path", fake_path)
    assert agent._ancestor_is_worker(300) is True


def test_agent_daemon_environment_drops_unrelated_credentials(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "not-a-real-key")
    monkeypatch.setenv("UNUSUAL_SESSION_COOKIE", "not-a-real-cookie")
    monkeypatch.setenv("SUDO_ASKPASS", "/private/helper")
    monkeypatch.setenv("SLEIPNIR_AGENT_SOCK", "/private/socket")
    monkeypatch.setenv(agent.WORKER_MARKER_ENV, "1")
    monkeypatch.setenv("PATH", "/bin")
    safe = agent.daemon_env()
    assert safe["PATH"] == "/bin"
    assert "OPENROUTER_API_KEY" not in safe
    assert "UNUSUAL_SESSION_COOKIE" not in safe
    assert "SUDO_ASKPASS" not in safe
    assert "SLEIPNIR_AGENT_SOCK" not in safe
    assert agent.WORKER_MARKER_ENV not in safe


def test_worker_cannot_start_a_fresh_agent(monkeypatch) -> None:
    monkeypatch.setenv(agent.WORKER_MARKER_ENV, "1")
    with pytest.raises(agent.AgentError, match="worker"):
        agent.ensure_running()


def test_list_reports_labels_and_ages_but_never_values(running_agent: agent.Agent) -> None:
    client = agent.AgentClient(running_agent.socket_path)
    client.set("sudo", b"hunter2")
    client.set("gmail", b"correct horse")
    listing = client.list()
    assert {row["label"] for row in listing} == {"sudo", "gmail"}
    blob = json.dumps(listing)
    assert "hunter2" not in blob and "correct horse" not in blob
    for row in listing:
        assert set(row) == {"label", "age_s", "length"}


def test_list_never_reports_an_expired_entry(tmp_path: Path) -> None:
    server = agent.Agent(socket_path=tmp_path / "expired.sock", idle_timeout_s=0.05)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.socket_path.exists():
                break
            time.sleep(0.01)
        client = agent.AgentClient(server.socket_path)
        client.set("sudo", b"synthetic")
        time.sleep(0.1)
        assert client.list() == []
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_drop_and_drop_all_wipe(running_agent: agent.Agent) -> None:
    client = agent.AgentClient(running_agent.socket_path)
    client.set("sudo", b"hunter2")
    client.set("gmail", b"x")
    client.drop("sudo")
    assert client.get("sudo") is None
    assert client.get("gmail") == b"x"
    client.drop_all()
    assert client.list() == []


def test_an_oversized_value_is_refused(running_agent: agent.Agent) -> None:
    """The agent is a credential cache, not a data channel out of a sandbox."""
    client = agent.AgentClient(running_agent.socket_path)
    with pytest.raises(agent.AgentError):
        client.set("sudo", b"A" * (agent.MAX_SECRET_BYTES + 1))


def test_agent_rejects_labels_that_can_break_its_line_protocol(
    running_agent: agent.Agent,
) -> None:
    client = agent.AgentClient(running_agent.socket_path)
    for label in ("has space", "line\nbreak", "x" * (agent.MAX_LABEL_CHARS + 1)):
        with pytest.raises(agent.AgentError, match="label"):
            client.set(label, b"synthetic")


def test_full_agent_status_response_is_not_truncated(running_agent: agent.Agent) -> None:
    client = agent.AgentClient(running_agent.socket_path)
    for index in range(agent.MAX_SECRET_ENTRIES):
        label = f"entry-{index:02d}-" + "x" * (agent.MAX_LABEL_CHARS - 9)
        client.set(label, b"x")
    assert len(client.list()) == agent.MAX_SECRET_ENTRIES


def test_a_garbage_line_does_not_kill_the_agent(running_agent: agent.Agent) -> None:
    # Through the platform seam rather than a bare AF_UNIX socket: the point
    # of the test is that malformed input does not kill the agent, and that
    # holds on a named pipe too.
    with platform.agent_connect(running_agent.socket_path, 5.0) as raw:
        raw.sendall(b"NONSENSE \xff\xfe not-base64\n")
        raw.recv(4096)
    client = agent.AgentClient(running_agent.socket_path)
    client.set("sudo", b"hunter2")
    assert client.get("sudo") == b"hunter2"


# --------------------------------------------------------------------------
# the GUI prompt
# --------------------------------------------------------------------------


def test_pinentry_backend_is_probed_not_assumed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two of the three pinentries on the dev machine are broken installs.

    Picking by desktop environment would have chosen `pinentry-qt` on KDE and
    failed at the moment a password was needed.  The same shape of bug as
    selecting `grim` on KWin.
    """
    monkeypatch.setattr(askpass.shutil, "which", lambda name: f"/usr/bin/{name}")
    tried: list[str] = []

    def fake_handshake(path: str) -> bool:
        tried.append(path)
        return path.endswith("pinentry-gtk")

    monkeypatch.setattr(askpass, "_handshake_ok", fake_handshake)
    askpass.find_pinentry.cache_clear()
    assert askpass.find_pinentry().endswith("pinentry-gtk")
    assert len(tried) > 1, "a working backend must be found by probing, not by name"


def test_no_pinentry_is_a_clean_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(askpass.shutil, "which", lambda name: None)
    askpass.find_pinentry.cache_clear()
    with pytest.raises(askpass.AskpassError):
        askpass.find_pinentry()


def test_assuan_percent_decoding() -> None:
    """pinentry percent-escapes the value; a naive read corrupts real passwords."""
    assert askpass._unescape("a%25b%0Ac%0D") == b"a%b\nc\r"
    assert askpass._unescape("plain") == b"plain"
    assert askpass._unescape("trailing%A") == b"trailing%A"
    assert askpass._unescape("caf%C3%A9") == "café".encode()


def test_prompt_reads_the_value_from_the_assuan_data_line(
    monkeypatch: pytest.MonkeyPatch, fake_pinentry
) -> None:
    fake_pinentry.reply = "D hunter%252\nOK\n"
    value = askpass.prompt_gui("sudo", description="test")
    assert bytes(value) == b"hunter%2"


def test_prompt_never_puts_the_value_on_a_command_line(
    monkeypatch: pytest.MonkeyPatch, fake_pinentry
) -> None:
    """argv is world-readable in /proc. The value must arrive over a pipe."""
    fake_pinentry.reply = "D hunter2\nOK\n"
    askpass.prompt_gui("sudo", description="test")
    assert not any("hunter2" in part for part in fake_pinentry.argv)


def test_operator_cancel_raises_rather_than_returning_empty(fake_pinentry) -> None:
    """An empty password is a valid password; cancel is not the same event."""
    fake_pinentry.reply = "ERR 83886179 Operation cancelled <Pinentry>\n"
    with pytest.raises(askpass.AskpassCancelled):
        askpass.prompt_gui("sudo", description="test")


def test_the_description_is_clipped_and_stripped(fake_pinentry) -> None:
    """The description reaches a GUI and an Assuan line; both are injectable."""
    fake_pinentry.reply = "D x\nOK\n"
    askpass.prompt_gui(
        "sudo", description="evil\nSETPROMPT owned%0Ainjected\x1b[31m" + "y" * 900
    )
    sent = fake_pinentry.sent
    assert sent.count("SETDESC") == 1
    assert "\x1b" not in sent
    assert "%250Ainjected" in sent
    for line in sent.splitlines():
        assert len(line.encode("utf-8")) <= askpass.MAX_ASSUAN_LINE


def test_assuan_metadata_limit_counts_encoded_bytes() -> None:
    safe = askpass._assuan_safe("🔐" * 500, limit=120)
    assert len(safe.encode("utf-8")) <= 120


# --------------------------------------------------------------------------
# resolve(): the whole path, cache miss then cache hit
# --------------------------------------------------------------------------


def test_resolve_prompts_once_then_serves_from_the_agent(
    running_agent: agent.Agent, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This is the feature: type the sudo password once, never again this session."""
    prompts: list[str] = []

    def fake_prompt(label: str, *, description: str = "", **_: object) -> bytearray:
        prompts.append(label)
        return bytearray(b"hunter2")

    monkeypatch.setattr(askpass, "prompt_gui", fake_prompt)
    client = agent.AgentClient(running_agent.socket_path)

    first = askpass.resolve("[sudo] password for prahladv: ", client=client)
    second = askpass.resolve("Password:", client=client)

    assert first == b"hunter2" and second == b"hunter2"
    assert prompts == ["sudo"], "the second sudo prompt must be served from cache"


def test_audit_records_the_label_and_length_but_never_the_value(
    running_agent: agent.Agent, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """There is already a canary like this for the usage parser. Same reason."""
    from sleipnir.capabilities import audit

    log = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "DEFAULT_LOG", log)
    monkeypatch.setattr(
        askpass, "prompt_gui", lambda label, **_: bytearray(b"hunter2-secret")
    )
    askpass.resolve("[sudo] password for prahladv:", client=agent.AgentClient(running_agent.socket_path))
    text = log.read_text(encoding="utf-8")
    assert "sudo" in text
    assert "hunter2-secret" not in text
    assert '"length": 14' in text or '"length":14' in text


def test_resolve_is_refused_inside_a_worker_task(
    running_agent: agent.Agent, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Capabilities are an operator lane, never a worker lane.

    A dispatched task runs with a credential-stripped environment and a marker
    that says so.  If it could reach the cache, arbitrary model output would
    hold the operator's root password -- which deletes the sandbox the executor
    builds on purpose.
    """
    monkeypatch.setenv(askpass.WORKER_MARKER_ENV, "1")
    with pytest.raises(askpass.AskpassRefused):
        askpass.resolve("[sudo] password for prahladv:", client=agent.AgentClient(running_agent.socket_path))


@pytest.mark.skipif(platform.IS_WINDOWS, reason="Windows has no executable bit; an interpreter decides what runs")
def test_askpass_helper_script_is_executable_and_private(tmp_path: Path) -> None:
    """SUDO_ASKPASS takes a program path and passes no arguments of its own."""
    path = askpass.write_helper(directory=tmp_path, executable="/opt/x/bin/sleipnir")
    mode = path.stat().st_mode
    assert mode & stat.S_IXUSR
    assert not mode & (stat.S_IWGRP | stat.S_IWOTH)
    body = path.read_text(encoding="utf-8")
    assert "/opt/x/bin/sleipnir" in body and "askpass" in body


def test_sudo_env_points_at_the_helper_and_keeps_the_rest(tmp_path: Path) -> None:
    env = askpass.sudo_env({"PATH": "/bin"}, directory=tmp_path, executable="/x/sleipnir")
    assert env["PATH"] == "/bin"
    assert Path(env["SUDO_ASKPASS"]).exists()


def test_worker_environments_never_carry_the_askpass_hook() -> None:
    """`SUDO_ASKPASS` matches none of the adapter's secret markers on its own.

    It contains no `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `AUTH` or `CREDENTIAL`,
    so before this test it passed straight through to every delegated CLI --
    handing arbitrary model output a working route to the operator's root
    password.  The agent socket address is the same shape of leak.
    """
    from sleipnir.adapters.base import BaseAdapter

    stripped = BaseAdapter._subprocess_env(
        {
            "PATH": "/bin",
            "SUDO_ASKPASS": "/home/x/.sleipnir/askpass.sh",
            askpass.AGENT_SOCKET_ENV: "/run/user/1000/sleipnir/agent.sock",
        }
    )
    assert stripped["PATH"] == "/bin"
    assert "SUDO_ASKPASS" not in stripped
    assert askpass.AGENT_SOCKET_ENV not in stripped


def test_worker_environments_are_marked_as_such() -> None:
    """Stripping is necessary but not sufficient: refusal must be positive.

    A worker that reconstructs the socket path from its default location would
    otherwise still reach the cache.  The marker is what `resolve` refuses on.
    """
    from sleipnir.adapters.base import BaseAdapter

    assert BaseAdapter._subprocess_env({"PATH": "/bin"})[askpass.WORKER_MARKER_ENV] == "1"


def test_resolve_auto_starts_the_session_agent_on_first_use(monkeypatch) -> None:
    values: dict[str, bytes] = {}

    class Client:
        def get(self, label):
            return bytearray(values[label]) if label in values else None

        def set(self, label, value):
            values[label] = bytes(value)

    client = Client()
    starts: list[bool] = []
    monkeypatch.setattr(
        askpass.agent,
        "ensure_running",
        lambda: starts.append(True) or client,
    )
    monkeypatch.setattr(
        askpass, "prompt_gui", lambda *args, **kwargs: bytearray(b"memory-only")
    )
    first = askpass.resolve("Gmail password")
    second = askpass.resolve("Gmail password")
    try:
        assert first == second == bytearray(b"memory-only")
        assert starts == [True, True]
    finally:
        askpass.wipe(first)
        askpass.wipe(second)


def test_prompted_value_is_wiped_when_cache_insertion_fails(monkeypatch) -> None:
    entered = bytearray(b"not-a-real-password")

    class Client:
        def get(self, label):
            return None

        def set(self, label, value):
            raise agent.AgentError("cache unavailable")

    monkeypatch.setattr(askpass, "prompt_gui", lambda *args, **kwargs: entered)
    with pytest.raises(agent.AgentError, match="cache unavailable"):
        askpass.resolve("password", client=Client())
    assert entered == bytearray()


def test_cached_value_is_wiped_when_its_audit_fails(monkeypatch) -> None:
    cached = bytearray(b"not-a-real-password")

    class Client:
        def get(self, label):
            return cached

    monkeypatch.setattr(
        askpass.audit,
        "record",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("audit unavailable")),
    )
    with pytest.raises(OSError, match="audit unavailable"):
        askpass.resolve("password", client=Client())
    assert cached == bytearray()


def test_new_cache_entry_is_removed_when_prompt_audit_fails(monkeypatch) -> None:
    entered = bytearray(b"not-a-real-password")
    dropped: list[str] = []

    class Client:
        def get(self, label):
            return None

        def set(self, label, value):
            return None

        def drop(self, label):
            dropped.append(label)

    monkeypatch.setattr(askpass, "prompt_gui", lambda *args, **kwargs: entered)
    monkeypatch.setattr(
        askpass.audit,
        "record",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("audit unavailable")),
    )
    with pytest.raises(OSError, match="audit unavailable"):
        askpass.resolve("Gmail password", client=Client())
    assert entered == bytearray()
    assert dropped == ["Gmailpassword"]


def test_resolve_honours_the_private_socket_passed_to_a_helper(monkeypatch, tmp_path) -> None:
    configured = tmp_path / "private-agent.sock"
    seen: list[Path | None] = []

    class Client:
        def get(self, label):
            return bytearray(b"already-cached")

    monkeypatch.setenv(askpass.AGENT_SOCKET_ENV, str(configured))
    monkeypatch.setattr(
        askpass.agent,
        "ensure_running",
        lambda *, socket_path=None: seen.append(socket_path) or Client(),
    )
    value = askpass.resolve("Gmail password")
    try:
        assert value == bytearray(b"already-cached")
        assert seen == [configured]
    finally:
        askpass.wipe(value)


def test_secret_browser_fill_reuses_the_matching_cached_label(monkeypatch) -> None:
    from sleipnir import cli
    from sleipnir.capabilities import browser

    delivered: list[bytes] = []

    class FakeBrowser:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def fill_secret(self, selector, secret):
            delivered.append(secret.consume().encode())

        async def press(self, selector, key):
            return None

    calls: list[str] = []
    monkeypatch.setattr(browser, "Browser", FakeBrowser)
    monkeypatch.setattr(
        askpass,
        "resolve",
        lambda label, **kwargs: calls.append(label) or bytearray(b"gmail-value"),
    )
    args = argparse.Namespace(
        label="gmail", browser_selector="input[type=password]", submit=False
    )
    assert asyncio.run(cli.cmd_secret(args)) == 0
    assert calls == ["gmail"]
    assert delivered == [b"gmail-value"]


def test_askpass_cli_writes_raw_bytes_then_wipes_them(monkeypatch) -> None:
    from sleipnir import cli

    value = bytearray(b"sudo-value")
    writes: list[bytes] = []
    monkeypatch.setattr(askpass, "resolve", lambda prompt: value)
    monkeypatch.setattr(cli.os, "write", lambda fd, data: writes.append(bytes(data)) or len(data))
    args = argparse.Namespace(label=None, prompt="Password:")
    assert asyncio.run(cli.cmd_askpass(args)) == 0
    assert writes == [b"sudo-value"]
    assert value == bytearray()


def test_sudo_cli_starts_agent_before_spawning_sudo(monkeypatch, tmp_path) -> None:
    from sleipnir import cli
    from sleipnir.capabilities import audit

    events: list[object] = []
    audit_log = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "DEFAULT_LOG", audit_log)

    class Result:
        returncode = 0

    monkeypatch.setattr(agent, "ensure_running", lambda: events.append("agent"))
    monkeypatch.setattr(
        askpass,
        "sudo_env",
        lambda: events.append("env") or {"SUDO_ASKPASS": "/private/helper"},
    )
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda argv, **kwargs: events.append((argv, kwargs["env"])) or Result(),
    )
    args = argparse.Namespace(args=["--", "toolname", "--", "sensitive-operand"])
    assert asyncio.run(cli.cmd_sudo(args)) == 0
    assert events == [
        "agent",
        "env",
        (["sudo", "-A", "toolname", "--", "sensitive-operand"], {"SUDO_ASKPASS": "/private/helper"}),
    ]
    recorded = audit_log.read_text(encoding="utf-8")
    assert "sudo.command" in recorded
    assert '"arg_count": 3' in recorded
    assert '"returncode": 0' in recorded
    assert "toolname" not in recorded and "sensitive-operand" not in recorded


def test_sudo_refuses_to_spawn_when_the_audit_cannot_be_written(monkeypatch) -> None:
    from sleipnir import cli
    from sleipnir.capabilities import audit

    spawned: list[list[str]] = []
    monkeypatch.setattr(agent, "ensure_running", lambda: object())
    monkeypatch.setattr(askpass, "sudo_env", lambda: {})
    monkeypatch.setattr(
        audit,
        "record",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("audit unavailable")),
    )
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda argv, **kwargs: spawned.append(argv),
    )
    with pytest.raises(cli.CliError, match="audit unavailable"):
        asyncio.run(cli.cmd_sudo(argparse.Namespace(args=["--", "id"])))
    assert spawned == []


@pytest.mark.skipif(platform.IS_WINDOWS, reason="resource.setrlimit is POSIX-only; Windows crash dumps are configured outside the process")
def test_agent_process_disables_core_dumps(monkeypatch) -> None:
    calls: list[tuple[int, tuple[int, int]]] = []
    monkeypatch.setattr(agent.resource, "setrlimit", lambda kind, value: calls.append((kind, value)))
    agent._protect_process_memory()
    assert calls
    assert calls[0][1] == (0, 0)


@pytest.mark.skipif(platform.IS_WINDOWS, reason="creating a file symlink needs SeCreateSymbolicLinkPrivilege, which a normal account lacks")
def test_helper_replaces_a_symlink_instead_of_following_it(tmp_path: Path) -> None:
    victim = tmp_path / "victim"
    victim.write_text("keep", encoding="utf-8")
    helper = tmp_path / "askpass.sh"
    helper.symlink_to(victim)
    written = askpass.write_helper(directory=tmp_path, executable="/x/sleipnir")
    assert written == helper
    assert not helper.is_symlink()
    assert victim.read_text(encoding="utf-8") == "keep"


def test_helper_quotes_an_executable_path_with_spaces(tmp_path: Path) -> None:
    helper = askpass.write_helper(
        directory=tmp_path, executable="/opt/Sleipnir App/bin/sleipnir"
    )
    body = helper.read_text(encoding="utf-8")
    assert "'/opt/Sleipnir App/bin/sleipnir' askpass" in body


def test_default_helper_is_bound_to_this_python_install_not_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(askpass.shutil, "which", lambda name: "/tmp/stale/sleipnir")
    helper = askpass.write_helper(directory=tmp_path)
    body = helper.read_text(encoding="utf-8")
    assert sys.executable in body
    assert "-m sleipnir.cli askpass" in body
    assert "/tmp/stale/sleipnir" not in body


@pytest.mark.skipif(platform.IS_WINDOWS, reason="a named pipe has no containing directory to symlink")
def test_agent_refuses_a_symlinked_socket_directory(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    server = agent.Agent(socket_path=linked / "agent.sock")
    with pytest.raises(agent.AgentError, match="unsafe"):
        server._bind()


@pytest.mark.skipif(platform.IS_WINDOWS, reason="a named pipe has no filesystem entry that another file could masquerade as")
def test_agent_never_unlinks_a_regular_file_masquerading_as_its_socket(tmp_path: Path) -> None:
    path = tmp_path / "agent.sock"
    path.write_text("do not delete", encoding="utf-8")
    server = agent.Agent(socket_path=path)
    with pytest.raises(agent.AgentError, match="not a socket"):
        server._bind()
    assert path.read_text(encoding="utf-8") == "do not delete"
