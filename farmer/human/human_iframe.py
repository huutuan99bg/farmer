"""HumanIframe — Human-like interaction inside iframes.

Elements are found via the iframe's content document (separate DOM tree).
Mouse/keyboard events are dispatched via the parent page's Input domain
because browser input events always fire at the top-level page.

CDP's ``DOM.getBoxModel`` returns page-level coordinates even for iframe
elements, so no manual offset calculation is needed.

Usage:
    >>> iframe_el = await human.locator("iframe#captcha")
    >>> frame_page = await iframe_el.content_frame()
    >>> iframe_human = HumanIframe(human, frame_page)
    >>> await iframe_human.click(".submit-btn")
    >>> await iframe_human.fill("input[name='email']", "user@example.com")
"""

import asyncio
import random
from typing import Optional, Union

from farmer.human.human import Human
from farmer.human.timing import HumanTiming
from farmer.element import Element
from farmer.page.page import Page


class HumanIframe:
    """Human-like behavioral layer for iframe content.

    Locates elements inside the iframe via the iframe's ``Page`` (content
    document), but dispatches all mouse and keyboard input through the
    parent ``Human`` layer so events have correct page-level coordinates
    and ``isTrusted: true``.

    Args:
        parent: The parent ``Human`` instance (controls mouse/keyboard).
        frame_page: The ``Page`` instance for the iframe's content document
            (obtained from ``Element.content_frame()``).

    Example:
        >>> iframe_el = await human.locator("iframe#captcha")
        >>> frame_page = await iframe_el.content_frame()
        >>> iframe_human = HumanIframe(human, frame_page)
        >>> await iframe_human.click("button.verify")
    """

    def __init__(self, parent: Human, frame_page: Page):
        """Initialize HumanIframe.

        Args:
            parent: The parent ``Human`` instance. All mouse movement
                and keyboard input is dispatched through this instance
                so events arrive at page-level with ``isTrusted: true``.
            frame_page: A ``Page`` instance representing the iframe's
                content document. Obtain this via
                ``Element.content_frame()`` on an ``<iframe>`` element.

        Example:
            >>> iframe_el = await human.locator("iframe#captcha")
            >>> frame_page = await iframe_el.content_frame()
            >>> iframe = HumanIframe(human, frame_page)
        """
        self._parent = parent
        self._frame = frame_page
        self._log = parent._log

    # ══════════ Properties ══════════

    @property
    def position(self) -> tuple[float, float]:
        """tuple[float, float]: Current mouse ``(x, y)`` in page coordinates.

        Delegated to the parent ``Human`` instance since the mouse
        is a page-level resource shared across all frames.
        """
        return self._parent.position

    @property
    def parent(self) -> Human:
        """Human: The parent ``Human`` that owns mouse and keyboard."""
        return self._parent

    @property
    def frame(self) -> Page:
        """Page: The iframe's content document for DOM queries."""
        return self._frame

    # ══════════ Locator (iframe DOM) ══════════

    async def locator(
        self,
        selector: str,
        has_text: str = None,
        has_not_text: str = None,
        timeout: float = None,
        visible: bool = True,
        raise_on_fail: bool = True,
    ) -> Optional[Element]:
        """Wait for an element inside the iframe to appear.

        Queries the iframe's content document (not the parent page).
        Actively polls the DOM with randomized intervals until the
        element is found, optionally checking visibility.

        Args:
            selector: CSS selector to search within the iframe DOM.
            has_text: Only match if element contains this text.
            has_not_text: Exclude elements containing this text.
            timeout: Maximum wait time in seconds. Defaults to
                parent's ``_default_timeout`` (typically 10s).
            visible: If ``True``, waits for non-zero bounding box
                (element must be rendered on screen).
            raise_on_fail: If ``True``, raises ``TimeoutError``.
                If ``False``, returns ``None`` on timeout.

        Returns:
            ``Element`` instance within the iframe, or ``None``
            if ``raise_on_fail`` is ``False`` and element not found.

        Raises:
            TimeoutError: If element not found within timeout and
                ``raise_on_fail`` is ``True``.

        Example:
            >>> btn = await iframe.locator("button.verify")
            >>> await btn.click()
        """
        _timeout = timeout or self._parent._default_timeout
        deadline = asyncio.get_event_loop().time() + _timeout

        while asyncio.get_event_loop().time() < deadline:
            el = Element(self._frame, selector)
            try:
                nid = await self._frame._query_selector_id(selector)
                if not nid:
                    await asyncio.sleep(random.uniform(0.2, 0.5))
                    continue

                el._node_id = nid

                if has_text or has_not_text:
                    text = await el.inner_text()
                    if has_text and has_text not in text:
                        await asyncio.sleep(random.uniform(0.2, 0.5))
                        continue
                    if has_not_text and has_not_text in text:
                        await asyncio.sleep(random.uniform(0.2, 0.5))
                        continue

                if visible:
                    box = await el.bounding_box()
                    if not box or box["width"] <= 0 or box["height"] <= 0:
                        await asyncio.sleep(random.uniform(0.2, 0.5))
                        continue

                return el
            except Exception:
                await asyncio.sleep(random.uniform(0.2, 0.5))

        if raise_on_fail:
            raise TimeoutError(f"Timeout {_timeout}s waiting for iframe element: {selector}")
        return None

    async def locator_any(
        self,
        selectors: list[str],
        has_text: str = None,
        has_not_text: str = None,
        timeout: float = None,
        visible: bool = True,
        raise_on_fail: bool = True,
    ) -> Optional[tuple[str, Element]]:
        """Wait for ANY of multiple selectors inside the iframe.

        Returns whichever selector matches first. Useful for
        branching logic (e.g., challenge image OR success message).

        Args:
            selectors: List of CSS selectors to race.
            has_text: Only match if element contains this text.
            has_not_text: Exclude elements containing this text.
            timeout: Maximum wait time in seconds.
            visible: If ``True``, requires non-zero bounding box.
            raise_on_fail: If ``True``, raises on timeout.

        Returns:
            Tuple of ``(matched_selector, Element)``, or ``None``
            if ``raise_on_fail`` is ``False`` and nothing matched.

        Raises:
            TimeoutError: If no selector matches within timeout.

        Example:
            >>> result = await iframe.locator_any(["#success", "#error"])
            >>> if result:
            ...     selector, el = result
        """
        _timeout = timeout or self._parent._default_timeout
        deadline = asyncio.get_event_loop().time() + _timeout

        while asyncio.get_event_loop().time() < deadline:
            for sel in selectors:
                try:
                    nid = await self._frame._query_selector_id(sel)
                    if not nid:
                        continue

                    el = Element(self._frame, sel, node_id=nid)

                    if has_text or has_not_text:
                        text = await el.inner_text()
                        if has_text and has_text not in text:
                            continue
                        if has_not_text and has_not_text in text:
                            continue

                    if visible:
                        box = await el.bounding_box()
                        if not box or box["width"] <= 0:
                            continue

                    return (sel, el)
                except Exception:
                    continue
            await asyncio.sleep(random.uniform(0.2, 0.5))

        if raise_on_fail:
            raise TimeoutError(f"Timeout {_timeout}s waiting for any iframe element: {selectors}")
        return None

    # ══════════ Target Resolution ══════════

    async def _resolve_target(
        self,
        target: Union[str, Element, tuple],
        timeout: float = None,
        raise_on_fail: bool = True,
    ) -> tuple[Optional[Element], Optional[dict]]:
        """Resolve a target to an Element and its bounding box.

        Handles three target types:
        - **str**: CSS selector → waits via ``locator()``.
        - **Element**: Uses directly → gets bounding box.
        - **tuple**: ``(x, y)`` coordinates → returns synthetic box.

        Args:
            target: CSS selector string (auto-waits via ``locator()``),
                ``Element`` instance, or ``(x, y)`` coordinate tuple.
            timeout: Wait timeout for selector targets.
            raise_on_fail: Raise on resolution failure.

        Returns:
            Tuple of ``(Element, bounding_box_dict)``. For ``(x, y)``
            targets, Element is ``None``.

        Raises:
            RuntimeError: If element has no bounding box.
            ValueError: If target type is not recognized.
        """
        if isinstance(target, tuple):
            x, y = target
            return None, {"x": x, "y": y, "width": 0, "height": 0, "center_x": x, "center_y": y}

        if isinstance(target, str):
            el = await self.locator(target, timeout=timeout, raise_on_fail=raise_on_fail)
            if el is None:
                return None, None
            target = el

        if isinstance(target, Element):
            box = await target.bounding_box()
            if not box and raise_on_fail:
                raise RuntimeError(f"Iframe element has no bounding box: {target}")
            return target, box

        raise ValueError(f"Invalid target type: {type(target)}")

    # ══════════ Mouse Movement ══════════

    async def move(
        self,
        x: float, y: float,
        steps: int = None,
        duration: float = None,
        jitter: float = 1.5,
    ):
        """Move mouse via Bezier curve to page-level coordinates.

        Fully delegated to the parent ``Human.move()`` — same
        Bezier path generation, ease-in-out velocity, and position
        tracking.

        Args:
            x: Target X coordinate in page-level CSS pixels.
            y: Target Y coordinate in page-level CSS pixels.
            steps: Bezier interpolation steps. ``None`` = auto.
            duration: Movement duration in seconds. ``None`` = auto.
            jitter: Gaussian noise intensity along the path.
        """
        await self._parent.move(x, y, steps=steps, duration=duration, jitter=jitter)

    async def move_to_element(
        self,
        target: Union[str, Element],
        offset: tuple = None,
        absolute: tuple = None,
        ensure_visible: bool = True,
        steps: int = None,
        duration: float = None,
        jitter: float = 1.5,
        margin: int = 50,
        timeout: float = 10,
        raise_on_fail: bool = True,
    ) -> Optional[Element]:
        """Move mouse to an element inside the iframe via Bezier curve.

        Resolves the element in the iframe's content document, gets
        its page-level bounding box (CDP returns page coords for
        iframe elements automatically), then moves the mouse via
        the parent Human's Bezier path engine.

        Includes a 12% chance of overshoot + correction to mimic
        natural hand movement imprecision.

        Args:
            target: CSS selector or ``Element`` within the iframe.
            offset: Relative offset ``(ox, oy)`` as fractions (0-1)
                within the element box. ``None`` = random (0.35-0.65).
            absolute: Absolute pixel offset ``(px, py)`` from element
                origin. Takes precedence over ``offset``.
            ensure_visible: Scroll element into viewport first.
            steps: Bezier interpolation steps. ``None`` = auto.
            duration: Movement duration in seconds. ``None`` = auto.
            jitter: Path noise intensity.
            margin: Viewport margin in pixels for scroll check.
            timeout: Element wait timeout in seconds.
            raise_on_fail: Raise on element not found.

        Returns:
            Resolved ``Element``, or ``None`` if not found and
            ``raise_on_fail`` is ``False``.
        """
        el, box = await self._resolve_target(target, timeout, raise_on_fail)
        if not box:
            return None

        if ensure_visible and el:
            try:
                await el.scroll_into_view_if_needed()
                box = await el.bounding_box()
                if not box:
                    return None
            except Exception:
                pass

        tx, ty = self._parent._pick_point_in_box(box, offset, absolute)
        await self._parent.move(tx, ty, steps=steps, duration=duration, jitter=jitter)

        # Overshoot + correction: 12% chance
        if random.random() < 0.12:
            ox = tx + random.uniform(-12, 12)
            oy = ty + random.uniform(-6, 6)
            await self._parent.move(ox, oy, steps=random.randint(2, 4), jitter=0.5)
            await asyncio.sleep(random.uniform(0.04, 0.12))
            await self._parent.move(tx, ty, steps=random.randint(2, 3), jitter=0.3)

        return el

    # ══════════ Click ══════════

    async def click(
        self,
        target: Union[str, Element, tuple],
        offset: tuple = None,
        absolute: tuple = None,
        button: str = "left",
        hold: float = None,
        ensure_visible: bool = True,
        steps: int = None,
        duration: float = None,
        jitter: float = 1.5,
        down_up_delay: tuple = (0.05, 0.18),
        pre_move_pause: float = None,
        after_click_pause: tuple = (0.2, 0.5),
        timeout: float = 10,
        raise_on_fail: bool = True,
    ):
        """Full human click on an element inside the iframe.

        Pipeline: Bezier move → micro-jitter at target → mouse
        down/up with Gaussian hold delay. Optional press-and-hold
        mode with hand tremor simulation.

        Args:
            target: CSS selector, ``Element``, or ``(x, y)`` tuple.
            offset: Relative offset ``(ox, oy)`` as fractions (0-1)
                within the element. ``None`` = random (0.35-0.65).
            absolute: Absolute pixel offset from element origin.
            button: Mouse button — ``"left"``, ``"right"``, or
                ``"middle"``.
            hold: Hold duration in milliseconds. If set, performs
                a press-and-hold with hand tremor instead of a
                quick click. Useful for drag-start or long-press.
            ensure_visible: Scroll element into viewport first.
            steps: Bezier interpolation steps. ``None`` = auto.
            duration: Mouse movement duration. ``None`` = auto.
            jitter: Path noise intensity.
            down_up_delay: ``(min, max)`` seconds for button hold
                duration during a normal (non-hold) click.
            pre_move_pause: Optional pause in seconds before
                starting mouse movement.
            after_click_pause: ``(min, max)`` seconds for the
                post-click cooldown pause.
            timeout: Element wait timeout in seconds.
            raise_on_fail: Raise on element not found.

        Example:
            >>> await iframe.click("button.submit")
            >>> await iframe.click(".target", hold=1500)  # long press
        """
        self._log.action("iframe_click", str(target))

        if pre_move_pause:
            await asyncio.sleep(pre_move_pause)

        el, box = await self._resolve_target(target, timeout, raise_on_fail)
        if not box:
            return

        if ensure_visible and el:
            try:
                await el.scroll_into_view_if_needed()
                box = await el.bounding_box()
                if not box:
                    return
            except Exception:
                pass

        tx, ty = self._parent._pick_point_in_box(box, offset, absolute)
        await self._parent.move(tx, ty, steps=steps, duration=duration, jitter=jitter)

        # Micro-jitter at target
        for _ in range(random.randint(1, 3)):
            jx = tx + random.gauss(0, 1.5)
            jy = ty + random.gauss(0, 1.5)
            await self._parent._mouse.move(jx, jy)
            self._parent._pos = (jx, jy)
            await asyncio.sleep(random.uniform(0.01, 0.03))

        # Final position
        await self._parent._mouse.move(tx, ty)
        self._parent._pos = (tx, ty)

        if hold:
            await self._parent._mouse.down(button)
            elapsed = 0
            hold_s = hold / 1000.0
            while elapsed < hold_s:
                tremor_delay = random.uniform(0.1, 0.3)
                await asyncio.sleep(tremor_delay)
                elapsed += tremor_delay
                jx = tx + random.gauss(0, 0.5)
                jy = ty + random.gauss(0, 0.5)
                await self._parent._mouse.move(jx, jy)
            await self._parent._mouse.move(tx, ty)
            await self._parent._mouse.up(button)
        else:
            await self._parent._mouse.down(button)
            await asyncio.sleep(HumanTiming.delay(*down_up_delay))
            await self._parent._mouse.up(button)

        await asyncio.sleep(HumanTiming.delay(*after_click_pause))

    async def double_click(self, target: Union[str, Element, tuple], **kwargs):
        """Double-click with human-like inter-click delay (80-150ms).

        Args:
            target: CSS selector, ``Element``, or ``(x, y)`` tuple.
            **kwargs: Additional args passed to ``click()``.
        """
        kwargs.setdefault("after_click_pause", (0.0, 0.02))
        await self.click(target, **kwargs)
        await asyncio.sleep(HumanTiming.delay(0.08, 0.15))
        await self._parent._mouse.down()
        await asyncio.sleep(HumanTiming.click_hold())
        await self._parent._mouse.up()
        await asyncio.sleep(HumanTiming.delay(0.2, 0.4))

    async def right_click(self, target: Union[str, Element, tuple], **kwargs):
        """Right-click on a target inside the iframe.

        Args:
            target: CSS selector, ``Element``, or ``(x, y)`` tuple.
            **kwargs: Additional args passed to ``click()``.
        """
        kwargs["button"] = "right"
        await self.click(target, **kwargs)

    # ══════════ Keyboard ══════════

    async def type(
        self,
        text: str,
        wpm: float = 200,
        typo_rate: float = 0.02,
        burst_rate: float = 0.12,
    ):
        """Type text with human-like timing.

        Fully delegated to parent ``Human.type()`` — includes
        per-character Gaussian timing, burst patterns (2-4 chars
        typed rapidly), and rare typo simulation.

        Args:
            text: Text to type.
            wpm: Target words per minute (controls base delay).
            typo_rate: Probability of a typo per character (0.0-1.0).
                Typo = wrong char → pause → backspace → correct char.
            burst_rate: Probability of burst typing per character
                (0.0-1.0). Burst = 2-4 chars typed with minimal delay.
        """
        await self._parent.type(text, wpm=wpm, typo_rate=typo_rate, burst_rate=burst_rate)

    async def press(self, key: str, modifiers: list[str] = None):
        """Press a key with human-like hold delay (50-120ms).

        Delegated to parent ``Human.press()``. Modifier keys are
        held down during the press if specified.

        Args:
            key: Key name (e.g., ``"Enter"``, ``"Tab"``,
                ``"Backspace"``, ``"ArrowDown"``).
            modifiers: Optional modifier keys held during the press
                (e.g., ``["Control"]``, ``["Shift", "Control"]``).

        Example:
            >>> await iframe.press("Enter")
            >>> await iframe.press("a", modifiers=["Control"])  # Ctrl+A
        """
        await self._parent.press(key, modifiers=modifiers)

    async def hotkey(self, *keys: str):
        """Press a key combination (down all → up all in reverse).

        Delegated to parent ``Human.hotkey()``.

        Args:
            *keys: Key names in press order.

        Example:
            >>> await iframe.hotkey("Control", "a")  # Select all
            >>> await iframe.hotkey("Control", "c")  # Copy
        """
        await self._parent.hotkey(*keys)

    async def fill(
        self,
        target: Union[str, Element],
        text: str,
        clear_first: bool = True,
        typing_delay: tuple = (0.12, 0.25),
        offset: tuple = None,
        ensure_visible: bool = True,
        timeout: float = None,
        raise_on_fail: bool = True,
        **type_kwargs,
    ):
        """Full human fill: click input → clear → type text.

        Pipeline: human click to focus the input → Ctrl+A → Backspace
        to clear existing content → human-like typing with the parent
        ``Human.type()`` engine.

        Args:
            target: CSS selector or ``Element`` inside the iframe.
            text: Text to type into the input.
            clear_first: If ``True``, selects all and deletes before
                typing. Set to ``False`` to append to existing content.
            typing_delay: Unused (kept for API compatibility with
                ``HuMouseIframeAsync``).
            offset: Click offset within the input element.
            ensure_visible: Scroll into viewport before clicking.
            timeout: Element wait timeout in seconds.
            raise_on_fail: Raise on element not found.
            **type_kwargs: Additional keyword args passed to
                ``Human.type()`` (e.g., ``wpm``, ``typo_rate``).

        Example:
            >>> await iframe.fill("input[name='code']", "ABC123")
            >>> await iframe.fill("#search", "query", clear_first=False)
        """
        self._log.action("iframe_fill", str(target), text_len=len(text))

        await self.click(
            target, offset=offset, ensure_visible=ensure_visible,
            timeout=timeout or self._parent._default_timeout,
            raise_on_fail=raise_on_fail,
        )

        if clear_first:
            await self._parent.hotkey("Control", "a")
            await asyncio.sleep(HumanTiming.delay(0.05, 0.1))
            await self._parent._keyboard.press("Backspace")
            await asyncio.sleep(HumanTiming.delay(0.08, 0.15))

        await self._parent.type(text, **type_kwargs)

    # ══════════ Drag ══════════

    async def drag(
        self,
        from_target: Union[str, Element, tuple],
        to_target: Union[str, Element, tuple],
        steps: int = None,
        duration: float = None,
    ):
        """Drag from one iframe element to another via Bezier curve.

        Resolves both source and destination in the iframe DOM,
        then performs: move to source → mouse down → Bezier drag
        to destination → mouse up.

        Args:
            from_target: Source CSS selector, ``Element``, or
                ``(x, y)`` coordinate tuple.
            to_target: Destination CSS selector, ``Element``, or
                ``(x, y)`` coordinate tuple.
            steps: Bezier interpolation steps for the drag path.
                ``None`` = auto based on distance.
            duration: Drag movement duration in seconds.
                ``None`` = auto.

        Raises:
            RuntimeError: If source or target element not found.

        Example:
            >>> await iframe.drag(".slider-handle", ".slider-end")
            >>> await iframe.drag((100, 200), (300, 200))  # by coords
        """
        _, from_box = await self._resolve_target(from_target)
        _, to_box = await self._resolve_target(to_target)
        if not from_box or not to_box:
            raise RuntimeError("Drag source or target not found in iframe")

        fx, fy = self._parent._pick_point_in_box(from_box)
        tx, ty = self._parent._pick_point_in_box(to_box)

        await self._parent.move(fx, fy, jitter=1.0)
        await asyncio.sleep(HumanTiming.delay(0.05, 0.15))
        await self._parent._mouse.down()
        await asyncio.sleep(HumanTiming.delay(0.1, 0.2))
        await self._parent.move(tx, ty, steps=steps, duration=duration, jitter=0.8)
        await asyncio.sleep(HumanTiming.delay(0.05, 0.1))
        await self._parent._mouse.up()

    # ══════════ Hover ══════════

    async def hover(self, target: Union[str, Element, tuple], duration: float = None):
        """Move to an element in the iframe and optionally hover.

        Uses Bezier curve movement via ``move_to_element()``,
        then holds position for the specified duration.

        Args:
            target: CSS selector, ``Element``, or ``(x, y)`` tuple.
            duration: Optional hover duration in seconds. If ``None``,
                moves to the element without pausing.

        Example:
            >>> await iframe.hover(".tooltip-trigger", duration=1.5)
        """
        await self.move_to_element(target)
        if duration:
            await asyncio.sleep(duration)

    # ══════════ Scroll ══════════

    async def scroll(self, delta_y: float, delta_x: float = 0):
        """Scroll with human-like step sizes and momentum.

        Delegated to parent ``Human.scroll()`` which breaks the
        scroll into randomized steps with inter-step delays.

        Args:
            delta_y: Vertical scroll in pixels (positive = down,
                negative = up).
            delta_x: Horizontal scroll in pixels (positive = right).
        """
        await self._parent.scroll(delta_y, delta_x)

    async def scroll_to_element(self, target: Union[str, Element], margin: int = 100):
        """Scroll until an iframe element is visible in the viewport.

        Resolves the element in the iframe DOM, then uses CDP's
        ``DOM.scrollIntoViewIfNeeded`` to bring it into view.

        Args:
            target: CSS selector or ``Element`` within the iframe.
            margin: Viewport margin in pixels (reserved for future
                human-like wheel scrolling implementation).
        """
        el, box = await self._resolve_target(target, raise_on_fail=False)
        if el:
            await el.scroll_into_view_if_needed()

    # ══════════ Query helpers ══════════

    async def query_selector(self, selector: str) -> Optional[Element]:
        """Find the first element matching a CSS selector in the iframe.

        Unlike ``locator()``, this does NOT wait or poll — returns
        immediately with the current DOM state.

        Args:
            selector: CSS selector to search in the iframe DOM.

        Returns:
            ``Element`` instance, or ``None`` if not found.
        """
        return await self._frame.query_selector(selector)

    async def query_selector_all(self, selector: str) -> list[Element]:
        """Find all elements matching a CSS selector in the iframe.

        Unlike ``locator()``, this does NOT wait or poll — returns
        immediately with the current DOM state.

        Args:
            selector: CSS selector to search in the iframe DOM.

        Returns:
            List of ``Element`` instances (may be empty).
        """
        return await self._frame.query_selector_all(selector)

    async def inner_text(self, selector: str) -> str:
        """Get the visible text of an element inside the iframe.

        Args:
            selector: CSS selector for the target element.

        Returns:
            Extracted text with HTML tags stripped, or empty string
            if the element is not found.
        """
        return await self._frame.inner_text(selector)

    async def get_attribute(self, selector: str, attr: str) -> Optional[str]:
        """Get an HTML attribute value from an iframe element.

        Args:
            selector: CSS selector for the target element.
            attr: Attribute name (e.g., ``"href"``, ``"class"``,
                ``"data-sitekey"``).

        Returns:
            Attribute value string, or ``None`` if the attribute
            is not present or the element is not found.

        Example:
            >>> key = await iframe.get_attribute(".h-captcha", "data-sitekey")
        """
        return await self._frame.get_attribute(selector, attr)

    def __repr__(self) -> str:
        """Return a developer-friendly string representation."""
        return f"HumanIframe(frame_id={self._frame._frame_id!r})"
