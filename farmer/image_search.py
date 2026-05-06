"""ImageSearch — OpenCV template matching for inaccessible DOM.

Provides screenshot-based element detection using OpenCV
``matchTemplate``. Designed for elements behind closed shadow
DOM or cross-origin iframes where CDP DOM queries fail.

Requires: ``opencv-python``, ``numpy``.
"""

import asyncio
import random
from typing import Optional, Union, TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    from farmer.page.page import Page
    from farmer.human.human import Human
    from farmer.element import Element


def _do_match(
    source_bytes: bytes,
    template_path: str,
    multi_scale: bool = True,
    threshold: float = 0.85,
) -> Optional[dict]:
    """Run OpenCV template matching on in-memory screenshot data.

    Performs multi-scale, multi-method matching and returns the
    best result if it exceeds the confidence threshold.

    Args:
        source_bytes: PNG screenshot as raw bytes.
        template_path: File path to the template image.
        multi_scale: If ``True``, tries scales [0.8, 0.9, 1.0, 1.1, 1.2].
        threshold: Minimum confidence to accept a match (0-1).

    Returns:
        Dict with keys ``confidence``, ``left``, ``top``, ``right``,
        ``bottom``, ``width``, ``height``, ``center_x``, ``center_y``,
        ``scale``. Returns ``None`` if no match above threshold.
    """
    # Decode source from bytes
    src_array = np.frombuffer(source_bytes, dtype=np.uint8)
    img_bgr = cv2.imdecode(src_array, cv2.IMREAD_COLOR)
    if img_bgr is None:
        return None
    img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    # Load template
    template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
    if template is None:
        return None
    t_h, t_w = template.shape[:2]

    best_result = None
    best_val = -1

    # Scales to try
    scales = [1.0]
    if multi_scale:
        scales = [0.8, 0.9, 1.0, 1.1, 1.2]

    methods = [cv2.TM_CCOEFF_NORMED, cv2.TM_CCORR_NORMED]

    for scale in scales:
        if scale != 1.0:
            new_w = int(t_w * scale)
            new_h = int(t_h * scale)
            if new_w < 5 or new_h < 5:
                continue
            tmpl = cv2.resize(template, (new_w, new_h))
        else:
            tmpl = template
            new_w, new_h = t_w, t_h

        # Skip if template is larger than source
        if new_h > img_gray.shape[0] or new_w > img_gray.shape[1]:
            continue

        for method in methods:
            res = cv2.matchTemplate(img_gray, tmpl, method)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)

            if max_val > best_val:
                best_val = max_val
                left, top = max_loc
                best_result = {
                    "confidence": float(max_val),
                    "left": left,
                    "top": top,
                    "right": left + new_w,
                    "bottom": top + new_h,
                    "width": new_w,
                    "height": new_h,
                    "center_x": left + new_w // 2,
                    "center_y": top + new_h // 2,
                    "scale": scale,
                }

    if best_result and best_result["confidence"] >= threshold:
        return best_result
    return None


