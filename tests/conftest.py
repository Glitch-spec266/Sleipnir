"""Test-suite guardrails.

The budget governor reads real window utilisation from
``GET /api/oauth/usage``, authenticated with the OAuth token the `claude` CLI
stores. That is correct in production and unacceptable in a test run: it makes
the suite depend on the network, and it puts a bearer token on the wire every
time anyone types `pytest`.

Both fixtures below are autouse, so hermetic is the default and a test that
wants the real thing has to say so.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

import sleipnir.budget as budget


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "allow_utilization_reads: opt out of the hermetic guards below. Only for "
        "tests that exercise the reader itself, and only with a mock transport "
        "or a fixture credential file — never the real endpoint.",
    )


def _probe_symlink_privilege() -> bool:
    """Whether this process can create a file symlink right now.

    Always true on POSIX. On Windows, ``os.symlink`` needs either Developer
    Mode (a machine-wide opt-in, off by default) or an elevated process --
    reproduced live on an ordinary, non-elevated dev machine as
    ``OSError: [WinError 1314] A required privilege is not held by the
    client``. GitHub's ``windows-latest`` runners ship with Developer Mode
    on, so this still exercises the real symlink-containment defence in CI;
    it only skips on a stock local Windows install.
    """
    if sys.platform != "win32":
        return True
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "target.txt"
        link = Path(tmp) / "link.txt"
        target.write_text("x")
        try:
            os.symlink(target, link)
        except OSError:
            return False
        return True


#: Computed once per test session; creating a real symlink to probe this on
#: every call would be needless I/O for what is a fixed machine capability.
CAN_SYMLINK = _probe_symlink_privilege()

requires_symlink = pytest.mark.skipif(
    not CAN_SYMLINK,
    reason="this account cannot create symlinks (needs Windows Developer Mode "
    "or elevation) -- the containment behaviour this test checks is exercised "
    "in CI, where Developer Mode is on by default",
)


@pytest.fixture(autouse=True)
def no_real_utilization_reads(monkeypatch, request):
    """Never call the usage endpoint from a test.

    Returns ``None``, which is the same path taken when the credential is
    missing or expired — so the suite exercises the fallback that real users
    without a credential will hit.
    """
    if request.node.get_closest_marker("allow_utilization_reads"):
        return
    monkeypatch.setattr(budget, "fetch_window_utilization", lambda **_: None)


@pytest.fixture(autouse=True)
def no_credential_reads(monkeypatch, request):
    """Belt and braces: the token must not be read from disk either.

    A test that needs to exercise token parsing should monkeypatch
    ``read_oauth_token`` back, or call it with an explicit path fixture.
    """
    if request.node.get_closest_marker("allow_utilization_reads"):
        return
    monkeypatch.setattr(budget, "read_oauth_token", lambda *a, **k: None)


requires_junction = pytest.mark.skipif(
    sys.platform != "win32", reason="NTFS junctions are a Windows-only shape"
)


def make_junction(link: Path, target: Path) -> None:
    """Create an NTFS directory junction at ``link`` pointing at ``target``.

    The counterpart to ``requires_symlink``, and the more important one: a
    junction needs neither Developer Mode nor elevation, so it is the reparse
    point a subagent on a stock Windows install can actually create. The
    symlink tests skip on such a machine; these do not.

    ``_winapi.CreateJunction`` is private but is what the stdlib's own ``venv``
    uses; the alternative is shelling out to ``mklink /J``.
    """
    import _winapi

    _winapi.CreateJunction(str(target), str(link))
