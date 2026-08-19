"""Real browser control, for the work that only exists behind a login.

Provisioning an API key or standing up hosting is a web flow, not an API call —
there is no headless endpoint for "click through the signup, accept the terms,
copy the key".  So this drives an actual Chromium.

Two decisions worth stating:

* **Persistent profile, not a fresh context.**  Sessions have to survive
  between runs or the agent re-authenticates on every task, which means asking
  the operator for credentials over and over — the opposite of the goal.
* **Headed by default.**  The operator must be able to watch, and many signup
  flows fingerprint headless browsers and block them.

Playwright is imported lazily so that the rest of Sleipnir — and its test
suite — still runs on a machine where the browser was never installed.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import stat
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sleipnir.capabilities import audit
from sleipnir.capabilities.computer import CapabilityError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sleipnir.capabilities.secrets import Secret

DEFAULT_PROFILE = Path.home() / ".sleipnir" / "browser-profile"

#: Fixed port for the long-lived browser. A file-based endpoint would have to
#: be reconciled with a browser that died; a fixed port is checked by simply
#: asking it whether it is there.
DEBUG_PORT = 9333
CDP_ENDPOINT = f"http://127.0.0.1:{DEBUG_PORT}"
#: Where the detached browser's pid is recorded. Needed because closing a
#: CDP *connection* does not close the browser — `browser close` reported
#: success while Chromium kept running, which is exactly the kind of stray
#: process that makes a tool feel untrustworthy.
PID_FILE = Path.home() / ".sleipnir" / "browser.pid"


def _publish_pid(pid: int, path: Path | None = None) -> None:
    """Atomically publish a private PID file without following an old symlink."""
    path = PID_FILE if path is None else path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(str(pid))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_pid(path: Path | None = None) -> int | None:
    path = PID_FILE if path is None else path
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 32:
            return None
        raw = os.read(descriptor, 32)
        pid = int(raw.decode("ascii").strip())
        return pid if pid > 1 else None
    except (OSError, UnicodeError, ValueError):
        return None
    finally:
        os.close(descriptor)


def _pid_matches_browser(
    pid: int,
    profile_dir: Path | None = None,
    *,
    proc_root: Path = Path("/proc"),
) -> bool:
    """Verify the PID still names Sleipnir's exact Chromium invocation."""
    profile_dir = DEFAULT_PROFILE if profile_dir is None else profile_dir
    try:
        argv = (proc_root / str(pid) / "cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    decoded = {arg.decode("utf-8", "replace") for arg in argv if arg}
    return (
        f"--remote-debugging-port={DEBUG_PORT}" in decoded
        and f"--user-data-dir={profile_dir}" in decoded
    )


def _cdp_alive(timeout_s: float = 0.5) -> bool:
    import httpx

    try:
        response = httpx.get(f"{CDP_ENDPOINT}/json/version", timeout=timeout_s)
    except Exception:  # noqa: BLE001 - any failure means "not there"
        return False
    return response.status_code == 200


async def ensure_browser(profile_dir: Path = DEFAULT_PROFILE, *, headless: bool = False) -> str:
    """Start the shared browser if it is not already running, and return its endpoint.

    This exists because a browser that dies with the command that opened it is
    useless for the only job it was added for. ``browser open`` followed by
    ``browser click`` are two separate CLI processes; with Playwright's managed
    lifecycle the second one got a brand-new blank browser, so every multi-step
    web flow — every sign-in, which is the point — was impossible. It also looks
    exactly like a bug from the outside: the same window opening and closing
    over and over.

    So Chromium is launched as a detached OS process and driven over CDP.
    Playwright still does the automation; it just no longer owns the process
    lifetime.
    """
    import subprocess

    if _cdp_alive():
        return CDP_ENDPOINT

    if profile_dir.exists() and (profile_dir.is_symlink() or not profile_dir.is_dir()):
        raise CapabilityError(f"unsafe browser profile directory: {profile_dir}")
    profile_dir.mkdir(parents=True, exist_ok=True)
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    try:
        executable = playwright.chromium.executable_path
    finally:
        await playwright.stop()

    argv = [
        executable,
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        # Without a starting page Chromium exits immediately on some builds.
        "about:blank",
    ]
    if headless:
        argv.insert(1, "--headless=new")
    process = subprocess.Popen(  # noqa: S603 - fixed argv from the installed browser
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    _publish_pid(process.pid)

    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        if _cdp_alive():
            audit.record("browser.daemon_started", {"endpoint": CDP_ENDPOINT})
            return CDP_ENDPOINT
        await asyncio.sleep(0.2)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    PID_FILE.unlink(missing_ok=True)
    raise CapabilityError(
        f"the browser did not open a debugging port on {CDP_ENDPOINT} within 20s"
    )


def available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def stop_browser(timeout_s: float = 8.0) -> bool:
    """Terminate the detached browser, if one is running. True if it stopped."""
    pid = _read_pid()
    if pid is None or not _pid_matches_browser(pid):
        PID_FILE.unlink(missing_ok=True)
        return False
    try:
        group = os.getpgid(pid)
        if group != pid:
            PID_FILE.unlink(missing_ok=True)
            return False
        os.killpg(group, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        PID_FILE.unlink(missing_ok=True)
        return False

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _cdp_alive(0.2):
            break
        time.sleep(0.2)
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    PID_FILE.unlink(missing_ok=True)
    return True


@dataclass
class Browser:
    """An open browser the agent can drive.

    Deliberately a thin wrapper: it exposes the Playwright page so an agent can
    do anything Playwright can, while routing the few operations that touch
    credentials or the filesystem through audited helpers.
    """

    profile_dir: Path = DEFAULT_PROFILE
    headless: bool = False
    _playwright: Any = None
    _context: Any = None
    _browser: Any = None

    async def start(self) -> Browser:
        """Attach to the shared browser, starting it only if nobody has.

        Attaching rather than launching is the whole fix: the browser outlives
        the command, so a sign-in survives from `browser open` to `browser fill`
        to `browser click`.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError as error:  # pragma: no cover - environment dependent
            raise CapabilityError(
                "playwright is not installed; run `sleipnir setup`"
            ) from error
        endpoint = await ensure_browser(self.profile_dir, headless=self.headless)
        self._playwright = await async_playwright().start()
        browser = await self._playwright.chromium.connect_over_cdp(endpoint)
        contexts = browser.contexts
        self._context = contexts[0] if contexts else await browser.new_context()
        self._browser = browser
        audit.record("browser.attached", {"endpoint": endpoint})
        return self

    @property
    def page(self) -> Any:
        if self._context is None:
            raise CapabilityError("browser not started")
        pages = self._context.pages
        return pages[0] if pages else None

    async def new_page(self) -> Any:
        if self._context is None:
            raise CapabilityError("browser not started")
        return await self._context.new_page()

    async def goto(self, url: str, *, wait: str = "domcontentloaded") -> Any:
        page = self.page or await self.new_page()
        await page.goto(url, wait_until=wait)
        audit.record("browser.goto", {"url": url})
        return page

    async def click(self, selector: str) -> None:
        await self.page.click(selector)
        audit.record("browser.click", {"selector": selector})

    async def fill(self, selector: str, value: str) -> None:
        await self.page.fill(selector, value)
        audit.record("browser.fill", {"selector": selector, "chars": len(value)})

    async def fill_secret(self, selector: str, secret: Secret) -> None:
        """Put a captured credential into a form field and wipe it.

        Separate from ``fill`` so the audit entry can never carry the value:
        only the field it went into and how long it was.
        """
        await self.page.fill(selector, secret.consume())
        audit.record("browser.fill_secret", {"selector": selector, "label": secret.label})

    async def press(self, selector: str, key: str) -> None:
        await self.page.press(selector, key)
        audit.record("browser.press", {"selector": selector, "key": key})

    async def text(self, selector: str = "body") -> str:
        return await self.page.inner_text(selector)

    async def screenshot(self, path: str | Path) -> Path:
        destination = Path(path).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        await self.page.screenshot(path=str(destination), full_page=True)
        audit.record("browser.screenshot", {"path": str(destination)})
        return destination

    async def close(self) -> None:
        """Detach. Deliberately does **not** close the browser.

        Closing it here is what made multi-step web flows impossible: every CLI
        command would tear down the session it had just established. Use
        ``shutdown()`` to actually end it.
        """
        self._context = None
        if self._browser is not None:
            await self._browser.close()  # closes the CDP connection, not Chromium
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        audit.record("browser.detached", {})

    async def shutdown(self) -> None:
        """Really end the shared browser, discarding its live tabs.

        The profile on disk survives, so logins persist into the next one.

        The process is signalled directly rather than asked politely over CDP:
        disconnecting a CDP client does not close the browser it was driving,
        so the earlier version reported "browser closed" while Chromium carried
        on running. The whole process group goes, because Chromium's renderers
        are children that outlive a bare kill of the parent.
        """
        await self.close()
        stop_browser()
        audit.record("browser.shutdown", {})

    async def __aenter__(self) -> Browser:
        return await self.start()

    async def __aexit__(self, *_: object) -> None:
        await self.close()


__all__ = [
    "Browser",
    "CDP_ENDPOINT",
    "DEBUG_PORT",
    "DEFAULT_PROFILE",
    "available",
    "ensure_browser",
    "stop_browser",
]
