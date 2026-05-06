"""Launch Chrome with CDP remote debugging enabled.

Provides cross-platform Chrome discovery and process management
with configurable flags, proxy, extensions, and viewport.

Example:
    >>> process, url = await ChromeLauncher.launch(headless=True)
    >>> print(url)  # http://127.0.0.1:54321
"""

import asyncio
import socket
import subprocess
import sys
from typing import Optional


class ChromeLauncher:
    """Launch a Chrome process with CDP remote debugging.

    Provides static methods to find Chrome on the system and launch
    it with appropriate flags for automation.

    Attributes:
        DEFAULT_ARGS: Default Chrome flags optimized for automation.
    """

    DEFAULT_ARGS = [
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        "--disable-ipc-flooding-protection",
        "--disable-hang-monitor",
        "--disable-prompt-on-repost",
        "--disable-sync",
        "--metrics-recording-only",
    ]

    @staticmethod
    def _find_free_port() -> int:
        """Find an available TCP port on the local machine.

        Returns:
            An unused port number.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    @staticmethod
    def _find_chrome() -> str:
        """Auto-detect Chrome executable path on the current OS.

        Searches common installation paths on Windows, macOS, and
        Linux.

        Returns:
            Absolute path to the Chrome executable.

        Raises:
            FileNotFoundError: If Chrome is not found in any
                standard location.
        """
        if sys.platform == "win32":
            paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            ]
        elif sys.platform == "darwin":
            paths = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
        else:
            paths = ["/usr/bin/google-chrome", "/usr/bin/chromium-browser", "/usr/bin/chromium"]

        import os
        for path in paths:
            if os.path.exists(path):
                return path
        raise FileNotFoundError("Chrome not found. Specify executable_path.")

    @staticmethod
    async def launch(
        executable_path: str = None,
        headless: bool = False,
        proxy: str = None,
        extensions: list[str] = None,
        user_data_dir: str = None,
        viewport: tuple[int, int] = (1280, 720),
        port: int = 0,
        args: list[str] = None,
    ) -> tuple[asyncio.subprocess.Process, str]:
        """Launch Chrome with CDP remote debugging enabled.

        Starts a Chrome subprocess with ``--remote-debugging-port``
        and waits for the debug endpoint to become available.

        Args:
            executable_path: Path to Chrome executable. If ``None``,
                auto-detected via ``_find_chrome()``.
            headless: If ``True``, launches Chrome in headless mode
                (``--headless=new``).
            proxy: Proxy server URL (e.g., ``"socks5://127.0.0.1:1080"``).
            extensions: List of extension directory paths to load.
            user_data_dir: Chrome user data directory. If ``None``,
                creates a temporary directory.
            viewport: Window size as ``(width, height)`` in pixels.
            port: Debug port number. If ``0``, a random free port
                is selected.
            args: Additional Chrome command-line arguments.

        Returns:
            Tuple of ``(process, debug_url)`` where ``debug_url``
            is ``"http://127.0.0.1:{port}"``.

        Raises:
            FileNotFoundError: If Chrome executable not found.
            TimeoutError: If Chrome fails to start within 15 seconds.

        Example:
            >>> proc, url = await ChromeLauncher.launch(
            ...     headless=True, viewport=(1920, 1080)
            ... )
            >>> # url == "http://127.0.0.1:XXXXX"
        """
        chrome = executable_path or ChromeLauncher._find_chrome()
        if port == 0:
            port = ChromeLauncher._find_free_port()

        cmd = [chrome]
        cmd.append(f"--remote-debugging-port={port}")
        cmd.extend(ChromeLauncher.DEFAULT_ARGS)

        if headless:
            cmd.append("--headless=new")

        if proxy:
            cmd.append(f"--proxy-server={proxy}")

        if user_data_dir:
            cmd.append(f"--user-data-dir={user_data_dir}")
        else:
            import tempfile
            tmp = tempfile.mkdtemp(prefix="farmer_")
            cmd.append(f"--user-data-dir={tmp}")

        if extensions:
            cmd.append(f"--load-extension={','.join(extensions)}")

        cmd.append(f"--window-size={viewport[0]},{viewport[1]}")

        if args:
            cmd.extend(args)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        debug_url = f"http://127.0.0.1:{port}"

        # Wait for Chrome to be ready
        import aiohttp
        for _ in range(30):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{debug_url}/json/version", timeout=aiohttp.ClientTimeout(total=1)):
                        return process, debug_url
            except Exception:
                await asyncio.sleep(0.5)

        raise TimeoutError(f"Chrome failed to start on port {port}")
