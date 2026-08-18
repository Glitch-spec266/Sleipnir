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

import pytest

import sleipnir.budget as budget


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "allow_utilization_reads: opt out of the hermetic guards below. Only for "
        "tests that exercise the reader itself, and only with a mock transport "
        "or a fixture credential file — never the real endpoint.",
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
