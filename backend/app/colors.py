"""Display colours shared by the API (assigned to new regions) and the renderer."""

# Distinct, saturated hues for user-drawn areas and lines, in assignment order.
REGION_COLORS = ["#f59e0b", "#06b6d4", "#a855f7", "#84cc16", "#ec4899", "#3b82f6", "#ef4444", "#14b8a6"]
WHOLE_FRAME_COLOR = "#e5e7eb"


def next_region_color(used: list[str | None]) -> str:
    """First palette colour not already used by the video's regions."""
    taken = {c.lower() for c in used if c}
    for c in REGION_COLORS:
        if c not in taken:
            return c
    return REGION_COLORS[len(used) % len(REGION_COLORS)]


def hex_to_bgr(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)
