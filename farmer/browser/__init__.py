"""Farmer browser layer — lifecycle and tab management."""

from farmer.browser.browser import Browser
from farmer.browser.connector import CDPConnector
from farmer.browser.launcher import ChromeLauncher

__all__ = ["Browser", "CDPConnector", "ChromeLauncher"]
