"""FarmerSync — synchronous wrapper around async Farmer.

Runs the async Farmer on a dedicated event loop in a background
thread, exposing a fully synchronous API.

Example:
    >>> farmer = FarmerSync.connect("http://127.0.0.1:9222")
    >>> farmer.goto("https://example.com")
    >>> farmer.click("#submit")
    >>> farmer.close()
"""

import asyncio
import threading
from typing import Optional


class FarmerSync:
    """Synchronous wrapper around ``Farmer``.

    All async methods are callable synchronously via a dedicated
    background event loop. Thread-safe for single-threaded callers.

    Example:
        >>> with FarmerSync.connect("http://127.0.0.1:9222") as f:
        ...     f.goto("https://example.com")
        ...     f.click("#submit")
    """

    def __init__(self, farmer):
        """Initialize sync wrapper (use ``connect()`` or ``launch()``).

        Args:
            farmer: Async ``Farmer`` instance to wrap.
        """
        self._farmer = farmer
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

    @staticmethod
    def _create_event_loop() -> tuple[asyncio.AbstractEventLoop, threading.Thread]:
        """Create a dedicated event loop on a background thread."""
        loop = asyncio.new_event_loop()

        def _run():
            asyncio.set_event_loop(loop)
            loop.run_forever()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return loop, t

    def _run(self, coro):
        """Run a coroutine on the background loop and block for result.

        Args:
            coro: Coroutine to execute.

        Returns:
            The coroutine's return value.
        """
        if self._loop is None or self._loop.is_closed():
            self._loop, self._thread = self._create_event_loop()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=120)

    @staticmethod
    def connect(debug_url: str, **kwargs) -> "FarmerSync":
        """Connect to an existing Chrome instance (synchronous).

        Args:
            debug_url: Chrome debug URL.
            **kwargs: Additional args for ``Farmer.connect()``.

        Returns:
            ``FarmerSync`` instance.
        """
        from farmer.farmer import Farmer

        loop, thread = FarmerSync._create_event_loop()
        future = asyncio.run_coroutine_threadsafe(
            Farmer.connect(debug_url, **kwargs), loop
        )
        farmer = future.result(timeout=30)
        sync = FarmerSync(farmer)
        sync._loop = loop
        sync._thread = thread
        return sync

    @staticmethod
    def launch(**kwargs) -> "FarmerSync":
        """Launch a new Chrome instance and connect (synchronous).

        Args:
            **kwargs: Additional args for ``Farmer.launch()``.

        Returns:
            ``FarmerSync`` instance.
        """
        from farmer.farmer import Farmer

        loop, thread = FarmerSync._create_event_loop()
        future = asyncio.run_coroutine_threadsafe(
            Farmer.launch(**kwargs), loop
        )
        farmer = future.result(timeout=60)
        sync = FarmerSync(farmer)
        sync._loop = loop
        sync._thread = thread
        return sync

    def close(self):
        """Close browser, CDP connection, and stop the background loop."""
        self._run(self._farmer.close())
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)

    # ── Context Manager ──

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ── Access Layers ──

    @property
    def browser(self):
        """Browser: Tab and page manager."""
        return self._farmer.browser

    @property
    def page(self):
        """Page: Currently active page."""
        return self._farmer.page

    @property
    def human(self):
        """Human: Behavioral simulation layer."""
        return self._farmer.human

    @property
    def images(self):
        """ImageSearch: OpenCV template matching engine."""
        return self._farmer.images

    # ── Shortcuts (sync wrappers) ──

    def goto(self, url: str, **kw):
        """Navigate to URL (sync)."""
        return self._run(self._farmer.goto(url, **kw))

    def click(self, target, **kw):
        """Human click (sync)."""
        return self._run(self._farmer.click(target, **kw))

    def fill(self, target, text: str, **kw):
        """Human fill (sync)."""
        return self._run(self._farmer.fill(target, text, **kw))

    def type(self, text: str, **kw):
        """Human type (sync)."""
        return self._run(self._farmer.type(text, **kw))

    def screenshot(self, **kw):
        """Capture screenshot (sync)."""
        return self._run(self._farmer.screenshot(**kw))

    def wait_for(self, selector: str, **kw):
        """Wait for selector (sync)."""
        return self._run(self._farmer.wait_for(selector, **kw))
