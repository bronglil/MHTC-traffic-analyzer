"""Data passed between pipeline stages.

Detection -> Tracking -> ROI analysis -> Counting -> Reporting each consume the
output of the previous stage only, which keeps stages independently testable
and replaceable.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(slots=True)
class Frame:
    index: int  # index in the source video
    timestamp: float  # seconds from start of video
    image: np.ndarray  # BGR


@dataclass(slots=True)
class Detection:
    """One object detected in one frame (pixel coordinates)."""

    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    vehicle_type: str


@dataclass(slots=True)
class TrackedObject:
    """A detection associated with a persistent track id."""

    track_id: int
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    vehicle_type: str

    @property
    def bottom_center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, self.y2)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)
