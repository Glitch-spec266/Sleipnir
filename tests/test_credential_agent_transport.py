"""The credential agent's transport must keep its guarantees on both platforms.

``capabilities/agent.py`` names three guards, and two of them are properties of
the transport rather than of the protocol: only this account can open the
endpoint, and the peer's identity is read from the kernel rather than taken
from the client.  CPython has no ``AF_UNIX`` on Windows, so the transport there
is a named pipe -- a substitution that is only safe while it still answers to
both of those.  These tests assert the guarantees, not the mechanism.
"""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

import pytest

from sleipnir import platform
from sleipnir.capabilities.agent import Agent, AgentClient, AgentError, _reachable

SECRET = b"hunter2-never-logged"


@pytest.fixture
def running_agent():
    root = Path(tempfile.mkdtemp())
    endpoint = root / "agent.sock"
    agent = Agent(socket_path=endpoint)
    thread = threading.Thread(target=agent.serve_forever, daemon=True)
    thread.start()
    for _ in range(50):  # the listener is up before the first client call
        if _reachable(endpoint):
            break
        time.sleep(0.1)
    try:
        yield agent, endpoint
    finally:
        agent.shutdown()
        thread.join(timeout=5)


def test_a_secret_survives_one_connection_and_returns_on_the_next(running_agent) -> None:
    """The reason the agent exists: sudo's askpass is a fresh process each time."""
    _agent, endpoint = running_agent
    client = AgentClient(endpoint)
    assert client.alive()
    client.set("db-password", bytearray(SECRET))
    assert bytes(AgentClient(endpoint).get("db-password")) == SECRET


def test_drop_removes_it(running_agent) -> None:
    _agent, endpoint = running_agent
    client = AgentClient(endpoint)
    client.set("db-password", bytearray(SECRET))
    client.drop("db-password")
    assert client.get("db-password") is None


def test_a_peer_from_another_account_is_refused(running_agent, monkeypatch) -> None:
    """The uid/SID comparison, exercised without a second user account.

    Moving the *agent's* idea of its own identity is equivalent to the peer's
    differing, and it is the only way to reach this branch in a single-user
    test run.
    """
    _agent, endpoint = running_agent
    monkeypatch.setattr(platform, "current_user_id", lambda: "not-this-account")
    with pytest.raises(AgentError) as refusal:
        AgentClient(endpoint).set("db-password", bytearray(SECRET))
    assert "peer" in str(refusal.value).casefold()


def test_peer_identity_comes_from_the_kernel(running_agent) -> None:
    """Not from anything the client sends, which it could lie about."""
    _agent, endpoint = running_agent
    conn = platform.agent_connect(endpoint, 5.0)
    try:
        pid, user = platform.agent_peer_credentials(conn) if not platform.IS_WINDOWS else (None, None)
    finally:
        conn.close()
    # On Windows the server holds the pipe end that can answer this; asserting
    # the server-side path is what `test_a_peer_from_another_account_is_refused`
    # covers. Here, only the POSIX direction is directly observable.
    if not platform.IS_WINDOWS:
        assert user == platform.current_user_id()


def test_a_second_agent_will_not_share_the_endpoint(running_agent) -> None:
    """Two agents on one endpoint would split the cache and confuse clients."""
    _agent, endpoint = running_agent
    with pytest.raises((AgentError, OSError)):
        Agent(socket_path=endpoint)._bind()


@pytest.mark.skipif(not platform.IS_WINDOWS, reason="named-pipe ACL is Windows-only")
def test_the_pipe_grants_access_to_this_account_only(running_agent) -> None:
    """Read the DACL back off the live pipe, rather than trusting the input.

    The POSIX socket's guard is a 0700 directory; the pipe's is this ACL, so
    an ACL that silently failed to apply would quietly widen access to every
    local account.
    """
    import ctypes
    import ctypes.wintypes as w

    from sleipnir.platform import _win32, _windows

    _agent, endpoint = running_agent
    name = _windows._pipe_name(endpoint)

    handle = _win32.kernel32.CreateFileW(
        name, _win32.GENERIC_READ, 0, None, _win32.OPEN_EXISTING, 0, None
    )
    assert handle != _win32.INVALID_HANDLE_VALUE, "could not open the pipe to inspect it"
    try:
        advapi32 = _win32.advapi32
        advapi32.GetSecurityInfo.argtypes = [
            w.HANDLE, ctypes.c_int, w.DWORD,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        advapi32.GetSecurityInfo.restype = w.DWORD
        advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
            ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.POINTER(w.LPWSTR), ctypes.POINTER(w.ULONG)
        ]
        advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = w.BOOL

        descriptor = ctypes.c_void_p()
        SE_KERNEL_OBJECT, DACL_SECURITY_INFORMATION = 6, 0x00000004
        status = advapi32.GetSecurityInfo(
            handle, SE_KERNEL_OBJECT, DACL_SECURITY_INFORMATION,
            None, None, None, None, ctypes.byref(descriptor),
        )
        assert status == 0, f"GetSecurityInfo failed with {status}"
        text = w.LPWSTR()
        assert advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor, 1, DACL_SECURITY_INFORMATION, ctypes.byref(text), None
        )
        sddl = str(text.value)
        _win32.kernel32.LocalFree(text)
    finally:
        _win32.kernel32.CloseHandle(handle)

    me = platform.current_user_id()
    assert me in sddl, f"this account is not in the pipe DACL: {sddl}"
    assert sddl.count("(A;") == 1, f"the pipe DACL grants more than one account: {sddl}"
    assert sddl.startswith("D:P"), f"the pipe DACL is not protected from inheritance: {sddl}"
