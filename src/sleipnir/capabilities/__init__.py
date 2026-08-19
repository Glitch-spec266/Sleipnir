"""Operator-authorised capabilities: the desk the robot sits at.

Everything in this package deliberately breaks the sandbox the executor builds
around worker tasks.  That is the point — but it means the boundary has to be
explicit rather than incidental:

* Capabilities are **never** handed to a worker task.  Workers keep the
  credential-stripped environment and the confined attempt workspace.  Only the
  operator-facing console, and the brain acting on an operator instruction, may
  reach these.
* Every call is appended to an audit log so there is a record of what the
  machine did on the operator's behalf.
* Secrets never enter this package's return values, its log, a model prompt, or
  ``results.jsonl``.  See :mod:`sleipnir.capabilities.secrets`.
"""

from __future__ import annotations

__all__ = ["audit", "clipboard", "computer", "secrets"]
