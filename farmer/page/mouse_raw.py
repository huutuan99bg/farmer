"""Raw mouse input via CDP ``Input.dispatchMouseEvent``.

All dispatched events produce ``isTrusted: true`` in the browser.

Example:
    >>> mouse = RawMouse(cdp)
    >>> await mouse.click(100, 200)
"""

from farmer.core.connection import CDPConnection


class RawMouse:
    """Low-level mouse via direct CDP dispatch. Mirrors Playwright ``page.mouse``.

    Attributes:
        x: Current mouse X position.
        y: Current mouse Y position.
    """

    def __init__(self, cdp: CDPConnection):
        """Initialize raw mouse controller.

        Args:
            cdp: Active CDP connection instance.
        """
        self._cdp = cdp
        self._x = 0.0
        self._y = 0.0

    @property
    def x(self) -> float:
        """float: Current mouse X coordinate."""
        return self._x

    @property
    def y(self) -> float:
        """float: Current mouse Y coordinate."""
        return self._y

    async def move(self, x: float, y: float):
        """Move mouse cursor instantly (no interpolation).

        Args:
            x: Target X coordinate in CSS pixels.
            y: Target Y coordinate in CSS pixels.
        """
        await self._cdp.send("Input.dispatchMouseEvent", {
            "type": "mouseMoved", "x": x, "y": y,
            "button": "none", "buttons": 0,
        })
        self._x = x
        self._y = y

    async def down(self, button: str = "left", click_count: int = 1):
        """Press mouse button at current position.

        Args:
            button: ``"left"``, ``"right"``, or ``"middle"``.
            click_count: Click ordinal (2 for double-click second press).
        """
        await self._cdp.send("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": self._x, "y": self._y,
            "button": button, "buttons": 1, "clickCount": click_count,
        })

    async def up(self, button: str = "left", click_count: int = 1):
        """Release mouse button at current position.

        Args:
            button: ``"left"``, ``"right"``, or ``"middle"``.
            click_count: Click ordinal matching the preceding ``down()``.
        """
        await self._cdp.send("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": self._x, "y": self._y,
            "button": button, "buttons": 0, "clickCount": click_count,
        })

    async def click(self, x: float, y: float, button: str = "left", click_count: int = 1):
        """Move then click (move -> down -> up).

        Args:
            x: Target X coordinate.
            y: Target Y coordinate.
            button: Mouse button.
            click_count: Number of clicks.
        """
        await self.move(x, y)
        await self.down(button, click_count)
        await self.up(button, click_count)

    async def dblclick(self, x: float, y: float, button: str = "left"):
        """Double-click at position with correct ``clickCount`` sequence.

        Args:
            x: Target X coordinate.
            y: Target Y coordinate.
            button: Mouse button.
        """
        await self.move(x, y)
        await self.down(button, click_count=1)
        await self.up(button, click_count=1)
        await self.down(button, click_count=2)
        await self.up(button, click_count=2)

    async def wheel(self, delta_x: float = 0, delta_y: float = 0):
        """Dispatch mouse wheel event at current position.

        Args:
            delta_x: Horizontal scroll (positive = right).
            delta_y: Vertical scroll (positive = down).
        """
        await self._cdp.send("Input.dispatchMouseEvent", {
            "type": "mouseWheel", "x": self._x, "y": self._y,
            "deltaX": delta_x, "deltaY": delta_y,
            "button": "none", "buttons": 0,
        })
