"""Structured logging for Farmer — per-instance with session ID.

Provides a logging wrapper that tags every log message with a unique
session identifier, enabling log disambiguation across multi-threaded
or multi-worker deployments.

Example:
    >>> log = FarmerLogger(level=logging.DEBUG, session_id="worker_01")
    >>> log.info("Connected")
    [12:00:00] [farmer.worker_01] INFO Connected
"""

import logging
import uuid
from typing import Optional


# Custom log level for verbose CDP messages
CDP_LEVEL = 5
logging.addLevelName(CDP_LEVEL, "CDP")


class FarmerLogger:
    """Structured logger for Farmer instances.

    Each logger is uniquely identified by a session ID (auto-generated
    or user-provided) to prevent log collision across concurrent
    workers.

    Attributes:
        session_id: Unique identifier for this logger instance.
        logger: Underlying ``logging.Logger`` instance.

    Example:
        >>> log = FarmerLogger(name="farmer", level=logging.INFO)
        >>> log.action("click", "#submit")
        [12:00:00] [farmer.a1b2c3d4] INFO ACTION click "#submit"
    """

    def __init__(
        self,
        name: str = "farmer",
        level: int = logging.INFO,
        session_id: Optional[str] = None,
    ):
        """Initialize a Farmer logger.

        Args:
            name: Logger name prefix. Combined with ``session_id``
                to form the full logger name (e.g., ``farmer.a1b2c3d4``).
            level: Logging level (e.g., ``logging.INFO``,
                ``logging.DEBUG``).
            session_id: Optional fixed session ID. If ``None``, a
                random 8-character hex string is generated.
        """
        self.session_id = session_id or uuid.uuid4().hex[:8]
        self._name = f"{name}.{self.session_id}"
        self.logger = logging.getLogger(self._name)
        self.logger.setLevel(level)

        # Add handler only if none exists (avoid duplicates)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                f"[%(asctime)s] [{self._name}] %(levelname)s %(message)s",
                datefmt="%H:%M:%S",
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def cdp(self, method: str, params: dict = None, direction: str = "→"):
        """Log a CDP message at the custom CDP level.

        Args:
            method: CDP method name (e.g., ``"Page.navigate"``).
            params: Optional parameters dict. Logged inline if provided.
            direction: Arrow indicating send (``"→"``) or receive
                (``"←"``).
        """
        p = f" {params}" if params else ""
        self.logger.log(CDP_LEVEL, f"{direction} {method}{p}")

    def action(self, action: str, target: str = None, **extra):
        """Log a high-level user action (click, fill, type, scroll).

        Args:
            action: Action name (e.g., ``"click"``, ``"fill"``).
            target: Target selector or description.
            **extra: Additional key-value pairs appended to the log
                message (e.g., ``text_len=42``).

        Example:
            >>> log.action("fill", "#email", text_len=25)
            ACTION fill "#email" text_len=25
        """
        parts = [f"ACTION {action}"]
        if target:
            parts.append(f'"{target}"')
        for k, v in extra.items():
            parts.append(f"{k}={v}")
        self.logger.info(" ".join(parts))

    def mouse(self, x: float, y: float, event: str = "move"):
        """Log mouse position at the CDP level (verbose).

        Args:
            x: Mouse X coordinate.
            y: Mouse Y coordinate.
            event: Event type (e.g., ``"move"``, ``"click"``).
        """
        self.logger.log(CDP_LEVEL, f"MOUSE {event} ({x:.1f}, {y:.1f})")

    def debug(self, msg: str, **extra):
        """Log a debug message.

        Args:
            msg: Message string.
            **extra: Reserved for future structured fields.
        """
        self.logger.debug(msg)

    def info(self, msg: str, **extra):
        """Log an informational message.

        Args:
            msg: Message string.
            **extra: Reserved for future structured fields.
        """
        self.logger.info(msg)

    def warn(self, msg: str, **extra):
        """Log a warning message.

        Args:
            msg: Message string.
            **extra: Reserved for future structured fields.
        """
        self.logger.warning(msg)

    def error(self, msg: str, exc: Exception = None, **extra):
        """Log an error message with optional exception traceback.

        Args:
            msg: Error description.
            exc: Optional exception instance. If provided, the full
                traceback is included via ``exc_info=True``.
            **extra: Reserved for future structured fields.
        """
        if exc:
            self.logger.error(f"{msg}: {exc}", exc_info=True)
        else:
            self.logger.error(msg)
