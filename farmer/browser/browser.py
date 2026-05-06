"""Browser — centralized tab/page manager.

Discovers existing browser targets, tracks tab creation/destruction
via CDP ``Target`` events, and provides a Playwright-like API for
multi-tab management.

Example:
    >>> browser = Browser(cdp, log)
    >>> await browser._init()
    >>> new_page = await browser.new_page("https://example.com")
    >>> await browser.switch_to(new_page)
"""

import asyncio
from typing import Callable, Optional

from farmer.core.connection import CDPConnection
from farmer.core.logger import FarmerLogger
from farmer.page.page import Page


class Browser:
    """Centralized tab/page manager for CDP connections.

    Tracks ``Target.targetCreated`` and ``Target.targetDestroyed``
    events to maintain an up-to-date map of open pages. Provides
    methods to create, close, and switch between tabs.

    Example:
        >>> browser = Browser(cdp_connection, logger)
        >>> await browser._init()
        >>> print(f"Open tabs: {len(browser.pages)}")
    """

    def __init__(self, cdp: CDPConnection, log: FarmerLogger = None):
        """Initialize the browser manager.

        Args:
            cdp: Active CDP connection instance.
            log: Structured logger. Creates a default if ``None``.
        """
        self._cdp = cdp
        self._log = log or FarmerLogger()
        self._pages: dict[str, Page] = {}  # target_id -> Page
        self._active_target_id: Optional[str] = None

        self._on_page_created_cb: Optional[Callable] = None
        self._on_page_closed_cb: Optional[Callable] = None

    @property
    def pages(self) -> list[Page]:
        """list[Page]: All currently open pages."""
        return list(self._pages.values())

    @property
    def page(self) -> Optional[Page]:
        """Optional[Page]: The currently active page, or the first page as fallback."""
        if self._active_target_id and self._active_target_id in self._pages:
            return self._pages[self._active_target_id]
        if self._pages:
            first_id = next(iter(self._pages))
            self._active_target_id = first_id
            return self._pages[first_id]
        return None

    async def _init(self):
        """Discover existing targets and set up event listeners.

        Temporarily enables target discovery, scans for existing
        page targets, initializes the first page, then disables
        continuous discovery to reduce CDP traffic.
        """
        # Enable target discovery temporarily for initial scan
        await self._cdp.send("Target.setDiscoverTargets", {"discover": True})

        # Get existing targets
        result = await self._cdp.send("Target.getTargets")
        for target_info in result.get("targetInfos", []):
            if target_info.get("type") == "page":
                tid = target_info["targetId"]
                page = Page(self._cdp, target_id=tid, log=self._log)
                self._pages[tid] = page
                if self._active_target_id is None:
                    self._active_target_id = tid

        # Initialize first page
        if self.page:
            await self.page._init_page()

        # Listen for target events (still fires without discover=True
        # when targets are created via Target.createTarget)
        self._cdp.on_event("Target.targetCreated", self._on_target_created)
        self._cdp.on_event("Target.targetDestroyed", self._on_target_destroyed)

        # Disable continuous discovery to reduce CDP event traffic
        # Target events still fire for explicitly created/closed targets
        try:
            await self._cdp.send("Target.setDiscoverTargets", {"discover": False})
        except Exception:
            pass

        self._log.info(f"Browser initialized with {len(self._pages)} page(s)")

    def _on_target_created(self, params: dict):
        """Handle new tab/window creation events.

        Args:
            params: CDP ``Target.targetCreated`` event parameters.
        """
        target_info = params.get("targetInfo", {})
        if target_info.get("type") == "page":
            tid = target_info["targetId"]
            if tid not in self._pages:
                page = Page(self._cdp, target_id=tid, log=self._log)
                self._pages[tid] = page
                self._log.info(f"Page created: {tid}")
                if self._on_page_created_cb:
                    try:
                        self._on_page_created_cb(page)
                    except Exception:
                        pass

    def _on_target_destroyed(self, params: dict):
        """Handle tab/window close events.

        Args:
            params: CDP ``Target.targetDestroyed`` event parameters.
        """
        tid = params.get("targetId", "")
        if tid in self._pages:
            page = self._pages.pop(tid)
            self._log.info(f"Page closed: {tid}")
            if self._active_target_id == tid:
                self._active_target_id = next(iter(self._pages), None)
            if self._on_page_closed_cb:
                try:
                    self._on_page_closed_cb(page)
                except Exception:
                    pass

    async def new_page(self, url: str = None) -> Page:
        """Open a new browser tab and return its Page.

        Creates a new target, attaches to it, and initializes
        the page. The new page becomes the active page.

        Args:
            url: Initial URL to navigate to. Defaults to
                ``"about:blank"``.

        Returns:
            Initialized ``Page`` instance for the new tab.

        Example:
            >>> page = await browser.new_page("https://example.com")
        """
        params = {"url": url or "about:blank"}
        result = await self._cdp.send("Target.createTarget", params)
        tid = result["targetId"]

        # Attach
        await self._cdp.send("Target.attachToTarget", {
            "targetId": tid, "flatten": True,
        })

        page = Page(self._cdp, target_id=tid, log=self._log)
        await page._init_page()
        self._pages[tid] = page
        self._active_target_id = tid
        return page

    async def close_page(self, page: Page):
        """Close a specific page/tab.

        Args:
            page: The ``Page`` instance to close.
        """
        tid = page.target_id
        if tid:
            await self._cdp.send("Target.closeTarget", {"targetId": tid})
            self._pages.pop(tid, None)
            if self._active_target_id == tid:
                self._active_target_id = next(iter(self._pages), None)

    async def switch_to(self, page: Page):
        """Switch focus to a specific page.

        Args:
            page: The ``Page`` instance to activate.
        """
        if page.target_id in self._pages:
            self._active_target_id = page.target_id
            await self._cdp.send("Target.activateTarget", {
                "targetId": page.target_id,
            })

    async def switch_to_index(self, index: int):
        """Switch to a page by its index in the pages list.

        Args:
            index: Zero-based page index.

        Raises:
            IndexError: If index is out of range.

        Example:
            >>> await browser.switch_to_index(0)  # first tab
        """
        pages = self.pages
        if 0 <= index < len(pages):
            await self.switch_to(pages[index])
        else:
            raise IndexError(f"Page index {index} out of range (0-{len(pages) - 1})")

    def on_page_created(self, callback: Callable):
        """Register a callback for new tab creation events.

        Args:
            callback: Function accepting a single ``Page`` argument.
        """
        self._on_page_created_cb = callback

    def on_page_closed(self, callback: Callable):
        """Register a callback for tab close events.

        Args:
            callback: Function accepting a single ``Page`` argument.
        """
        self._on_page_closed_cb = callback

    async def close(self):
        """Close all managed pages/tabs."""
        for tid in list(self._pages.keys()):
            try:
                await self._cdp.send("Target.closeTarget", {"targetId": tid})
            except Exception:
                pass
        self._pages.clear()
        self._active_target_id = None
