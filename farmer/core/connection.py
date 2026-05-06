"""Async CDP WebSocket connection with auto-reconnect and heartbeat.

Core transport layer — all CDP communication flows through this module.
Provides reliable WebSocket connectivity with automatic retry logic,
heartbeat-based connection health monitoring, and an event listener system
for CDP domain events.

Example:
    >>> conn = CDPConnection("ws://127.0.0.1:9222/devtools/page/XXX")
    >>> await conn.connect()
    >>> result = await conn.send("Page.navigate", {"url": "https://example.com"})
    >>> await conn.close()
"""

import asyncio
import json
import logging
from typing import Any, Callable, Dict, Optional

import aiohttp

from farmer.core.logger import FarmerLogger


class CDPConnection:
    """Async WebSocket connection to Chrome DevTools Protocol.

    Manages the full lifecycle of a WebSocket connection to a Chrome
    DevTools Protocol endpoint, including automatic reconnection with
    exponential backoff, heartbeat pings to detect stale connections,
    and an event listener system for CDP domain events.

    Attributes:
        connected: Whether the WebSocket is currently connected.

    Example:
        >>> conn = CDPConnection("ws://127.0.0.1:9222/devtools/page/XXX")
        >>> await conn.connect()
        >>> result = await conn.send("DOM.getDocument", {"depth": 0})
        >>> conn.on_event("Page.loadEventFired", lambda p: print("loaded"))
        >>> await conn.close()
    """

    def __init__(
        self,
        ws_url: str,
        logger: Optional[FarmerLogger] = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
        ping_interval: float = 10.0,
        connect_timeout: float = 10.0,
    ):
        """Initialize CDP connection.

        Args:
            ws_url: WebSocket URL to connect to.
                Format: ``ws://host:port/devtools/page/TARGET_ID``.
            logger: Structured logger instance. Creates a default
                WARNING-level logger if not provided.
            max_retries: Maximum number of reconnection attempts before
                raising ``ConnectionError``.
            retry_delay: Initial delay in seconds between retries.
            retry_backoff: Multiplier applied to ``retry_delay`` after
                each failed attempt (exponential backoff).
            ping_interval: Seconds between WebSocket heartbeat pings.
            connect_timeout: Timeout in seconds for each connection
                attempt.
        """
        self._ws_url = ws_url
        self._log = logger or FarmerLogger(level=logging.WARNING)
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._retry_backoff = retry_backoff
        self._ping_interval = ping_interval
        self._connect_timeout = connect_timeout

        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._msg_id = 0
        self._pending: Dict[int, asyncio.Future] = {}
        self._event_listeners: Dict[str, list[Callable]] = {}
        self._enabled_domains: set[str] = set()
        self._listener_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._connected = False

        # Callbacks
        self._on_disconnect_cb: Optional[Callable] = None
        self._on_reconnect_cb: Optional[Callable] = None

    @property
    def connected(self) -> bool:
        """bool: Whether the WebSocket connection is alive."""
        return self._connected and self._ws is not None and not self._ws.closed

    async def connect(self):
        """Establish WebSocket connection with retry logic.

        Attempts to connect up to ``max_retries + 1`` times with
        exponential backoff between attempts. On success, starts
        background listener and heartbeat tasks.

        Raises:
            ConnectionError: If all connection attempts fail.

        Example:
            >>> conn = CDPConnection("ws://127.0.0.1:9222/devtools/page/X")
            >>> await conn.connect()
        """
        delay = self._retry_delay
        last_error = None

        for attempt in range(self._max_retries + 1):
            try:
                if not self._session or self._session.closed:
                    self._session = aiohttp.ClientSession()

                self._ws = await asyncio.wait_for(
                    self._session.ws_connect(
                        self._ws_url, max_msg_size=50 * 1024 * 1024
                    ),
                    timeout=self._connect_timeout,
                )
                self._connected = True
                self._listener_task = asyncio.create_task(self._listen())
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                self._log.info(f"Connected to {self._ws_url}")
                return
            except Exception as e:
                last_error = e
                if attempt < self._max_retries:
                    self._log.warn(
                        f"Connect attempt {attempt + 1} failed: {e}, "
                        f"retry in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
                    delay *= self._retry_backoff

        raise ConnectionError(
            f"Failed to connect after {self._max_retries + 1} attempts: {last_error}"
        )

    async def reconnect(self):
        """Reconnect after disconnect and re-enable CDP domains.

        Cleans up stale tasks, re-establishes the WebSocket connection,
        and re-enables all previously active CDP domains (e.g.,
        ``Page.enable``, ``DOM.enable``).

        Raises:
            ConnectionError: If reconnection fails after all retries.
        """
        self._log.warn("Reconnecting...")
        self._connected = False

        # Cleanup old tasks
        await self._cleanup_tasks()

        # Reconnect
        await self.connect()

        # Re-enable domains that were enabled before
        for domain in list(self._enabled_domains):
            try:
                await self.send(f"{domain}.enable")
            except Exception as e:
                self._log.warn(f"Failed to re-enable {domain}: {e}")

        if self._on_reconnect_cb:
            try:
                self._on_reconnect_cb()
            except Exception:
                pass
        self._log.info("Reconnected successfully")

    async def send(
        self, method: str, params: dict = None, timeout: float = 30
    ) -> dict:
        """Send CDP command and wait for response.

        Automatically tracks enabled/disabled domains for reconnection.
        If the WebSocket is disconnected, triggers a reconnect before
        sending. If the send itself fails, retries once after reconnect.

        Args:
            method: CDP method name (e.g., ``"Page.navigate"``).
            params: Optional parameters dict for the CDP method.
            timeout: Maximum seconds to wait for a response.

        Returns:
            The ``result`` field from the CDP response as a dict.

        Raises:
            RuntimeError: If the CDP response contains an error.
            asyncio.TimeoutError: If no response within ``timeout``.
            ConnectionError: If reconnection fails.

        Example:
            >>> result = await conn.send("Page.navigate", {"url": "https://example.com"})
            >>> frame_id = result.get("frameId")
        """
        if not self.connected:
            await self.reconnect()

        # Track enabled domains for reconnect
        if method.endswith(".enable"):
            self._enabled_domains.add(method.rsplit(".", 1)[0])
        elif method.endswith(".disable"):
            self._enabled_domains.discard(method.rsplit(".", 1)[0])

        self._msg_id += 1
        msg_id = self._msg_id
        payload: Dict[str, Any] = {"id": msg_id, "method": method}
        if params:
            payload["params"] = params

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending[msg_id] = fut

        self._log.cdp(method, params, "→")

        try:
            await self._ws.send_json(payload)
        except Exception as e:
            self._pending.pop(msg_id, None)
            self._log.warn(f"Send failed: {e}, attempting reconnect")
            await self.reconnect()
            # Retry once after reconnect
            self._msg_id += 1
            msg_id = self._msg_id
            payload["id"] = msg_id
            fut = loop.create_future()
            self._pending[msg_id] = fut
            await self._ws.send_json(payload)

        try:
            result = await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(msg_id, None)

        if "error" in result:
            err = result["error"]
            raise RuntimeError(
                f'CDP error [{err.get("code")}]: {err.get("message")}'
            )

        self._log.cdp(method, None, "←")
        return result.get("result", {})

    def on_event(self, event_name: str, callback: Callable):
        """Register a listener for a CDP event.

        Multiple listeners can be registered for the same event.
        Callbacks may be sync or async (coroutines are auto-scheduled).

        Args:
            event_name: CDP event name (e.g.,
                ``"Network.responseReceived"``).
            callback: Function accepting a single ``params`` dict
                argument.

        Example:
            >>> def on_response(params):
            ...     print(params["response"]["url"])
            >>> conn.on_event("Network.responseReceived", on_response)
        """
        if event_name not in self._event_listeners:
            self._event_listeners[event_name] = []
        self._event_listeners[event_name].append(callback)

    def remove_event(self, event_name: str, callback: Callable):
        """Remove a specific event listener.

        Args:
            event_name: CDP event name.
            callback: The exact callback reference to remove.
        """
        if event_name in self._event_listeners:
            self._event_listeners[event_name] = [
                cb for cb in self._event_listeners[event_name] if cb is not callback
            ]

    def on_disconnect(self, callback: Callable):
        """Register callback invoked when WebSocket disconnects.

        Args:
            callback: No-argument callable.
        """
        self._on_disconnect_cb = callback

    def on_reconnect(self, callback: Callable):
        """Register callback invoked after successful reconnection.

        Args:
            callback: No-argument callable.
        """
        self._on_reconnect_cb = callback

    async def _listen(self):
        """Background listener for CDP responses and events.

        Dispatches incoming messages to pending futures (for command
        responses) or registered event listeners (for CDP events).
        """
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    msg_id = data.get("id")

                    if msg_id is not None and msg_id in self._pending:
                        # Response to a sent command
                        self._pending[msg_id].set_result(data)
                    elif "method" in data:
                        # CDP event
                        event_name = data["method"]
                        params = data.get("params", {})
                        for cb in self._event_listeners.get(event_name, []):
                            try:
                                result = cb(params)
                                if asyncio.iscoroutine(result):
                                    asyncio.create_task(result)
                            except Exception as e:
                                self._log.error(f"Event handler error", exc=e)

                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break
        except asyncio.CancelledError:
            return
        except Exception as e:
            self._log.error("Listener error", exc=e)
        finally:
            self._connected = False
            if self._on_disconnect_cb:
                try:
                    self._on_disconnect_cb()
                except Exception:
                    pass

    async def _heartbeat_loop(self):
        """Ping WebSocket periodically to detect stale connections.

        Runs every ``ping_interval`` seconds. If a ping fails, marks
        the connection as disconnected.
        """
        try:
            while self._connected:
                await asyncio.sleep(self._ping_interval)
                if self._ws and not self._ws.closed:
                    try:
                        await self._ws.ping()
                    except Exception:
                        self._log.warn("Heartbeat ping failed")
                        self._connected = False
                        break
        except asyncio.CancelledError:
            return

    async def _cleanup_tasks(self):
        """Cancel background listener and heartbeat tasks.

        Also fails all pending command futures with ``ConnectionError``.
        """
        for task in [self._listener_task, self._heartbeat_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._listener_task = None
        self._heartbeat_task = None

        # Fail all pending futures
        for msg_id, fut in list(self._pending.items()):
            if not fut.done():
                fut.set_exception(ConnectionError("Connection lost"))
        self._pending.clear()

    async def close(self):
        """Close WebSocket connection and release all resources.

        Cancels background tasks, closes the WebSocket and the
        underlying HTTP session.

        Example:
            >>> await conn.close()
        """
        self._connected = False
        await self._cleanup_tasks()
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
        self._log.info("Disconnected")


async def resolve_ws_url(debug_url: str) -> str:
    """Resolve a Chrome debug HTTP URL to a WebSocket URL.

    Queries the ``/json`` endpoint to discover available page targets
    and returns the WebSocket debugger URL of the first page target.

    Args:
        debug_url: Chrome debug URL (e.g., ``"http://127.0.0.1:9222"``).

    Returns:
        WebSocket URL for the first page target.
        Format: ``ws://host:port/devtools/page/TARGET_ID``.

    Raises:
        RuntimeError: If no page target is found at the given URL.
        aiohttp.ClientError: If the HTTP request fails.

    Example:
        >>> ws = await resolve_ws_url("http://127.0.0.1:9222")
        >>> print(ws)
        'ws://127.0.0.1:9222/devtools/page/ABC123'
    """
    debug_url = debug_url.rstrip("/")
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{debug_url}/json") as resp:
            pages = await resp.json()

    for target in pages:
        if target.get("type") == "page":
            ws_url = target.get("webSocketDebuggerUrl")
            if ws_url:
                return ws_url

    raise RuntimeError(f"No page target found at {debug_url}")


async def get_all_targets(debug_url: str) -> list[dict]:
    """Get all browser targets from the ``/json`` debug endpoint.

    Args:
        debug_url: Chrome debug URL (e.g., ``"http://127.0.0.1:9222"``).

    Returns:
        List of target info dicts, each containing keys like
        ``"id"``, ``"type"``, ``"title"``, ``"url"``,
        ``"webSocketDebuggerUrl"``.

    Raises:
        aiohttp.ClientError: If the HTTP request fails.

    Example:
        >>> targets = await get_all_targets("http://127.0.0.1:9222")
        >>> for t in targets:
        ...     print(t["type"], t["title"])
    """
    debug_url = debug_url.rstrip("/")
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{debug_url}/json") as resp:
            return await resp.json()
