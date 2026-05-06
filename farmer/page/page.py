"""Page — core mechanical layer via Chrome DevTools Protocol.

Provides direct CDP operations without human simulation.
API mirrors Playwright for developer familiarity. All mouse clicks
hit element centers instantly, typing has no delay.

Example:
    >>> page = Page(cdp_connection, target_id="ABC")
    >>> await page._init_page()
    >>> await page.goto("https://example.com")
    >>> el = await page.wait_for_selector("#submit")
    >>> await el.click()
"""

import asyncio
import base64
import random
import uuid
from typing import Any, Callable, Optional, TYPE_CHECKING

from farmer.core.connection import CDPConnection
from farmer.core.logger import FarmerLogger
from farmer.page.mouse_raw import RawMouse
from farmer.page.keyboard_raw import RawKeyboard

if TYPE_CHECKING:
    from farmer.element import Element


class RawTouch:
    """Touch input via CDP ``Input.dispatchTouchEvent``.

    Produces ``isTrusted: true`` touch events in the browser.
    """

    def __init__(self, cdp: CDPConnection):
        self._cdp = cdp

    async def tap(self, x: float, y: float):
        """Perform a tap gesture at the given coordinates.

        Args:
            x: X coordinate in CSS pixels.
            y: Y coordinate in CSS pixels.
        """
        await self._cdp.send("Input.dispatchTouchEvent", {
            "type": "touchStart",
            "touchPoints": [{"x": x, "y": y}],
        })
        await asyncio.sleep(0.05)
        await self._cdp.send("Input.dispatchTouchEvent", {
            "type": "touchEnd",
            "touchPoints": [],
        })


