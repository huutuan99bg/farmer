"""Human timing — Gaussian-distributed delays for natural behavior.

Provides timing functions that mimic human reaction times, typing
speeds, and interaction pauses using Gaussian distributions centered
around psychologically realistic values.

Example:
    >>> delay = HumanTiming.delay(0.1, 0.3)
    >>> await asyncio.sleep(delay)
"""

import random
import math


class HumanTiming:
    """Gaussian-distributed delays mimicking human reaction times.

    All methods return a ``float`` delay in seconds, drawn from a
    Gaussian distribution centered between min and max values.
    Values are clamped to ``[min*0.5, max*1.5]`` to prevent
    extreme outliers.
    """

    @staticmethod
    def delay(min_d: float, max_d: float) -> float:
        """Generate a Gaussian-distributed delay.

        Clusters around the mean of ``min_d`` and ``max_d`` rather
        than being uniformly distributed.

        Args:
            min_d: Minimum expected delay in seconds.
            max_d: Maximum expected delay in seconds.

        Returns:
            Delay in seconds, clamped to ``[min_d*0.5, max_d*1.5]``.

        Example:
            >>> d = HumanTiming.delay(0.05, 0.18)  # click hold time
            >>> 0.025 <= d <= 0.27
            True
        """
        mean = (min_d + max_d) / 2
        std = (max_d - min_d) / 4  # ~95% within range
        d = random.gauss(mean, std)
        return max(min_d * 0.5, min(d, max_d * 1.5))

    @staticmethod
    def typing_delay(char: str, wpm: float = 200) -> float:
        """Calculate per-character typing delay with character-type variance.

        Different character types have different typical delays:
        special characters are slowest, spaces are fastest.

        Args:
            char: The character being typed.
            wpm: Target words per minute (assumes 5 chars/word).

        Returns:
            Delay in seconds before the next character.

        Example:
            >>> d = HumanTiming.typing_delay("a", wpm=200)
            >>> 0.03 < d < 0.12
            True
        """
        base_delay = 60.0 / (wpm * 5)  # avg 5 chars per word

        if char in "@#$%^&*(){}[]|\\:;\"'<>?,./~`":
            return HumanTiming.delay(0.22, 0.40)
        elif char.isupper():
            return HumanTiming.delay(0.15, 0.28)
        elif char == " ":
            return HumanTiming.delay(0.06, 0.14)
        elif char.isdigit():
            return HumanTiming.delay(0.12, 0.22)
        else:
            return HumanTiming.delay(base_delay * 0.7, base_delay * 1.3)

    @staticmethod
    def click_hold() -> float:
        """Generate random mouse button hold time (down -> up).

        Returns:
            Hold duration in seconds (typically 0.05-0.18s).
        """
        return HumanTiming.delay(0.05, 0.18)

    @staticmethod
    def after_click_pause() -> float:
        """Generate post-click pause duration.

        Returns:
            Pause duration in seconds (typically 0.2-0.5s).
        """
        return HumanTiming.delay(0.2, 0.5)

    @staticmethod
    def reading_time(text_length: int) -> float:
        """Estimate reading time from text length (~250 WPM).

        Args:
            text_length: Number of characters in the text.

        Returns:
            Reading time in seconds (minimum 0.5s), with ±20%
            random variance.
        """
        words = text_length / 5
        minutes = words / 250
        return max(0.5, minutes * 60 * random.uniform(0.8, 1.2))

    @staticmethod
    def move_delay(distance: float) -> float:
        """Calculate inter-step delay for mouse movement.

        Args:
            distance: Total movement distance in pixels.

        Returns:
            Per-step delay in seconds.
        """
        if distance < 50:
            return HumanTiming.delay(0.003, 0.008)
        elif distance < 200:
            return HumanTiming.delay(0.004, 0.012)
        else:
            return HumanTiming.delay(0.005, 0.015)

    @staticmethod
    def scroll_step_delay() -> float:
        """Generate delay between scroll wheel steps.

        Returns:
            Delay in seconds (typically 0.08-0.25s).
        """
        return HumanTiming.delay(0.08, 0.25)
