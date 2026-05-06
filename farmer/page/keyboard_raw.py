"""Raw keyboard input via CDP ``Input.dispatchKeyEvent``.

All dispatched events produce ``isTrusted: true`` in the browser.

Example:
    >>> kb = RawKeyboard(cdp)
    >>> await kb.press("Enter")
    >>> await kb.type("hello")
"""

import asyncio
from typing import Optional

from farmer.core.connection import CDPConnection
from farmer.utils.key_map import get_key_definition, get_modifier_mask


class RawKeyboard:
    """Low-level keyboard via direct CDP dispatch. Mirrors Playwright ``page.keyboard``.

    Tracks active modifier keys (Ctrl, Shift, Alt, Meta) to produce
    correct ``modifiers`` bitmask on subsequent key events.
    """

    def __init__(self, cdp: CDPConnection):
        """Initialize raw keyboard controller.

        Args:
            cdp: Active CDP connection instance.
        """
        self._cdp = cdp
        self._modifiers = 0  # active modifier bitmask

    async def down(self, key: str):
        """Press a key down (does not auto-release).

        Dispatches ``keyDown`` with the correct ``key``, ``code``,
        ``windowsVirtualKeyCode``, and ``text`` fields derived from
        the key map. Tracks modifier state internally.

        Args:
            key: Key name (e.g., ``"a"``, ``"Enter"``, ``"Control"``).
                Single characters dispatch with ``text`` field for
                ``input`` event generation.
        """
        definition = get_key_definition(key)
        params = {
            "type": "keyDown" if "text" not in definition else "keyDown",
            "modifiers": self._modifiers,
            "key": definition["key"],
            "code": definition.get("code", ""),
            "windowsVirtualKeyCode": definition.get("keyCode", 0),
        }
        if definition.get("text"):
            params["text"] = definition["text"]
            params["unmodifiedText"] = definition["text"]

        await self._cdp.send("Input.dispatchKeyEvent", params)

        # Track modifier state
        from farmer.utils.key_map import MODIFIER_FLAGS
        if key in MODIFIER_FLAGS:
            self._modifiers |= MODIFIER_FLAGS[key]

    async def up(self, key: str):
        """Release a previously pressed key.

        Args:
            key: Key name matching a prior ``down()`` call.
        """
        definition = get_key_definition(key)
        await self._cdp.send("Input.dispatchKeyEvent", {
            "type": "keyUp",
            "modifiers": self._modifiers,
            "key": definition["key"],
            "code": definition.get("code", ""),
            "windowsVirtualKeyCode": definition.get("keyCode", 0),
        })

        # Untrack modifier
        from farmer.utils.key_map import MODIFIER_FLAGS
        if key in MODIFIER_FLAGS:
            self._modifiers &= ~MODIFIER_FLAGS[key]

    async def press(self, key: str, delay: float = 0):
        """Press and release a key in sequence.

        Args:
            key: Key name (e.g., ``"Enter"``, ``"Backspace"``).
            delay: Seconds to wait between down and up events.

        Example:
            >>> await kb.press("Enter")
            >>> await kb.press("Tab", delay=0.05)
        """
        await self.down(key)
        if delay > 0:
            await asyncio.sleep(delay)
        await self.up(key)

    async def type(self, text: str, delay: float = 0):
        """Type text character by character with key events.

        Each character generates a ``keyDown``/``keyUp`` pair with
        the ``text`` field set, producing both ``keydown`` and
        ``input`` events in the browser.

        Args:
            text: String to type.
            delay: Seconds to wait between each character.

        Example:
            >>> await kb.type("hello@world.com", delay=0.05)
        """
        for char in text:
            await self.down(char)
            await self.up(char)
            if delay > 0:
                await asyncio.sleep(delay)

    async def insert_text(self, text: str):
        """Insert text at once via ``Input.insertText``.

        Faster than ``type()`` but does NOT generate individual
        ``keydown``/``keyup`` events. Only the ``input`` event fires.

        Warning:
            Sites listening for ``keydown`` events will not detect
            this input. Use ``type()`` for stealth operations.

        Args:
            text: String to insert.

        Example:
            >>> await kb.insert_text("bulk text here")
        """
        await self._cdp.send("Input.insertText", {"text": text})