class Page:
    """Core mechanical layer — direct CDP operations.

    No human simulation. Click hits element center, type has no
    delay. For stealth operations, use the ``Human`` layer instead.

    Attributes:
        mouse: Raw mouse controller (``RawMouse``).
        keyboard: Raw keyboard controller (``RawKeyboard``).
        touchscreen: Raw touch controller (``RawTouch``).
        url: Current page URL.
        target_id: CDP target identifier.
    """

    def __init__(
        self,
        cdp: CDPConnection,
        target_id: str = None,
        session_id: str = None,
        log: FarmerLogger = None,
    ):
        """Initialize a Page instance.

        Args:
            cdp: Active CDP connection.
            target_id: CDP target ID for this page.
            session_id: CDP session ID (for attached targets).
            log: Structured logger instance.
        """
        self._cdp = cdp
        self._target_id = target_id
        self._session_id = session_id
        self._log = log or FarmerLogger()

        self._mouse = RawMouse(cdp)
        self._keyboard = RawKeyboard(cdp)
        self._touch = RawTouch(cdp)

        self._url: str = ""
        self._frame_id: str = ""
        self._root_node_id: int = 0
        self._dialog_handler: Optional[Callable] = None
        self._dom_enabled: bool = False

    # ── Properties ──

    @property
    def mouse(self) -> RawMouse:
        """RawMouse: Low-level mouse controller."""
        return self._mouse

    @property
    def keyboard(self) -> RawKeyboard:
        """RawKeyboard: Low-level keyboard controller."""
        return self._keyboard

    @property
    def touchscreen(self) -> RawTouch:
        """RawTouch: Low-level touch controller."""
        return self._touch

    @property
    def url(self) -> str:
        """str: Current page URL (updated on navigation)."""
        return self._url

    @property
    def target_id(self) -> str:
        """str: CDP target identifier for this page."""
        return self._target_id or ""

    # ── Init ──

    async def _init_page(self):
        """Enable required CDP domains and set up event listeners.

        Enables ``Page`` domain, discovers main frame, and registers
        handlers for dialogs and navigation events. DOM domain is
        lazy-enabled on first query.
        """
        await self._cdp.send("Page.enable")

        # Get frame tree to find main frame
        try:
            result = await self._cdp.send("Page.getFrameTree")
            frame = result.get("frameTree", {}).get("frame", {})
            self._frame_id = frame.get("id", "")
            self._url = frame.get("url", "")
        except Exception:
            pass

        # DOM.enable is lazy — only enabled when needed, then disabled
        # (reduces timing side-channel fingerprint)

        # Setup dialog handler
        self._cdp.on_event("Page.javascriptDialogOpening", self._on_dialog)

        # Track URL changes
        self._cdp.on_event("Page.frameNavigated", self._on_frame_navigated)

    def _on_frame_navigated(self, params: dict):
        """Track URL changes."""
        frame = params.get("frame", {})
        if frame.get("id") == self._frame_id or not self._frame_id:
            self._url = frame.get("url", self._url)
            self._frame_id = frame.get("id", self._frame_id)

    async def _on_dialog(self, params: dict):
        """Handle JavaScript dialogs (alert/confirm/prompt)."""
        if self._dialog_handler:
            dialog = DialogProxy(self._cdp, params)
            try:
                result = self._dialog_handler(dialog)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                # Auto-dismiss if handler fails
                await dialog.dismiss()
        else:
            # Auto-accept if no handler
            await self._cdp.send("Page.handleJavaScriptDialog", {"accept": True})

    # ── Navigation ──

    async def goto(self, url: str, timeout: float = 30) -> dict:
        """Navigate to a URL and wait for page load.

        Args:
            url: Target URL.
            timeout: Maximum seconds to wait for load event.

        Returns:
            CDP navigation result dict containing ``frameId``.

        Example:
            >>> await page.goto("https://example.com")
        """
        self._log.action("goto", url)
        result = await self._cdp.send("Page.navigate", {"url": url})
        self._url = url

        # Wait for load
        try:
            await self.wait_for_load_state("load", timeout=timeout)
        except asyncio.TimeoutError:
            self._log.warn(f"Timeout waiting for load: {url}")

        return result

    async def reload(self):
        """Reload the current page."""
        self._log.action("reload")
        await self._cdp.send("Page.reload")

    async def go_back(self):
        """Navigate to the previous page in browser history."""
        history = await self._cdp.send("Page.getNavigationHistory")
        idx = history.get("currentIndex", 0)
        if idx > 0:
            entries = history.get("entries", [])
            await self._cdp.send("Page.navigateToHistoryEntry", {
                "entryId": entries[idx - 1]["id"]
            })

    async def go_forward(self):
        """Navigate to the next page in browser history."""
        history = await self._cdp.send("Page.getNavigationHistory")
        idx = history.get("currentIndex", 0)
        entries = history.get("entries", [])
        if idx < len(entries) - 1:
            await self._cdp.send("Page.navigateToHistoryEntry", {
                "entryId": entries[idx + 1]["id"]
            })

    async def title(self) -> str:
        """Get the page title via DOM query.

        Returns:
            Page title string, or empty string if not found.
        """
        root = await self._get_document()
        try:
            result = await self._cdp.send("DOM.querySelector", {
                "nodeId": root, "selector": "title",
            })
            nid = result.get("nodeId", 0)
            if nid:
                html = await self._cdp.send("DOM.getOuterHTML", {"nodeId": nid})
                # Extract text from <title>...</title>
                text = html.get("outerHTML", "")
                start = text.find(">") + 1
                end = text.rfind("<")
                return text[start:end] if start > 0 and end > start else ""
        except Exception:
            pass
        return ""

    # ── Locator ──

    def locator(self, selector: str) -> "Element":
        """Create a lazy Element locator (like Playwright Locator).

        Does NOT query the DOM until an action is called.

        Args:
            selector: CSS selector.

        Returns:
            Lazy ``Element`` instance.

        Example:
            >>> btn = page.locator("#submit")
            >>> await btn.click()  # DOM query happens here
        """
        from farmer.element import Element
        return Element(self, selector)

    # ── Wait ──

    async def wait_for_selector(
        self, selector: str, state: str = "visible", timeout: float = 30
    ) -> "Element":
        """Wait for an element matching the selector to reach a state.

        Args:
            selector: CSS selector.
            state: Target state — ``"visible"``, ``"hidden"``,
                ``"attached"``, or ``"detached"``.
            timeout: Maximum seconds to wait.

        Returns:
            ``Element`` instance once the state is reached.

        Raises:
            TimeoutError: If state not reached within timeout.
        """
        from farmer.element import Element
        deadline = asyncio.get_event_loop().time() + timeout

        while asyncio.get_event_loop().time() < deadline:
            el = Element(self, selector)
            try:
                if state == "attached":
                    node_id = await self._query_selector_id(selector)
                    if node_id:
                        return el
                elif state == "visible":
                    box = await el.bounding_box()
                    if box and box["width"] > 0 and box["height"] > 0:
                        return el
                elif state == "hidden":
                    box = await el.bounding_box()
                    if not box or box["width"] == 0:
                        return el
                elif state == "detached":
                    node_id = await self._query_selector_id(selector)
                    if not node_id:
                        return el
            except Exception:
                pass
            await asyncio.sleep(random.uniform(0.2, 0.5))

        raise TimeoutError(f"Timeout {timeout}s waiting for selector: {selector} (state={state})")

    async def wait_for_load_state(self, state: str = "load", timeout: float = 30):
        """Wait for a page load state.

        Args:
            state: Load state — ``"load"``, ``"domcontentloaded"``,
                or ``"networkidle"``.
            timeout: Maximum seconds to wait.

        Raises:
            ValueError: If ``state`` is not recognized.
            asyncio.TimeoutError: If state not reached.
        """
        if state == "load":
            event = "Page.loadEventFired"
        elif state == "domcontentloaded":
            event = "Page.domContentEventFired"
        elif state == "networkidle":
            await self._wait_network_idle(timeout=timeout)
            return
        else:
            raise ValueError(f"Unknown state: {state}")

        fut = asyncio.get_running_loop().create_future()

        def handler(params):
            if not fut.done():
                fut.set_result(True)

        self._cdp.on_event(event, handler)
        try:
            await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._cdp.remove_event(event, handler)

    async def wait_for_url(self, url_or_pattern: str, timeout: float = 30):
        """Wait until the page URL matches or contains a pattern.

        Args:
            url_or_pattern: Exact URL or substring to match.
            timeout: Maximum seconds to wait.

        Raises:
            TimeoutError: If URL doesn't match within timeout.
        """
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if url_or_pattern in self._url or self._url == url_or_pattern:
                return
            await asyncio.sleep(0.25)
        raise TimeoutError(f"Timeout waiting for URL: {url_or_pattern}")

    # ── DOM (no Runtime) ──

    async def _ensure_dom_enabled(self):
        """Lazy-enable DOM domain only when needed."""
        if not self._dom_enabled:
            await self._cdp.send("DOM.enable")
            self._dom_enabled = True

    async def dom_disable(self):
        """Explicitly disable the DOM domain to reduce fingerprint.

        Call after batch DOM operations are complete. The DOM domain
        will auto re-enable on the next query.
        """
        if self._dom_enabled:
            try:
                await self._cdp.send("DOM.disable")
            except Exception:
                pass
            self._dom_enabled = False

    async def _get_document(self) -> int:
        """Get the root DOM node ID. Lazy-enables DOM domain.

        Returns:
            Root node ID.
        """
        await self._ensure_dom_enabled()
        result = await self._cdp.send("DOM.getDocument", {"depth": 0})
        self._root_node_id = result["root"]["nodeId"]
        return self._root_node_id

    async def _query_selector_id(self, selector: str, root: int = None) -> Optional[int]:
        """Query DOM for a selector, return the first matching node ID.

        Args:
            selector: CSS selector.
            root: Root node ID to search within. If ``None``, uses document root.

        Returns:
            Node ID of the first match, or ``None`` if not found.
        """
        if root is None:
            root = await self._get_document()
        try:
            result = await self._cdp.send("DOM.querySelector", {
                "nodeId": root, "selector": selector,
            })
            nid = result.get("nodeId", 0)
            return nid if nid > 0 else None
        except Exception:
            return None

    async def _query_selector_all_ids(self, selector: str, root: int = None) -> list[int]:
        """Query DOM for all nodes matching a selector.

        Args:
            selector: CSS selector.
            root: Root node ID. If ``None``, uses document root.

        Returns:
            List of matching node IDs (may be empty).
        """
        if root is None:
            root = await self._get_document()
        try:
            result = await self._cdp.send("DOM.querySelectorAll", {
                "nodeId": root, "selector": selector,
            })
            return [nid for nid in result.get("nodeIds", []) if nid > 0]
        except Exception:
            return []

    async def _get_box_model(self, node_id: int) -> Optional[dict]:
        """Get element bounding box from ``DOM.getBoxModel``.

        Args:
            node_id: DOM node ID.

        Returns:
            Dict with ``x``, ``y``, ``width``, ``height``,
            ``center_x``, ``center_y``. ``None`` if not renderable.
        """
        try:
            result = await self._cdp.send("DOM.getBoxModel", {"nodeId": node_id})
            content = result["model"]["content"]
            x1, y1, x2, y2, x3, y3, x4, y4 = content
            x = min(x1, x4)
            y = min(y1, y2)
            w = max(x2, x3) - x
            h = max(y3, y4) - y
            return {
                "x": x, "y": y, "width": w, "height": h,
                "center_x": x + w / 2, "center_y": y + h / 2,
            }
        except Exception:
            return None

    async def _get_attributes(self, node_id: int) -> dict:
        """Get all HTML attributes of a DOM node.

        Args:
            node_id: DOM node ID.

        Returns:
            Dict of ``{attribute_name: attribute_value}``.
        """
        try:
            result = await self._cdp.send("DOM.getAttributes", {"nodeId": node_id})
            attrs = result.get("attributes", [])
            return dict(zip(attrs[::2], attrs[1::2]))
        except Exception:
            return {}

    async def _get_outer_html(self, node_id: int) -> str:
        """Get the outerHTML of a DOM node.

        Args:
            node_id: DOM node ID.

        Returns:
            HTML string, or empty string on error.
        """
        try:
            result = await self._cdp.send("DOM.getOuterHTML", {"nodeId": node_id})
            return result.get("outerHTML", "")
        except Exception:
            return ""

    async def query_selector(self, selector: str) -> "Optional[Element]":
        """Find the first element matching a CSS selector.

        Args:
            selector: CSS selector.

        Returns:
            ``Element`` instance, or ``None`` if not found.
        """
        from farmer.element import Element
        nid = await self._query_selector_id(selector)
        if nid:
            return Element(self, selector, node_id=nid)
        return None

    async def query_selector_all(self, selector: str) -> "list[Element]":
        """Find all elements matching a CSS selector.

        Args:
            selector: CSS selector.

        Returns:
            List of ``Element`` instances (may be empty).
        """
        from farmer.element import Element
        nids = await self._query_selector_all_ids(selector)
        return [Element(self, selector, node_id=nid) for nid in nids]

    async def content(self) -> str:
        """Get the full page HTML content.

        Returns:
            Complete HTML string of the page.
        """
        root = await self._get_document()
        return await self._get_outer_html(root)

    async def inner_text(self, selector: str) -> str:
        """Get the visible text of the first matching element.

        Args:
            selector: CSS selector.

        Returns:
            Extracted text, or empty string if not found.
        """
        nid = await self._query_selector_id(selector)
        if nid:
            html = await self._get_outer_html(nid)
            return self._extract_text(html)
        return ""

    async def get_attribute(self, selector: str, attr: str) -> Optional[str]:
        """Get an attribute value from the first matching element.

        Args:
            selector: CSS selector.
            attr: Attribute name.

        Returns:
            Attribute value, or ``None``.
        """
        nid = await self._query_selector_id(selector)
        if nid:
            attrs = await self._get_attributes(nid)
            return attrs.get(attr)
        return None

    # ── Screenshot ──

    async def screenshot(
        self,
        path: str = None,
        full_page: bool = False,
        clip: dict = None,
    ) -> bytes:
        """Capture a screenshot as PNG bytes.

        Args:
            path: Optional file path to save the PNG.
            full_page: If ``True``, captures the entire scrollable page.
            clip: Optional viewport region ``{x, y, width, height}``.

        Returns:
            PNG image data as bytes.
        """
        params = {"format": "png"}

        if full_page:
            # Get full page metrics
            metrics = await self._cdp.send("Page.getLayoutMetrics")
            content_size = metrics.get("cssContentSize", metrics.get("contentSize", {}))
            params["clip"] = {
                "x": 0, "y": 0,
                "width": content_size.get("width", 1280),
                "height": content_size.get("height", 720),
                "scale": 1,
            }
        elif clip:
            params["clip"] = {**clip, "scale": clip.get("scale", 1)}

        result = await self._cdp.send("Page.captureScreenshot", params)
        data = base64.b64decode(result.get("data", ""))

        if path:
            with open(path, "wb") as f:
                f.write(data)

        return data

    # ── File Upload ──

    async def set_input_files(self, selector: str, files):
        """Upload files to an ``<input type='file'>`` element.

        Args:
            selector: CSS selector for the file input.
            files: Single path string or list of path strings.

        Raises:
            RuntimeError: If file input element not found.
        """
        if isinstance(files, str):
            files = [files]
        nid = await self._query_selector_id(selector)
        if not nid:
            raise RuntimeError(f"File input not found: {selector}")
        await self._cdp.send("DOM.setFileInputFiles", {
            "nodeId": nid, "files": files,
        })

    # ── Cookies ──

    async def cookies(self, urls: list[str] = None) -> list[dict]:
        """Get browser cookies.

        Args:
            urls: Optional list of URLs to filter cookies by.

        Returns:
            List of cookie dicts.
        """
        params = {}
        if urls:
            params["urls"] = urls
        result = await self._cdp.send("Network.getCookies", params)
        return result.get("cookies", [])

    async def add_cookies(self, cookies: list[dict]):
        """Set cookies in the browser.

        Args:
            cookies: List of cookie dicts (each must include
                ``name``, ``value``, ``domain`` or ``url``).
        """
        for cookie in cookies:
            await self._cdp.send("Network.setCookie", cookie)

    async def clear_cookies(self):
        """Clear all cookies."""
        await self._cdp.send("Network.clearBrowserCookies")

    # ── Dialog ──

    def on_dialog(self, handler: Callable):
        """Register dialog handler (alert/confirm/prompt)."""
        self._dialog_handler = handler

    # ── Download ──

    async def set_download_path(self, path: str):
        """Set download folder."""
        await self._cdp.send("Browser.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": path,
        })

    # ── Emulation ──

    async def set_viewport_size(self, width: int, height: int):
        """Set the browser viewport size.

        Args:
            width: Viewport width in pixels.
            height: Viewport height in pixels.
        """
        await self._cdp.send("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height,
            "deviceScaleFactor": 1, "mobile": False,
        })

    async def set_user_agent(self, ua: str, platform: str = None):
        """Override the User-Agent string.

        Warning:
            May create fingerprint inconsistency. See ``detect_alert.md``.

        Args:
            ua: User-Agent string.
            platform: Optional platform override (e.g., ``"Win32"``).
        """
        params = {"userAgent": ua}
        if platform:
            params["platform"] = platform
        await self._cdp.send("Emulation.setUserAgentOverride", params)

    async def set_geolocation(self, latitude: float, longitude: float, accuracy: float = 1):
        """Override browser geolocation.

        Args:
            latitude: Latitude in degrees.
            longitude: Longitude in degrees.
            accuracy: Accuracy in meters.
        """
        await self._cdp.send("Emulation.setGeolocationOverride", {
            "latitude": latitude, "longitude": longitude, "accuracy": accuracy,
        })

    async def set_timezone(self, timezone_id: str):
        """Override the browser timezone.

        Args:
            timezone_id: IANA timezone ID (e.g., ``"Asia/Ho_Chi_Minh"``).
        """
        await self._cdp.send("Emulation.setTimezoneOverride", {
            "timezoneId": timezone_id,
        })

    async def set_locale(self, locale: str):
        """Override the browser locale.

        Args:
            locale: BCP 47 locale string (e.g., ``"vi-VN"``).
        """
        await self._cdp.send("Emulation.setLocaleOverride", {"locale": locale})

    # ── Permissions ──

    async def grant_permissions(self, permissions: list[str], origin: str = None):
        """Grant browser permissions.

        Args:
            permissions: List of permission names (e.g.,
                ``["geolocation", "notifications"]``).
            origin: Optional origin URL to scope permissions.
        """
        params = {"permissions": permissions}
        if origin:
            params["origin"] = origin
        await self._cdp.send("Browser.grantPermissions", params)

    # ── Drag ──

    async def drag_and_drop(self, source_sel: str, target_sel: str):
        """Drag from one element to another using raw mouse events.

        Args:
            source_sel: CSS selector for the drag source.
            target_sel: CSS selector for the drop target.

        Raises:
            RuntimeError: If source or target element not found.
        """
        from farmer.element import Element
        src = Element(self, source_sel)
        dst = Element(self, target_sel)
        src_box = await src.bounding_box()
        dst_box = await dst.bounding_box()
        if not src_box or not dst_box:
            raise RuntimeError("Source or target element not found")

        sx, sy = src_box["center_x"], src_box["center_y"]
        dx, dy = dst_box["center_x"], dst_box["center_y"]

        await self._mouse.move(sx, sy)
        await self._mouse.down()
        await asyncio.sleep(0.1)
        await self._mouse.move(dx, dy)
        await asyncio.sleep(0.05)
        await self._mouse.up()

    # ── Tabs ──

    async def new_page(self, url: str = None) -> "Page":
        """Open a new tab and return a Page for it.

        Args:
            url: Initial URL. Defaults to ``"about:blank"``.

        Returns:
            Initialized ``Page`` for the new tab.
        """
        params = {"url": url or "about:blank"}
        result = await self._cdp.send("Target.createTarget", params)
        new_target_id = result["targetId"]
        # Attach to new target
        attach = await self._cdp.send("Target.attachToTarget", {
            "targetId": new_target_id, "flatten": True,
        })
        new_page = Page(self._cdp, target_id=new_target_id, log=self._log)
        await new_page._init_page()
        return new_page

    async def close(self):
        """Close this page/tab."""
        if self._target_id:
            try:
                await self._cdp.send("Target.closeTarget", {"targetId": self._target_id})
            except Exception:
                pass

    # ── Evaluate Safe ──

    async def evaluate_safe(self, expression: str, world_name: str = None) -> Any:
        """Execute JavaScript in an isolated world.

        Creates a ``Page.createIsolatedWorld`` context and evaluates
        the expression there. Does NOT use ``Runtime.enable``.

        Warning:
            This is a **CRITICAL** detection risk. Sites can detect
            isolated world creation. Only use when no DOM/CDP
            alternative exists. See ``detect_alert.md``.

        Args:
            expression: JavaScript expression to evaluate.
            world_name: Optional world name. If ``None``, a random
                UUID-based name is generated to avoid fingerprinting.

        Returns:
            The evaluated result value.

        Raises:
            RuntimeError: If JavaScript execution throws an error.
        """
        # Random world name to avoid fingerprinting via fixed name
        _world_name = world_name or f"__ctx_{uuid.uuid4().hex[:8]}__"

        # Create isolated world
        result = await self._cdp.send("Page.createIsolatedWorld", {
            "frameId": self._frame_id,
            "worldName": _world_name,
            "grantUniveralAccess": True,
        })
        context_id = result["executionContextId"]

        # Evaluate in isolated context
        result = await self._cdp.send("Runtime.evaluate", {
            "expression": expression,
            "contextId": context_id,
            "returnByValue": True,
            "awaitPromise": True,
        })

        if "exceptionDetails" in result:
            raise RuntimeError(f"JS error: {result['exceptionDetails']}")

        return result.get("result", {}).get("value")

    # ── Events ──

    def on(self, event: str, callback: Callable):
        """Listen for page events using Playwright-style event names.

        Maps friendly names to CDP events:
        ``"load"`` -> ``Page.loadEventFired``,
        ``"response"`` -> ``Network.responseReceived``, etc.

        Args:
            event: Event name (Playwright-style or raw CDP name).
            callback: Handler function accepting event params dict.
        """
        event_map = {
            "load": "Page.loadEventFired",
            "domcontentloaded": "Page.domContentEventFired",
            "response": "Network.responseReceived",
            "request": "Network.requestWillBeSent",
            "dialog": "Page.javascriptDialogOpening",
            "close": "Target.targetDestroyed",
        }
        cdp_event = event_map.get(event, event)
        self._cdp.on_event(cdp_event, callback)

    # ── Private Helpers ──

    async def _wait_network_idle(self, idle_time: float = 0.5, timeout: float = 30):
        """Wait until no network requests for a specified idle period.

        Temporarily enables ``Network`` domain, monitors requests,
        and disables the domain after completion.

        Args:
            idle_time: Seconds of inactivity to consider "idle".
            timeout: Maximum seconds to wait.

        Raises:
            TimeoutError: If network doesn't idle within timeout.
        """
        await self._cdp.send("Network.enable")
        pending = set()
        last_activity = asyncio.get_event_loop().time()

        def on_request(params):
            nonlocal last_activity
            pending.add(params.get("requestId"))
            last_activity = asyncio.get_event_loop().time()

        def on_response(params):
            nonlocal last_activity
            pending.discard(params.get("requestId"))
            last_activity = asyncio.get_event_loop().time()

        def on_finished(params):
            nonlocal last_activity
            pending.discard(params.get("requestId"))
            last_activity = asyncio.get_event_loop().time()

        self._cdp.on_event("Network.requestWillBeSent", on_request)
        self._cdp.on_event("Network.responseReceived", on_response)
        self._cdp.on_event("Network.loadingFinished", on_finished)
        self._cdp.on_event("Network.loadingFailed", on_finished)

        try:
            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                now = asyncio.get_event_loop().time()
                if not pending and (now - last_activity) >= idle_time:
                    return
                await asyncio.sleep(0.1)
            raise TimeoutError("Network idle timeout")
        finally:
            self._cdp.remove_event("Network.requestWillBeSent", on_request)
            self._cdp.remove_event("Network.responseReceived", on_response)
            self._cdp.remove_event("Network.loadingFinished", on_finished)
            self._cdp.remove_event("Network.loadingFailed", on_finished)
            # Disable Network domain after use to reduce timing side-channel
            try:
                await self._cdp.send("Network.disable")
            except Exception:
                pass

    @staticmethod
    def _extract_text(html: str) -> str:
        """Extract visible text from an HTML string.

        Strips HTML tags and decodes common HTML entities.

        Args:
            html: Raw HTML string.

        Returns:
            Cleaned text content.
        """
        import re
        # Remove tags
        text = re.sub(r"<[^>]+>", "", html)
        # Decode common entities
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&nbsp;", " ").replace("&quot;", '"')
        return text.strip()


class DialogProxy:
    """Proxy for handling JavaScript dialogs (alert/confirm/prompt).

    Attributes:
        type: Dialog type (``"alert"``, ``"confirm"``, ``"prompt"``,
            ``"beforeunload"``).
        message: Dialog message text.
        default_prompt: Default value for prompt dialogs.
    """

    def __init__(self, cdp: CDPConnection, params: dict):
        self._cdp = cdp
        self.type = params.get("type", "")  # alert, confirm, prompt, beforeunload
        self.message = params.get("message", "")
        self.default_prompt = params.get("defaultPrompt", "")

    async def accept(self, prompt_text: str = None):
        """Accept the dialog.

        Args:
            prompt_text: Optional text to enter in prompt dialogs.
        """
        params = {"accept": True}
        if prompt_text is not None:
            params["promptText"] = prompt_text
        await self._cdp.send("Page.handleJavaScriptDialog", params)

    async def dismiss(self):
        """Dismiss the dialog."""
        await self._cdp.send("Page.handleJavaScriptDialog", {"accept": False})
