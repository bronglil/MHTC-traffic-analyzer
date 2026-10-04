"""Small, dependency-free 2D geometry helpers."""

from __future__ import annotations

import math
from collections.abc import Sequence

Point = tuple[float, float]


def point_in_polygon(pt: Point, polygon: Sequence[Point]) -> bool:
    """Ray-casting test; points exactly on an edge may fall either way."""
    x, y = pt
    inside = False
    n = len(polygon)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def cross(o: Point, a: Point, b: Point) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def segments_intersect(p1: Point, p2: Point, q1: Point, q2: Point) -> bool:
    """Proper or touching intersection of segments p1p2 and q1q2."""
    d1 = cross(q1, q2, p1)
    d2 = cross(q1, q2, p2)
    d3 = cross(p1, p2, q1)
    d4 = cross(p1, p2, q2)
    if ((d1 > 0 > d2) or (d1 < 0 < d2)) and ((d3 > 0 > d4) or (d3 < 0 < d4)):
        return True

    def on_segment(a: Point, b: Point, c: Point) -> bool:
        return min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= c[1] <= max(a[1], b[1])

    return (
        (d1 == 0 and on_segment(q1, q2, p1))
        or (d2 == 0 and on_segment(q1, q2, p2))
        or (d3 == 0 and on_segment(p1, p2, q1))
        or (d4 == 0 and on_segment(p1, p2, q2))
    )


def side_of_line(pt: Point, a: Point, b: Point) -> int:
    """+1 / -1 for the two sides of line a->b, 0 when on the line."""
    c = cross(a, b, pt)
    return (c > 0) - (c < 0)


COMPASS_8 = ["E", "NE", "N", "NW", "W", "SW", "S", "SE"]


def compass_direction(start: Point, end: Point) -> str:
    """8-way heading in *image* space: N = towards the top of the frame."""
    dx = end[0] - start[0]
    dy = start[1] - end[1]  # image y grows downwards
    angle = math.degrees(math.atan2(dy, dx)) % 360.0
    return COMPASS_8[int(((angle + 22.5) % 360.0) // 45.0)]
