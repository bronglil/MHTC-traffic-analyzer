"""Black-and-white frame difference: did the picture itself move.

Road colour says which road a vehicle's base is on. Movement is a change in
brightness between the two analysed frames. The check uses the base and the
whole box, because a vehicle driving straight down the road keeps the middle
of the box the same colour while its edges change.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.pipeline.types import TrackedObject

# A pixel counts as changed once it differs by this much (0–255).
DIFF_THRESHOLD = 16
# Share of the base band that must change. A slow vehicle only refreshes its
# leading edge, so this stays small. Compression noise stays under it.
DIFF_FRACTION = 0.06


def to_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _slice_changed(prev_gray: np.ndarray, gray: np.ndarray, x1: float, y1: float, x2: float, y2: float) -> bool:
    height, width = gray.shape[:2]
    ix1 = int(np.clip(min(x1, x2), 0, width))
    ix2 = int(np.clip(max(x1, x2), 0, width))
    iy1 = int(np.clip(min(y1, y2), 0, height))
    iy2 = int(np.clip(max(y1, y2), 0, height))
    if ix2 - ix1 < 2 or iy2 - iy1 < 2:
        return False
    diff = cv2.absdiff(prev_gray[iy1:iy2, ix1:ix2], gray[iy1:iy2, ix1:ix2])
    return float((diff >= DIFF_THRESHOLD).mean()) >= DIFF_FRACTION


def base_changed(prev_gray: np.ndarray, gray: np.ndarray, obj: TrackedObject, anchor: str = "bottom_center") -> bool:
    """True when the black-and-white picture changed for this vehicle.

    The base band is where the vehicle meets the road. A vehicle driving
    straight along the road can keep that band the same colour, so the whole
    box is checked as well: the leading and trailing edges are what change.
    """
    if prev_gray.shape != gray.shape:
        return False
    box_h = max(1.0, obj.y2 - obj.y1)
    band = max(4.0, 0.2 * box_h)
    contact = (obj.y1 + obj.y2) / 2.0 if anchor == "center" else obj.y2
    if anchor == "center":
        y1, y2 = contact - band / 2.0, contact + band / 2.0
    else:
        y1, y2 = contact - band, contact
    return _slice_changed(prev_gray, gray, obj.x1, y1, obj.x2, y2) or _slice_changed(
        prev_gray, gray, obj.x1, obj.y1, obj.x2, obj.y2
    )
