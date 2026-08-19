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

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sleipnir.capabilities import audit
from sleipnir.capabilities.computer import CapabilityError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sleipnir.capabilities.secrets import Secret

DEFAULT_PROFILE = Path.home() / ".sleipnir" / "browser-profile"


def available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
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

    async def start(self) -> Browser:
        try:
            from playwright.async_api import async_playwright
        except ImportError as error:  # pragma: no cover - environment dependent
            raise CapabilityError(
                "playwright is not installed; run `sleipnir setup`"
            ) from error
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            str(self.profile_dir),
            headless=self.headless,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        audit.record("browser.start", {"profile": str(self.profile_dir), "headless": self.headless})
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

    async def text(self, selector: str = "body") -> str:
        return await self.page.inner_text(selector)

    async def screenshot(self, path: str | Path) -> Path:
        destination = Path(path).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        await self.page.screenshot(path=str(destination), full_page=True)
        audit.record("browser.screenshot", {"path": str(destination)})
        return destination

    async def close(self) -> None:
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        audit.record("browser.close", {})

    async def __aenter__(self) -> Browser:
        return await self.start()

    async def __aexit__(self, *_: object) -> None:
        await self.close()


__all__ = ["Browser", "DEFAULT_PROFILE", "available"]