class ImageSearch:
    """Image-based element search using OpenCV template matching.

    For elements behind closed shadow DOM or cross-origin iframes
    where CDP DOM access is unavailable.

    Features:
    - In-memory screenshots (no temp files).
    - Multi-scale matching (0.8x to 1.2x).
    - Multi-method (TM_CCOEFF_NORMED + TM_CCORR_NORMED).
    - Thread pool for OpenCV (non-blocking async).
    - Randomized polling intervals (anti-detection).
    """

    def __init__(
        self,
        page: "Page",
        human: "Optional[Human]" = None,
        default_timeout: float = 10.0,
        interval: float = 0.4,
        threshold: float = 0.85,
    ):
        """Initialize ImageSearch.

        Args:
            page: Page instance for taking screenshots.
            human: Optional Human instance for human-like clicks.
            default_timeout: Default polling timeout in seconds.
            interval: Base polling interval in seconds.
            threshold: Default minimum confidence (0-1).
        """
        self._page = page
        self._human = human
        self.default_timeout = default_timeout
        self.interval = interval
        self.threshold = threshold

    # ══════════ Find ══════════

    async def find(
        self,
        template: str,
        element: "Optional[Element]" = None,
        threshold: float = None,
        timeout: float = None,
        multi_scale: bool = True,
        raise_on_fail: bool = True,
    ) -> Optional[dict]:
        """Find a template image in a screenshot (polling loop).

        Args:
            template: File path to the template image.
            element: Optional element to screenshot instead of full page.
            threshold: Confidence threshold override.
            timeout: Polling timeout override.
            multi_scale: Enable multi-scale matching.
            raise_on_fail: Raise ``TimeoutError`` on failure.

        Returns:
            Match rect dict, or ``None`` if not found.

        Raises:
            TimeoutError: If not found within timeout.
        """
        _threshold = threshold or self.threshold
        _timeout = timeout or self.default_timeout
        deadline = asyncio.get_event_loop().time() + _timeout

        while asyncio.get_event_loop().time() < deadline:
            try:
                if element:
                    screenshot_bytes = await element.screenshot()
                else:
                    screenshot_bytes = await self._page.screenshot()
            except Exception:
                await asyncio.sleep(random.uniform(self.interval * 0.7, self.interval * 1.5))
                continue

            result = await asyncio.to_thread(
                _do_match, screenshot_bytes, template, multi_scale, _threshold
            )
            if result:
                return result
            await asyncio.sleep(random.uniform(self.interval * 0.7, self.interval * 1.5))

        if raise_on_fail:
            raise TimeoutError(f"Image not found ({_timeout}s): {template}")
        return None

    # ══════════ Find Any ══════════

    async def find_any(
        self,
        templates: list[str],
        element: "Optional[Element]" = None,
        threshold: float = None,
        timeout: float = None,
        multi_scale: bool = True,
        raise_on_fail: bool = True,
    ) -> Optional[tuple[str, dict]]:
        """Wait for ANY template to appear in a screenshot.

        Takes one screenshot per poll cycle and matches all templates.

        Args:
            templates: List of template image file paths.
            element: Optional element to screenshot.
            threshold: Confidence threshold override.
            timeout: Polling timeout override.
            multi_scale: Enable multi-scale matching.
            raise_on_fail: Raise on timeout.

        Returns:
            Tuple of ``(matched_template_path, rect_dict)``, or ``None``.

        Raises:
            TimeoutError: If no template found within timeout.
        """
        _threshold = threshold or self.threshold
        _timeout = timeout or self.default_timeout
        deadline = asyncio.get_event_loop().time() + _timeout

        while asyncio.get_event_loop().time() < deadline:
            try:
                if element:
                    screenshot_bytes = await element.screenshot()
                else:
                    screenshot_bytes = await self._page.screenshot()
            except Exception:
                await asyncio.sleep(random.uniform(self.interval * 0.7, self.interval * 1.5))
                continue

            for tmpl in templates:
                result = await asyncio.to_thread(
                    _do_match, screenshot_bytes, tmpl, multi_scale, _threshold
                )
                if result:
                    return (tmpl, result)

            await asyncio.sleep(random.uniform(self.interval * 0.7, self.interval * 1.5))

        if raise_on_fail:
            raise TimeoutError(f"No image found ({_timeout}s)")
        return None

    # ══════════ Click ══════════

    async def click(
        self,
        template: str,
        element: "Optional[Element]" = None,
        threshold: float = None,
        timeout: float = None,
        offset: tuple = None,
        button: str = "left",
        hold: float = None,
        raise_on_fail: bool = True,
    ) -> Optional[dict]:
        """Find a template and click at the match position.

        Uses Human layer if available, otherwise raw mouse click.

        Args:
            template: File path to the template image.
            element: Optional element scope.
            threshold: Confidence threshold override.
            timeout: Polling timeout override.
            offset: Click offset within match ``(ox, oy)`` as fractions.
            button: Mouse button.
            hold: Hold duration in ms (Human layer only).
            raise_on_fail: Raise on not found.

        Returns:
            Match rect dict, or ``None``.
        """
        rect = await self.find(
            template, element, threshold, timeout,
            raise_on_fail=raise_on_fail,
        )
        if not rect:
            return None

        # Calculate absolute coordinates
        abs_x, abs_y = await self._get_absolute_coords(rect, element, offset)

        if self._human:
            await self._human.click((abs_x, abs_y), button=button, hold=hold)
        else:
            await self._page.mouse.click(abs_x, abs_y, button=button)

        return rect

    # ══════════ Fill ══════════

    async def fill(
        self,
        template: str,
        text: str,
        element: "Optional[Element]" = None,
        threshold: float = None,
        timeout: float = None,
        offset: tuple = None,
        simulate: bool = True,
        clear_first: bool = True,
        raise_on_fail: bool = True,
        **type_kwargs,
    ) -> Optional[dict]:
        """Find a template, click it, and type text.

        Args:
            template: File path to the template image.
            text: Text to type after clicking.
            element: Optional element scope.
            threshold: Confidence threshold override.
            timeout: Polling timeout override.
            offset: Click offset within match.
            simulate: If ``True``, human-like typing. If ``False``,
                fast ``insertText``.
            clear_first: Clear existing text before typing.
            raise_on_fail: Raise on not found.
            **type_kwargs: Additional args for ``Human.type()``.

        Returns:
            Match rect dict, or ``None``.
        """
        rect = await self.click(
            template, element, threshold, timeout,
            offset=offset, raise_on_fail=raise_on_fail,
        )
        if not rect:
            return None

        if simulate:
            await asyncio.sleep(random.uniform(0.2, 0.4))
            if clear_first:
                if self._human:
                    await self._human.hotkey("Control", "a")
                    await self._human.press("Backspace")
                else:
                    await self._page.keyboard.down("Control")
                    await self._page.keyboard.press("a")
                    await self._page.keyboard.up("Control")
                    await self._page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.08, 0.15))

            if self._human:
                await self._human.type(text, **type_kwargs)
            else:
                await self._page.keyboard.type(text, delay=0.05)
        else:
            if clear_first:
                await self._page.keyboard.down("Control")
                await self._page.keyboard.press("a")
                await self._page.keyboard.up("Control")
            await self._page.keyboard.insert_text(text)

        return rect

    # ══════════ Private ══════════

    async def _get_absolute_coords(
        self,
        rect: dict,
        element: "Optional[Element]" = None,
        offset: tuple = None,
    ) -> tuple[float, float]:
        """Convert match rect to absolute viewport coordinates.

        Args:
            rect: Match result from ``_do_match()``.
            element: Optional element that was screenshotted.
            offset: Relative offset ``(ox, oy)`` within match rect.

        Returns:
            Tuple of ``(x, y)`` in viewport coordinates.
        """
        if offset:
            ox, oy = offset
            x = rect["left"] + rect["width"] * ox
            y = rect["top"] + rect["height"] * oy
        else:
            # Random point within matched area
            x = rect["left"] + random.uniform(0.3, 0.7) * rect["width"]
            y = rect["top"] + random.uniform(0.3, 0.7) * rect["height"]

        # Add element offset if searching within an element
        if element:
            box = await element.bounding_box()
            if box:
                x += box["x"]
                y += box["y"]

        return x, y
