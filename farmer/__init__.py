"""
Farmer — Stealth Browser Automation Library.

Raw CDP client with human-like interaction.
Zero Runtime.enable → undetectable by anti-bot systems.

Usage:
    from farmer import Farmer

    async with await Farmer.connect("http://127.0.0.1:9222") as f:
        await f.goto("https://example.com")
        await f.click("#submit")
        await f.fill("#email", "user@test.com")
"""

from farmer.farmer import Farmer
from farmer.farmer_sync import FarmerSync
from farmer.human.human_iframe import HumanIframe
from farmer._version import __version__

__all__ = ["Farmer", "FarmerSync", "HumanIframe", "__version__"]
