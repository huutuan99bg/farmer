"""Farmer — async entry point combining all layers.

Provides a unified API that combines Browser (tab manager),
Page (mechanical CDP), Human (behavioral simulation), and
ImageSearch (OpenCV template matching).

Example:
    >>> async with await Farmer.connect("http://127.0.0.1:9222") as f:
    ...     await f.goto("https://example.com")
    ...     await f.click("#submit")
"""

import asyncio
import logging
from typing import Optional

from farmer.core.connection import CDPConnection
from farmer.core.logger import FarmerLogger
from farmer.browser.browser import Browser
from farmer.browser.launcher import ChromeLauncher
from farmer.browser.connector import CDPConnector
from farmer.page.page import Page
from farmer.human.human import Human
from farmer.image_search import ImageSearch


class Farmer:
    """Unified async entry point for browser automation.

    Combines lifecycle management with all interaction layers.

    Attributes:
        browser: Tab/page manager (``Browser``).
        page: Active page, mechanical layer (``Page``).
        human: Behavioral simulation layer (``Human``).
        images: Image-based element search (``ImageSearch``).
    """

    def __init__(
        self,
        cdp: CDPConnection,
        browser: Browser,
        human: Human,
        images: ImageSearch,
        log: FarmerLogger,
        process=None,
    ):
        """Initialize Farmer (use ``launch()`` or ``connect()`` instead).

        Args:
            cdp: Active CDP connection.
            browser: Browser tab manager.
            human: Human interaction layer.
            images: ImageSearch instance.
            log: Structured logger.
            process: Optional Chrome subprocess (if launched).
        """
        self._cdp = cdp
        self._browser = browser
        self._human = human
        self._images = images
        self._log = log
        self._process = process  # Chrome process if launched

    # ── Lifecycle ──

    @staticmethod
    async def launch(
        executable_path: str = None,
        headless: bool = False,
        proxy: str = None,
        extensions: list[str] = None,
        user_data_dir: str = None,
        viewport: tuple[int, int] = (1280, 720),
        port: int = 0,
        args: list[str] = None,
        log_level: int = logging.INFO,
        **cdp_kwargs,
    ) -> "Farmer":
        """Launch a new Chrome instance and connect to it.

        Args:
            executable_path: Path to Chrome. Auto-detected if ``None``.
            headless: Run in headless mode.
            proxy: Proxy server URL.
            extensions: Extension directory paths.
            user_data_dir: Chrome profile directory.
            viewport: Window size ``(width, height)``.
            port: Debug port. ``0`` = random.
            args: Additional Chrome flags.
            log_level: Logging level.
            **cdp_kwargs: Additional CDP connection options.

        Returns:
            Configured ``Farmer`` instance.
        """
        log = FarmerLogger(level=log_level)
        log.info("Launching Chrome...")

        process, debug_url = await ChromeLauncher.launch(
            executable_path=executable_path,
            headless=headless,
            proxy=proxy,
            extensions=extensions,
            user_data_dir=user_data_dir,
            viewport=viewport,
            port=port,
            args=args,
        )

        cdp_kwargs["logger"] = log
        conn, target_id = await CDPConnector.connect(debug_url, **cdp_kwargs)

        browser = Browser(conn, log)
        await browser._init()

        page = browser.page
        human = Human(conn, viewport=viewport, log=log, target_id=target_id)
        await human._init_page()
        images = ImageSearch(page, human)

        return Farmer(conn, browser, human, images, log, process=process)

    @staticmethod
    async def connect(
        debug_url: str,
        viewport: tuple[int, int] = (1280, 720),
        log_level: int = logging.INFO,
        **cdp_kwargs,
    ) -> "Farmer":
        """Connect to an existing Chrome instance via CDP debug URL.

        Args:
            debug_url: Chrome debug URL (e.g., ``"http://127.0.0.1:9222"``).
            viewport: Assumed viewport size for Human layer.
            log_level: Logging level.
            **cdp_kwargs: Additional CDP connection options.

        Returns:
            Configured ``Farmer`` instance.
        """
        log = FarmerLogger(level=log_level)
        log.info(f"Connecting to {debug_url}...")

        cdp_kwargs["logger"] = log
        conn, target_id = await CDPConnector.connect(debug_url, **cdp_kwargs)

        browser = Browser(conn, log)
        await browser._init()

        page = browser.page
        human = Human(conn, viewport=viewport, log=log, target_id=target_id)
        await human._init_page()
        images = ImageSearch(page, human)

        return Farmer(conn, browser, human, images, log)

    async def close(self):
        """Close browser, CDP connection, and Chrome process (if launched)."""
        self._log.info("Closing...")
        try:
            await self._browser.close()
        except Exception:
            pass
        try:
            await self._cdp.close()
        except Exception:
            pass
        if self._process:
            try:
                self._process.terminate()
                await asyncio.sleep(0.5)
                if self._process.returncode is None:
                    self._process.kill()
            except Exception:
                pass

    # ── Context Manager ──

    async def __aenter__(self) -> "Farmer":
        return self

    async def __aexit__(self, *exc):
        await self.close()

    # ── Access Layers ──

    @property
    def browser(self) -> Browser:
        """Browser: Tab and page manager."""
        return self._browser

    @property
    def page(self) -> Page:
        """Page: Currently active page (delegated to ``browser.page``)."""
        return self._browser.page

    @property
    def human(self) -> Human:
        """Human: Behavioral simulation layer."""
        return self._human

    @property
    def images(self) -> ImageSearch:
        """ImageSearch: OpenCV template matching engine."""
        return self._images

    # ── Shortcuts ──

    async def goto(self, url: str, **kw):
        """Navigate to a URL (shortcut for ``page.goto()``)."""
        return await self.page.goto(url, **kw)

    async def click(self, target, **kw):
        """Human click (shortcut for ``human.click()``)."""
        return await self._human.click(target, **kw)

    async def fill(self, target, text: str, **kw):
        """Human fill (shortcut for ``human.fill()``)."""
        return await self._human.fill(target, text, **kw)

    async def type(self, text: str, **kw):
        """Human type (shortcut for ``human.type()``)."""
        return await self._human.type(text, **kw)

    async def screenshot(self, **kw):
        """Capture screenshot (shortcut for ``page.screenshot()``)."""
        return await self.page.screenshot(**kw)

    async def wait_for(self, selector: str, **kw):
        """Wait for selector (shortcut for ``page.wait_for_selector()``)."""
        return await self.page.wait_for_selector(selector, **kw)

    def locator(self, selector: str):
        """Lazy locator (Page behavior)."""
        return self.page.locator(selector)

    async def locator_wait(self, selector: str, **kw):
        """Auto-wait locator (Human behavior)."""
        return await self._human.locator(selector, **kw)
