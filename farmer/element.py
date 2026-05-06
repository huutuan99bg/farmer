"""Element — Playwright-style Locator for CDP.

Lazy evaluation: DOM queries execute only when an action is performed.
Automatically re-queries on stale ``nodeId``.

Example:
    >>> el = page.locator("h1")
    >>> text = await el.inner_text()
    >>> await el.click()
"""

import asyncio
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from farmer.page.page import Page


class Element:
    """Represents a DOM element with lazy resolution.

    Mirrors Playwright's ``Locator`` API. The element is not queried
    from the DOM until an action method is called, and automatically
    re-queries if the stored ``nodeId`` becomes stale (e.g., after
    navigation or DOM mutation).

    Example:
        >>> el = page.locator("#submit-btn")
        >>> if await el.is_visible():
        ...     await el.click()
    """

    def __init__(self, page: "Page", selector: str, node_id: int = None):
        """Initialize an Element.

        Args:
            page: The Page instance that owns this element.
            selector: CSS selector used to locate this element.
            node_id: Pre-resolved DOM node ID. If ``None``, the
                element will be queried lazily on first use.
        """
        self._page = page
        self._selector = selector
        self._node_id = node_id

    # ── Internal: resolve node ──

    async def _resolve(self) -> int:
        """Get or refresh the DOM node ID.

        Verifies the cached ``nodeId`` is still valid via
        ``DOM.describeNode``. If stale, re-queries the DOM using
        the stored selector.

        Returns:
            Valid DOM node ID.

        Raises:
            RuntimeError: If the element cannot be found in the DOM.
        """
        if self._node_id:
            # Verify node is still valid
            try:
                await self._page._cdp.send("DOM.describeNode", {"nodeId": self._node_id, "depth": 0})
                return self._node_id
            except Exception:
                self._node_id = None

        # Re-query
        nid = await self._page._query_selector_id(self._selector)
        if not nid:
            raise RuntimeError(f"Element not found: {self._selector}")
        self._node_id = nid
        return nid

    async def _resolve_or_none(self) -> Optional[int]:
        """Get node ID or return ``None`` if not found.

        Returns:
            DOM node ID, or ``None``.
        """
        try:
            return await self._resolve()
        except RuntimeError:
            return None

    # ── Query (scoped) ──

    def locator(self, selector: str) -> "Element":
        """Create a scoped child locator by combining selectors.

        Args:
            selector: CSS selector relative to this element.

        Returns:
            New ``Element`` with combined selector.

        Example:
            >>> form = page.locator("form.login")
            >>> email = form.locator("input[name='email']")
        """
        combined = f"{self._selector} {selector}"
        return Element(self._page, combined)

    def first(self) -> "Element":
        """Return the first matching element (equivalent to ``nth(0)``).

        Returns:
            New ``Element`` targeting ``:first-of-type``.
        """
        return Element(self._page, f"{self._selector}:first-of-type", self._node_id)

    def last(self) -> "Element":
        """Return the last matching element.

        Returns:
            New ``Element`` targeting ``:last-of-type``.
        """
        return Element(self._page, f"{self._selector}:last-of-type")

    def nth(self, index: int) -> "Element":
        """Return the nth matching element (0-based index).

        Args:
            index: Zero-based element index.

        Returns:
            New ``Element`` targeting ``:nth-of-type(index+1)``.

        Example:
            >>> third_item = page.locator("li").nth(2)
        """
        return Element(self._page, f"{self._selector}:nth-of-type({index + 1})")

    async def count(self) -> int:
        """Count all elements matching the selector.

        Returns:
            Number of matching DOM nodes.
        """
        nids = await self._page._query_selector_all_ids(self._selector)
        return len(nids)

    # ── State ──

    async def is_visible(self) -> bool:
        """Check if the element is visible (has non-zero bounding box).

        Returns:
            ``True`` if element exists and has ``width > 0`` and
            ``height > 0``.
        """
        box = await self.bounding_box()
        return box is not None and box["width"] > 0 and box["height"] > 0

    async def is_enabled(self) -> bool:
        """Check if the element is enabled (no ``disabled`` attribute).

        Returns:
            ``True`` if element exists and is not disabled.
        """
        nid = await self._resolve_or_none()
        if not nid:
            return False
        attrs = await self._page._get_attributes(nid)
        return "disabled" not in attrs

    async def is_checked(self) -> bool:
        """Check if a checkbox or radio input is checked.

        Returns:
            ``True`` if the ``checked`` attribute is present.
        """
        nid = await self._resolve_or_none()
        if not nid:
            return False
        attrs = await self._page._get_attributes(nid)
        return "checked" in attrs

    # ── Content ──

    async def inner_text(self) -> str:
        """Get the visible text content of the element.

        Returns:
            Extracted text with HTML tags stripped.

        Raises:
            RuntimeError: If element not found.
        """
        nid = await self._resolve()
        html = await self._page._get_outer_html(nid)
        return self._page._extract_text(html)

    async def inner_html(self) -> str:
        """Get the inner HTML of the element.

        Returns:
            HTML string between the opening and closing tags.

        Raises:
            RuntimeError: If element not found.
        """
        nid = await self._resolve()
        html = await self._page._get_outer_html(nid)
        start = html.find(">") + 1
        end = html.rfind("<")
        return html[start:end] if start > 0 and end > start else html

    async def text_content(self) -> str:
        """Get text content (alias for ``inner_text()``).

        Returns:
            Extracted text.
        """
        return await self.inner_text()

    async def get_attribute(self, name: str) -> Optional[str]:
        """Get the value of an HTML attribute.

        Args:
            name: Attribute name (e.g., ``"href"``, ``"class"``).

        Returns:
            Attribute value, or ``None`` if not present.

        Raises:
            RuntimeError: If element not found.

        Example:
            >>> href = await el.get_attribute("href")
        """
        nid = await self._resolve()
        attrs = await self._page._get_attributes(nid)
        return attrs.get(name)

    async def bounding_box(self) -> Optional[dict]:
        """Get the element's bounding box in viewport coordinates.

        Returns:
            Dict with keys ``x``, ``y``, ``width``, ``height``,
            ``center_x``, ``center_y``. Returns ``None`` if element
            is not found or not rendered.
        """
        nid = await self._resolve_or_none()
        if not nid:
            return None
        return await self._page._get_box_model(nid)

    # ── Actions ──

    async def click(self, **kwargs):
        """Click the element center using raw mouse dispatch.

        Raises:
            RuntimeError: If element not found or has no bounding box.
        """
        box = await self.bounding_box()
        if not box:
            raise RuntimeError(f"Cannot click — element not found: {self._selector}")
        await self._page.mouse.click(box["center_x"], box["center_y"])

    async def dblclick(self, **kwargs):
        """Double-click the element center.

        Raises:
            RuntimeError: If element not found.
        """
        box = await self.bounding_box()
        if not box:
            raise RuntimeError(f"Cannot dblclick — element not found: {self._selector}")
        await self._page.mouse.dblclick(box["center_x"], box["center_y"])

    async def fill(self, value: str):
        """Clear and type text into the element (focus -> select all -> type).

        Uses ``DOM.focus`` followed by Ctrl+A, Backspace, then
        character-by-character typing. For stealth, use ``Human.fill()``
        instead.

        Args:
            value: Text to type into the element.

        Raises:
            RuntimeError: If element not found.
        """
        await self.focus()
        await self._page.keyboard.down("Control")
        await self._page.keyboard.press("a")
        await self._page.keyboard.up("Control")
        await self._page.keyboard.press("Backspace")
        await self._page.keyboard.type(value)

    async def type(self, text: str, delay: float = 0):
        """Type text into the focused element character by character.

        Args:
            text: String to type.
            delay: Seconds between each character.

        Raises:
            RuntimeError: If element not found.
        """
        await self.focus()
        await self._page.keyboard.type(text, delay=delay)

    async def press(self, key: str):
        """Press a key while the element is focused.

        Args:
            key: Key name (e.g., ``"Enter"``, ``"Tab"``).

        Raises:
            RuntimeError: If element not found.
        """
        await self.focus()
        await self._page.keyboard.press(key)

    async def check(self):
        """Check a checkbox if not already checked."""
        if not await self.is_checked():
            await self.click()

    async def uncheck(self):
        """Uncheck a checkbox if currently checked."""
        if await self.is_checked():
            await self.click()

    async def select_option(self, value: str):
        """Select an ``<option>`` by value or visible text.

        Searches for an ``<option>`` with a matching ``value``
        attribute first, then falls back to matching by text content.

        Args:
            value: The option ``value`` attribute or visible text.

        Raises:
            RuntimeError: If no matching option is found.
        """
        nid = await self._resolve()
        options = await self._page._query_selector_all_ids(
            f"{self._selector} option[value='{value}']"
        )
        if not options:
            options = await self._page._query_selector_all_ids(f"{self._selector} option")
            for opt_id in options:
                html = await self._page._get_outer_html(opt_id)
                text = self._page._extract_text(html)
                if text.strip() == value:
                    box = await self._page._get_box_model(opt_id)
                    if box:
                        await self._page.mouse.click(box["center_x"], box["center_y"])
                        return
            raise RuntimeError(f"Option not found: {value}")
        else:
            box = await self._page._get_box_model(options[0])
            if box:
                await self.click()
                await asyncio.sleep(0.1)
                await self._page.mouse.click(box["center_x"], box["center_y"])

    async def set_input_files(self, files):
        """Upload files to a ``<input type="file">`` element.

        Args:
            files: Single file path string or list of file path strings.

        Raises:
            RuntimeError: If element not found.

        Example:
            >>> await el.set_input_files("/path/to/photo.jpg")
            >>> await el.set_input_files(["/a.jpg", "/b.png"])
        """
        if isinstance(files, str):
            files = [files]
        nid = await self._resolve()
        await self._page._cdp.send("DOM.setFileInputFiles", {
            "nodeId": nid, "files": files,
        })

    async def focus(self):
        """Focus the element via ``DOM.focus``.

        Raises:
            RuntimeError: If element not found.
        """
        nid = await self._resolve()
        await self._page._cdp.send("DOM.focus", {"nodeId": nid})

    async def scroll_into_view_if_needed(self):
        """Scroll the element into the viewport via CDP (instant, no animation).

        Warning:
            This uses ``DOM.scrollIntoViewIfNeeded`` which scrolls
            instantly. For stealth, use ``Human._human_scroll_into_view()``
            which simulates wheel-based scrolling.

        Raises:
            RuntimeError: If element not found.
        """
        nid = await self._resolve()
        await self._page._cdp.send("DOM.scrollIntoViewIfNeeded", {"nodeId": nid})

    async def screenshot(self, path: str = None) -> bytes:
        """Capture a screenshot of this element only.

        Args:
            path: Optional file path to save the PNG image.

        Returns:
            PNG image data as bytes.

        Raises:
            RuntimeError: If element not found or has no bounding box.
        """
        box = await self.bounding_box()
        if not box:
            raise RuntimeError(f"Cannot screenshot — element not found: {self._selector}")
        return await self._page.screenshot(
            path=path,
            clip={"x": box["x"], "y": box["y"], "width": box["width"], "height": box["height"]},
        )

    # ── Wait ──

    async def wait_for(self, state: str = "visible", timeout: float = 30):
        """Wait for this element to reach a specific state.

        Args:
            state: Target state — ``"visible"``, ``"hidden"``,
                ``"attached"``, or ``"detached"``.
            timeout: Maximum seconds to wait.

        Raises:
            TimeoutError: If state not reached within timeout.
        """
        await self._page.wait_for_selector(self._selector, state=state, timeout=timeout)

    # ── Frame ──

    async def content_frame(self) -> "Optional[Page]":
        """If this element is an ``<iframe>``, return a Page for its content.

        Returns:
            A ``Page`` instance connected to the iframe's document,
            or ``None`` if this is not an iframe or the content
            document is inaccessible.
        """
        nid = await self._resolve()
        try:
            desc = await self._page._cdp.send("DOM.describeNode", {
                "nodeId": nid, "depth": 1,
            })
            content_doc = desc.get("node", {}).get("contentDocument")
            if content_doc:
                from farmer.page.page import Page
                frame_page = Page(self._page._cdp, log=self._page._log)
                frame_page._frame_id = desc.get("node", {}).get("frameId", "")
                frame_page._root_node_id = content_doc["nodeId"]
                return frame_page
        except Exception:
            pass
        return None

    def __repr__(self):
        return f"Element({self._selector!r})"
