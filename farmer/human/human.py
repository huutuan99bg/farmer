"""Human — behavioral simulation layer extending Page.

Every interaction is human-like: Bezier mouse paths, random click
offsets, Gaussian timing, typo simulation, and position memory.
Use this layer instead of Page for stealth-critical operations.

Example:
    >>> human = Human(cdp, viewport=(1920, 1080))
    >>> await human._init_page()
    >>> await human.click("#submit")
    >>> await human.fill("#email", "user@example.com")
"""

import asyncio
import math
import random
from typing import Optional, Union, TYPE_CHECKING


from farmer.page.page import Page
from farmer.core.connection import CDPConnection
from farmer.core.logger import FarmerLogger
from farmer.human.curves import BezierPath
from farmer.human.timing import HumanTiming
from farmer.element import Element


class Human(Page):
    """Behavioral simulation layer extending ``Page``.

    Every interaction uses Bezier curve mouse paths, random click
    offsets within elements, Gaussian-distributed timing delays,
    and optional typo simulation. Maintains mouse position memory.
    """

    def __init__(
        self,
        cdp: CDPConnection,
        viewport: tuple[int, int] = (1280, 720),
        log: FarmerLogger = None,
        **kwargs,
    ):
        """Initialize Human layer.

        Args:
            cdp: Active CDP connection.
            viewport: Browser viewport size ``(width, height)``.
            log: Structured logger instance.
            **kwargs: Additional args passed to ``Page.__init__()``.
        """
        super().__init__(cdp, log=log, **kwargs)
        # Initialize mouse at random position within viewport
        self._pos = (
            random.uniform(100, viewport[0] - 100),
            random.uniform(100, viewport[1] - 100),
        )
        self._viewport = {"width": viewport[0], "height": viewport[1]}
        self._default_timeout = 10.0

    # ══════════ Position Memory ══════════

    @property
    def position(self) -> tuple[float, float]:
        """Current mouse position (x, y) — always tracked."""
        return self._pos

    def set_position(self, x: float, y: float):
        """Set internal position without dispatching mouse events.

        Args:
            x: X coordinate.
            y: Y coordinate.
        """
        self._pos = (x, y)

    # ══════════ Target Resolution ══════════

    async def _resolve_target(
        self,
        target: Union[str, Element, tuple],
        timeout: float = None,
        raise_on_fail: bool = True,
    ) -> tuple[Optional[Element], Optional[dict]]:
        """Resolve a target to an Element and its bounding box.

        Args:
            target: CSS selector string (auto-waits), ``Element``
                instance, or ``(x, y)`` tuple.
            timeout: Wait timeout for selector targets.
            raise_on_fail: Raise on resolution failure.

        Returns:
            Tuple of ``(Element, bounding_box_dict)``. For
            ``(x, y)`` targets, Element is ``None``.

        Raises:
            RuntimeError: If element has no bounding box.
            ValueError: If target type is invalid.
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
                raise RuntimeError(f"Element has no bounding box: {target}")
            return target, box

        raise ValueError(f"Invalid target type: {type(target)}")

    def _pick_point_in_box(self, box: dict, offset: tuple = None, absolute: tuple = None) -> tuple[float, float]:
        """Pick a click point within an element's bounding box.

        Args:
            box: Bounding box dict from ``Element.bounding_box()``.
            offset: Relative offset ``(ox, oy)`` as fractions (0-1).
            absolute: Absolute pixel offset ``(px, py)`` from box origin.

        Returns:
            Tuple of ``(x, y)`` coordinates.
        """
        if absolute:
            return box["x"] + absolute[0], box["y"] + absolute[1]

        if offset:
            ox, oy = offset
        else:
            # Random offset within (0.35-0.65) of box — NOT center
            ox = random.uniform(0.35, 0.65)
            oy = random.uniform(0.35, 0.65)

        return box["x"] + box["width"] * ox, box["y"] + box["height"] * oy

    # ══════════ Locator (auto-wait) ══════════

    async def locator(
        self,
        selector: str,
        has_text: str = None,
        has_not_text: str = None,
        timeout: float = None,
        visible: bool = True,
        raise_on_fail: bool = True,
    ) -> Optional[Element]:
        """Wait for an element to appear and become visible.

        Unlike ``Page.locator()`` which is lazy, this method
        actively polls the DOM with randomized intervals.

        Args:
            selector: CSS selector.
            has_text: Only match if element contains this text.
            has_not_text: Only match if element does NOT contain this.
            timeout: Maximum wait time in seconds.
            visible: If ``True``, waits for non-zero bounding box.
            raise_on_fail: Raise ``TimeoutError`` on failure.

        Returns:
            ``Element`` instance, or ``None`` if not found and
            ``raise_on_fail`` is ``False``.

        Raises:
            TimeoutError: If element not found within timeout.
        """
        _timeout = timeout or self._default_timeout
        deadline = asyncio.get_event_loop().time() + _timeout

        while asyncio.get_event_loop().time() < deadline:
            el = Element(self, selector)
            try:
                nid = await self._query_selector_id(selector)
                if not nid:
                    await asyncio.sleep(random.uniform(0.2, 0.5))
                    continue

                el._node_id = nid

                # Filter by text
                if has_text or has_not_text:
                    text = await el.inner_text()
                    if has_text and has_text not in text:
                        await asyncio.sleep(random.uniform(0.2, 0.5))
                        continue
                    if has_not_text and has_not_text in text:
                        await asyncio.sleep(random.uniform(0.2, 0.5))
                        continue

                # Check visibility
                if visible:
                    box = await el.bounding_box()
                    if not box or box["width"] <= 0 or box["height"] <= 0:
                        await asyncio.sleep(random.uniform(0.2, 0.5))
                        continue

                return el
            except Exception:
                await asyncio.sleep(random.uniform(0.2, 0.5))

        if raise_on_fail:
            raise TimeoutError(f"Timeout {_timeout}s waiting for: {selector}")
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
        """Wait for ANY of multiple selectors to match.

        Returns whichever selector matches first. Useful for
        branching logic (e.g., success OR error message).

        Args:
            selectors: List of CSS selectors.
            has_text: Only match if element contains this text.
            has_not_text: Only match if element does NOT contain this.
            timeout: Maximum wait time in seconds.
            visible: If ``True``, requires non-zero bounding box.
            raise_on_fail: Raise on timeout.

        Returns:
            Tuple of ``(matched_selector, Element)``, or ``None``.

        Raises:
            TimeoutError: If no selector matches within timeout.
        """
        _timeout = timeout or self._default_timeout
        deadline = asyncio.get_event_loop().time() + _timeout

        while asyncio.get_event_loop().time() < deadline:
            for sel in selectors:
                try:
                    nid = await self._query_selector_id(sel)
                    if not nid:
                        continue

                    el = Element(self, sel, node_id=nid)

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
            raise TimeoutError(f"Timeout {_timeout}s waiting for any of: {selectors}")
        return None

    # ══════════ Mouse (Human-Like) ══════════

    async def move(
        self,
        x: float, y: float,
        steps: int = None,
        duration: float = None,
        jitter: float = 1.5,
    ):
        """Move mouse via Bezier curve with ease-in-out velocity.

        Never teleports — always smooth movement from current
        position using ``sin(t*pi)`` velocity bell curve.

        Args:
            x: Target X coordinate.
            y: Target Y coordinate.
            steps: Interpolation steps. ``None`` = auto from distance.
            duration: Movement duration in seconds. ``None`` = auto.
            jitter: Gaussian noise intensity along the path.
        """
        self._log.mouse(x, y, "move_start")
        path = BezierPath.generate(
            self._pos, (x, y), steps=steps, jitter=jitter,
        )
        dur = duration or BezierPath.calculate_duration(
            math.hypot(x - self._pos[0], y - self._pos[1])
        )
        total_steps = max(len(path), 1)
        base_delay = dur / total_steps

        for i, (px, py) in enumerate(path):
            await self._mouse.move(px, py)
            self._pos = (px, py)
            # Ease-in-out: slower at start/end, faster in middle
            t = i / total_steps
            ease = math.sin(t * math.pi)  # 0→1→0 bell curve
            # Scale: slow edges (1.8x), fast middle (0.4x)
            factor = 1.8 - 1.4 * ease
            await asyncio.sleep(base_delay * factor * random.uniform(0.85, 1.15))

        self._pos = (x, y)

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
        """Move mouse to an element with Bezier curve.

        Auto-scrolls if the element is outside the viewport.

        Args:
            target: CSS selector or ``Element``.
            offset: Relative offset within element as ``(ox, oy)``.
            absolute: Absolute pixel offset from element origin.
            ensure_visible: Scroll element into view first.
            steps: Bezier interpolation steps.
            duration: Movement duration.
            jitter: Path noise intensity.
            margin: Viewport margin for scroll check.
            timeout: Element wait timeout.
            raise_on_fail: Raise on element not found.

        Returns:
            Resolved ``Element``, or ``None``.
        """
        el, box = await self._resolve_target(target, timeout, raise_on_fail)
        if not box:
            return None

        # Scroll into view if needed
        if ensure_visible and el:
            await el.scroll_into_view_if_needed()
            # Re-get box after scroll
            box = await el.bounding_box()
            if not box:
                return None

        # Pick target point
        tx, ty = self._pick_point_in_box(box, offset, absolute)
        await self.move(tx, ty, steps=steps, duration=duration, jitter=jitter)

        return el

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
        """Full human click with Bezier move, micro-jitter, and pauses.

        Args:
            target: CSS selector, ``Element``, or ``(x, y)`` tuple.
            offset: Relative offset ``(ox, oy)`` within element.
            absolute: Absolute pixel offset from element origin.
            button: Mouse button (``"left"``, ``"right"``, ``"middle"``).
            hold: Hold duration in milliseconds (for press-and-hold).
            ensure_visible: Scroll element into view first.
            steps: Bezier interpolation steps.
            duration: Mouse movement duration.
            jitter: Path noise intensity.
            down_up_delay: Min/max seconds for button hold.
            pre_move_pause: Optional pause before moving.
            after_click_pause: Min/max seconds for post-click pause.
            timeout: Element wait timeout.
            raise_on_fail: Raise on element not found.
        """
        self._log.action("click", str(target))

        if pre_move_pause:
            await asyncio.sleep(pre_move_pause)

        # Resolve target
        el, box = await self._resolve_target(target, timeout, raise_on_fail)
        if not box:
            return

        # Scroll into view using human-like wheel scroll
        if ensure_visible and el:
            await self._human_scroll_into_view(el)
            box = await el.bounding_box()
            if not box:
                return

        # Pick click point
        tx, ty = self._pick_point_in_box(box, offset, absolute)

        # Bézier move
        await self.move(tx, ty, steps=steps, duration=duration, jitter=jitter)

        # Micro-jitter at target: 1-3 tiny moves
        for _ in range(random.randint(1, 3)):
            jx = tx + random.gauss(0, 1.5)
            jy = ty + random.gauss(0, 1.5)
            await self._mouse.move(jx, jy)
            self._pos = (jx, jy)
            await asyncio.sleep(random.uniform(0.01, 0.03))

        # Final position
        await self._mouse.move(tx, ty)
        self._pos = (tx, ty)

        if hold:
            # Press-and-hold with tremor
            await self._mouse.down(button)
            elapsed = 0
            hold_s = hold / 1000.0
            while elapsed < hold_s:
                tremor_delay = random.uniform(0.1, 0.3)
                await asyncio.sleep(tremor_delay)
                elapsed += tremor_delay
                # Hand tremor
                jx = tx + random.gauss(0, 0.5)
                jy = ty + random.gauss(0, 0.5)
                await self._mouse.move(jx, jy)
            await self._mouse.move(tx, ty)
            await self._mouse.up(button)
        else:
            # Normal click
            await self._mouse.down(button)
            await asyncio.sleep(HumanTiming.delay(*down_up_delay))
            await self._mouse.up(button)

        # After-click pause
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
        # Second click at same position
        await self._mouse.down()
        await asyncio.sleep(HumanTiming.click_hold())
        await self._mouse.up()
        await asyncio.sleep(HumanTiming.delay(0.2, 0.4))

    async def right_click(self, target: Union[str, Element, tuple], **kwargs):
        """Right-click on a target.

        Args:
            target: CSS selector, ``Element``, or ``(x, y)`` tuple.
            **kwargs: Additional args passed to ``click()``.
        """
        kwargs["button"] = "right"
        await self.click(target, **kwargs)

    async def drag(
        self,
        from_target: Union[str, Element, tuple],
        to_target: Union[str, Element, tuple],
        steps: int = None,
        duration: float = None,
        **kwargs,
    ):
        """Drag from one target to another via Bezier curve.

        Args:
            from_target: Source CSS selector, Element, or (x, y).
            to_target: Destination CSS selector, Element, or (x, y).
            steps: Bezier interpolation steps.
            duration: Drag movement duration.

        Raises:
            RuntimeError: If source or target not found.
        """
        _, from_box = await self._resolve_target(from_target)
        _, to_box = await self._resolve_target(to_target)
        if not from_box or not to_box:
            raise RuntimeError("Drag source or target not found")

        fx, fy = self._pick_point_in_box(from_box)
        tx, ty = self._pick_point_in_box(to_box)

        await self.move(fx, fy, jitter=1.0)
        await asyncio.sleep(HumanTiming.delay(0.05, 0.15))
        await self._mouse.down()
        await asyncio.sleep(HumanTiming.delay(0.1, 0.2))
        await self.move(tx, ty, steps=steps, duration=duration, jitter=0.8)
        await asyncio.sleep(HumanTiming.delay(0.05, 0.1))
        await self._mouse.up()

    async def hover(
        self, target: Union[str, Element, tuple], duration: float = None
    ):
        """Move to an element and optionally hover for a duration.

        Args:
            target: CSS selector, ``Element``, or ``(x, y)`` tuple.
            duration: Optional hover duration in seconds.
        """
        await self.move_to_element(target)
        if duration:
            await asyncio.sleep(duration)

    # ══════════ Keyboard (Human-Like) ══════════

    async def type(
        self,
        text: str,
        wpm: float = 200,
        typo_rate: float = 0.02,
        burst_rate: float = 0.12,
    ):
        """Type text with human-like timing, typos, and burst patterns.

        Features:
        - Per-character Gaussian timing based on character type.
        - 2% chance of typo (wrong char -> pause -> backspace -> correct).
        - 12% chance of burst (2-4 chars typed rapidly).

        Args:
            text: Text to type.
            wpm: Target words per minute.
            typo_rate: Probability of a typo per character.
            burst_rate: Probability of burst typing per character.
        """
        self._log.action("type", f"({len(text)} chars)")
        i = 0
        while i < len(text):
            char = text[i]

            # Burst: 12% chance to type 2-4 chars rapidly
            if random.random() < burst_rate and i + 2 < len(text):
                burst_len = random.randint(2, min(4, len(text) - i))
                for j in range(burst_len):
                    await self._keyboard.down(text[i + j])
                    await self._keyboard.up(text[i + j])
                    await asyncio.sleep(random.uniform(0.02, 0.05))
                i += burst_len
                continue

            # Typo: 2% chance to type wrong char → pause → backspace → correct
            if random.random() < typo_rate and char.isalpha():
                wrong = chr(ord(char) + random.choice([-1, 1]))
                await self._keyboard.down(wrong)
                await self._keyboard.up(wrong)
                await asyncio.sleep(HumanTiming.delay(0.15, 0.35))
                await self._keyboard.press("Backspace")
                await asyncio.sleep(HumanTiming.delay(0.1, 0.2))

            # Type correct character
            await self._keyboard.down(char)
            await self._keyboard.up(char)

            # Per-character delay
            await asyncio.sleep(HumanTiming.typing_delay(char, wpm))
            i += 1

    async def press(self, key: str, modifiers: list[str] = None):
        """Press a key with human hold delay (50-120ms).

        Args:
            key: Key name (e.g., ``"Enter"``, ``"Tab"``).
            modifiers: Optional modifier keys held during press
                (e.g., ``["Control"]``).
        """
        if modifiers:
            for mod in modifiers:
                await self._keyboard.down(mod)

        await self._keyboard.down(key)
        await asyncio.sleep(HumanTiming.delay(0.05, 0.12))
        await self._keyboard.up(key)

        if modifiers:
            for mod in reversed(modifiers):
                await self._keyboard.up(mod)

    async def hotkey(self, *keys: str):
        """Press a key combination (down all -> up all in reverse).

        Args:
            *keys: Key names in order (e.g., ``"Control"``, ``"a"``).

        Example:
            >>> await human.hotkey("Control", "a")  # Select all
        """
        for key in keys:
            await self._keyboard.down(key)
            await asyncio.sleep(random.uniform(0.02, 0.05))
        for key in reversed(keys):
            await self._keyboard.up(key)
            await asyncio.sleep(random.uniform(0.02, 0.04))

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
        """Full human fill: click input -> clear -> type text.

        Args:
            target: CSS selector or ``Element``.
            text: Text to type.
            clear_first: If ``True``, Ctrl+A -> Backspace before typing.
            typing_delay: Unused (kept for API compat).
            offset: Click offset within element.
            ensure_visible: Scroll into view first.
            timeout: Element wait timeout.
            raise_on_fail: Raise on element not found.
            **type_kwargs: Additional args passed to ``type()``.
        """
        self._log.action("fill", str(target), text_len=len(text))

        # Click the input
        await self.click(
            target, offset=offset, ensure_visible=ensure_visible,
            timeout=timeout or self._default_timeout,
            raise_on_fail=raise_on_fail,
        )

        if clear_first:
            # Select all + delete
            await self.hotkey("Control", "a")
            await asyncio.sleep(HumanTiming.delay(0.05, 0.1))
            await self._keyboard.press("Backspace")
            await asyncio.sleep(HumanTiming.delay(0.08, 0.15))

        # Type text
        await self.type(text, **type_kwargs)

    # ══════════ Scroll (Human-Like) ══════════

    async def scroll(self, delta_y: float, delta_x: float = 0):
        """Scroll with randomized step sizes and momentum.

        Args:
            delta_y: Vertical scroll in pixels (positive = down).
            delta_x: Horizontal scroll in pixels (positive = right).
        """
        # Break into small steps
        step_size = random.randint(120, 260)
        remaining = abs(delta_y)
        direction = 1 if delta_y > 0 else -1

        while remaining > 0:
            step = min(step_size, remaining)
            # Add slight randomness to step
            actual_step = step * random.uniform(0.85, 1.15)
            await self._mouse.wheel(delta_x, actual_step * direction)
            remaining -= step
            await asyncio.sleep(HumanTiming.scroll_step_delay())
            step_size = random.randint(120, 260)

    async def scroll_to_element(self, target: Union[str, Element], margin: int = 100):
        """Scroll until an element is in the viewport.

        Args:
            target: CSS selector or ``Element``.
            margin: Viewport margin in pixels.
        """
        el, box = await self._resolve_target(target, raise_on_fail=False)
        if el:
            await el.scroll_into_view_if_needed()

    async def scroll_to_bottom(self, speed: str = "normal"):
        """Scroll to the bottom of the page gradually.

        Args:
            speed: Scroll speed — ``"slow"``, ``"normal"``, or ``"fast"``.
        """
        step_sizes = {"slow": (80, 160), "normal": (120, 260), "fast": (200, 400)}
        min_step, max_step = step_sizes.get(speed, (120, 260))

        for _ in range(50):  # Safety limit
            await self._mouse.wheel(0, random.randint(min_step, max_step))
            await asyncio.sleep(HumanTiming.scroll_step_delay())

    # ══════════ Behavior ══════════

    async def idle(self, duration: float = 2.0):
        """Simulate idle mouse wandering behavior.

        Makes small random movements (±80px) with Gaussian pauses
        to appear as a naturally idle user.

        Args:
            duration: Total idle time in seconds.
        """
        elapsed = 0
        while elapsed < duration:
            dx = random.gauss(0, 40)
            dy = random.gauss(0, 30)
            new_x = max(10, min(self._pos[0] + dx, self._viewport["width"] - 10))
            new_y = max(10, min(self._pos[1] + dy, self._viewport["height"] - 10))
            await self.move(new_x, new_y, jitter=0.5)
            pause = HumanTiming.delay(0.3, 1.2)
            await asyncio.sleep(pause)
            elapsed += pause

    async def reading_pause(self, text_length: int = 100):
        """Pause proportional to text length (~250 WPM reading speed).

        Args:
            text_length: Number of characters in the text being "read".
        """
        await asyncio.sleep(HumanTiming.reading_time(text_length))

    # ══════════ Internal Helpers ══════════

    async def _human_scroll_into_view(self, el: Element):
        """Scroll element into viewport using wheel events.

        Uses human-like wheel scrolling with momentum instead of
        the instant ``DOM.scrollIntoViewIfNeeded`` CDP command.
        Falls back to CDP scroll if element has no bounding box.

        Args:
            el: Element to scroll into view.
        """
        box = await el.bounding_box()
        if not box:
            # Fallback to CDP scroll (element may be far off-screen)
            await el.scroll_into_view_if_needed()
            return

        vp_h = self._viewport["height"]
        margin = 80

        # Already in viewport?
        if margin < box["center_y"] < vp_h - margin:
            return

        # Calculate scroll direction and distance
        if box["center_y"] > vp_h - margin:
            # Element below viewport → scroll down
            scroll_dist = box["center_y"] - vp_h // 2
        else:
            # Element above viewport → scroll up
            scroll_dist = box["center_y"] - vp_h // 2  # negative

        # Scroll in human-like steps
        remaining = abs(scroll_dist)
        direction = 1 if scroll_dist > 0 else -1
        max_attempts = 15

        for _ in range(max_attempts):
            if remaining <= 0:
                break
            step = min(random.randint(120, 260), remaining)
            await self._mouse.wheel(0, step * direction)
            remaining -= step
            await asyncio.sleep(HumanTiming.scroll_step_delay())

            # Re-check if element is now visible
            box = await el.bounding_box()
            if box and margin < box["center_y"] < vp_h - margin:
                break
