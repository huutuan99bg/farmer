"""Bezier path generation with jitter, overshoot, and micro-hesitation.

Generates human-like mouse movement paths using cubic Bezier curves
with Gaussian noise, optional overshoot correction, and rare
micro-hesitation pauses.

Example:
    >>> path = BezierPath.generate((100, 100), (500, 300))
    >>> for x, y in path:
    ...     await mouse.move(x, y)
"""

import math
import random
from typing import Optional


class BezierPath:
    """Generate human-like mouse movement paths using cubic Bezier curves.

    The generated paths include:
    - Random control point offsets for natural curvature.
    - Gaussian jitter (stronger at midpoint, zero at endpoints).
    - 5% chance of micro-hesitation (brief pause mid-path).
    - 12% chance of overshoot + correction for distances > 50px.
    """

    @staticmethod
    def generate(
        start: tuple[float, float],
        end: tuple[float, float],
        steps: int = None,
        jitter: float = 1.5,
        spread: float = 0.35,
    ) -> list[tuple[float, float]]:
        """Generate a Bezier path from start to end.

        Args:
            start: Starting point ``(x, y)``.
            end: Ending point ``(x, y)``.
            steps: Number of interpolation points. If ``None``,
                auto-calculated from distance via ``calculate_steps()``.
            jitter: Gaussian noise intensity applied along the path.
                Zero at endpoints, maximum at midpoint.
            spread: Control point spread factor. ``0.0`` produces a
                straight line, ``1.0`` produces very curved paths.

        Returns:
            List of ``(x, y)`` tuples along the path. First point
            matches ``start``, last point matches ``end``.

        Example:
            >>> pts = BezierPath.generate((0, 0), (500, 300), jitter=2.0)
            >>> len(pts)
            42
        """
        sx, sy = start
        ex, ey = end
        distance = math.hypot(ex - sx, ey - sy)

        if distance < 1:
            return [end]

        # Auto-calculate steps
        if steps is None:
            steps = BezierPath.calculate_steps(distance)

        # Generate 2 random control points
        dx, dy = ex - sx, ey - sy
        mid_x, mid_y = (sx + ex) / 2, (sy + ey) / 2

        # Perpendicular offset for control points
        perp_x, perp_y = -dy, dx  # perpendicular to direction
        perp_len = math.hypot(perp_x, perp_y) or 1
        perp_x, perp_y = perp_x / perp_len, perp_y / perp_len

        # Control point 1 (1/3 of the way)
        cp1_offset = random.gauss(0, spread * distance * 0.3)
        cp1_x = sx + dx * 0.33 + perp_x * cp1_offset
        cp1_y = sy + dy * 0.33 + perp_y * cp1_offset

        # Control point 2 (2/3 of the way)
        cp2_offset = random.gauss(0, spread * distance * 0.3)
        cp2_x = sx + dx * 0.67 + perp_x * cp2_offset
        cp2_y = sy + dy * 0.67 + perp_y * cp2_offset

        # Generate Bezier points
        points = []
        for i in range(steps + 1):
            t = i / steps
            # Cubic Bezier formula
            x = (
                (1 - t) ** 3 * sx
                + 3 * (1 - t) ** 2 * t * cp1_x
                + 3 * (1 - t) * t ** 2 * cp2_x
                + t ** 3 * ex
            )
            y = (
                (1 - t) ** 3 * sy
                + 3 * (1 - t) ** 2 * t * cp1_y
                + 3 * (1 - t) * t ** 2 * cp2_y
                + t ** 3 * ey
            )

            # Add jitter (stronger in middle, weaker at endpoints)
            if jitter > 0 and 0 < i < steps:
                # Bell curve: max at t=0.5, zero at t=0 and t=1
                intensity = math.sin(t * math.pi) * jitter
                x += random.gauss(0, intensity)
                y += random.gauss(0, intensity)

            points.append((x, y))

        # Micro-hesitation: 5% chance to pause in the middle
        if random.random() < 0.05 and len(points) > 10:
            mid_idx = len(points) // 2
            pause_point = points[mid_idx]
            # Insert duplicate point (will cause a pause)
            points.insert(mid_idx, pause_point)
            points.insert(mid_idx, pause_point)

        # Overshoot: 12% chance to overshoot then correct
        if random.random() < 0.12 and distance > 50:
            overshoot_dist = random.uniform(5, 15)
            angle = math.atan2(ey - sy, ex - sx)
            ox = ex + math.cos(angle) * overshoot_dist
            oy = ey + math.sin(angle) * overshoot_dist
            points.append((ox, oy))
            # Correct back
            correction_steps = random.randint(3, 6)
            for i in range(1, correction_steps + 1):
                t = i / correction_steps
                cx = ox + (ex - ox) * t
                cy = oy + (ey - oy) * t
                points.append((cx, cy))

        # Ensure last point is exactly the target
        points[-1] = end
        return points

    @staticmethod
    def calculate_steps(distance: float, duration: float = None) -> int:
        """Calculate the number of interpolation steps from distance.

        Longer distances produce more steps (sub-linear scaling).
        If ``duration`` is provided, calculates steps at ~60 FPS.

        Args:
            distance: Distance in pixels between start and end.
            duration: Optional movement duration in seconds. If
                provided, overrides distance-based calculation.

        Returns:
            Number of interpolation steps (minimum 5).
        """
        if duration is not None:
            return max(5, int(duration * 60))

        if distance < 50:
            return random.randint(8, 15)
        elif distance < 200:
            return random.randint(15, 30)
        elif distance < 500:
            return random.randint(25, 50)
        else:
            return random.randint(40, 70)

    @staticmethod
    def calculate_duration(distance: float) -> float:
        """Estimate human-like movement duration from distance.

        Based on Fitts's Law approximation: longer distances take
        proportionally more time, but with diminishing returns.

        Args:
            distance: Distance in pixels.

        Returns:
            Duration in seconds.
        """
        if distance < 50:
            return random.uniform(0.1, 0.2)
        elif distance < 200:
            return random.uniform(0.2, 0.4)
        elif distance < 500:
            return random.uniform(0.3, 0.6)
        else:
            return random.uniform(0.5, 0.9)
