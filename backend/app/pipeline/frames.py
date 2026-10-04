"""Video probing and frame extraction (OpenCV)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import cv2

from app.pipeline.types import Frame


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    fps: float
    frame_count: int

    @property
    def duration(self) -> float:
        return self.frame_count / self.fps if self.fps else 0.0


class VideoReadError(RuntimeError):
    pass


def probe(path: str) -> VideoInfo:
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise VideoReadError(f"Cannot open video: {path}")
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if width <= 0 or height <= 0:
            ok, img = cap.read()
            if not ok:
                raise VideoReadError(f"Video has no readable frames: {path}")
            height, width = img.shape[:2]
        return VideoInfo(width=width, height=height, fps=fps, frame_count=max(count, 0))
    finally:
        cap.release()


def iter_frames(path: str, stride: int = 1, fps: float | None = None) -> Iterator[Frame]:
    """Yield every ``stride``-th frame. Frames are decoded sequentially (grab()
    for skipped frames) which is far more reliable than seeking."""
    stride = max(1, int(stride))
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise VideoReadError(f"Cannot open video: {path}")
    fps = fps or float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
    index = 0
    try:
        while True:
            if index % stride == 0:
                ok, img = cap.read()
                if not ok:
                    break
                yield Frame(index=index, timestamp=index / fps, image=img)
            elif not cap.grab():
                break
            index += 1
    finally:
        cap.release()
