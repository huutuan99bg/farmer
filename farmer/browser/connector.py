"""Connect to an existing Chrome CDP endpoint.

Resolves debug HTTP URLs to WebSocket URLs and establishes a
CDP connection.

Example:
    >>> conn, target_id = await CDPConnector.connect("http://127.0.0.1:9222")
"""

import aiohttp

from farmer.core.connection import CDPConnection, resolve_ws_url


class CDPConnector:
    """Connect to an existing Chrome instance via CDP debug URL.

    Supports both HTTP debug URLs (resolved via ``/json`` endpoint)
    and direct ``ws://`` WebSocket URLs.
    """

    @staticmethod
    async def connect(debug_url: str, **cdp_kwargs) -> tuple[CDPConnection, str]:
        """Establish a CDP connection to an existing Chrome instance.

        Args:
            debug_url: Chrome debug URL. Accepts either:
                - HTTP URL: ``"http://127.0.0.1:9222"`` (resolved via
                  ``/json`` to find the first page target).
                - WebSocket URL: ``"ws://127.0.0.1:9222/devtools/page/X"``
                  (used directly).
            **cdp_kwargs: Additional keyword arguments passed to
                ``CDPConnection.__init__()`` (e.g., ``logger``,
                ``max_retries``, ``ping_interval``).

        Returns:
            Tuple of ``(CDPConnection, target_id)`` where
            ``target_id`` is extracted from the WebSocket URL.

        Raises:
            RuntimeError: If no page target found (HTTP URL).
            ConnectionError: If WebSocket connection fails.

        Example:
            >>> conn, tid = await CDPConnector.connect(
            ...     "http://127.0.0.1:9222", max_retries=5
            ... )
        """
        if debug_url.startswith("ws://") or debug_url.startswith("wss://"):
            ws_url = debug_url
        else:
            ws_url = await resolve_ws_url(debug_url)

        conn = CDPConnection(ws_url, **cdp_kwargs)
        await conn.connect()

        # Extract target_id from ws URL
        # ws://127.0.0.1:9222/devtools/page/XXXX
        target_id = ws_url.rsplit("/", 1)[-1] if "/devtools/page/" in ws_url else ""

        return conn, target_id
