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


def _measured_fps(cap: cv2.VideoCapture, samples: int = 30) -> float | None:
    """Frame rate from the decoded frames' presentation timestamps."""
    stamps = []
    for _ in range(samples + 1):
        if not cap.grab():
            break
        stamps.append(cap.get(cv2.CAP_PROP_POS_MSEC))
    if len(stamps) < 4 or stamps[-1] <= stamps[0]:
        return None
    # Average over the whole span: per-frame stamps are often rounded to whole ms.
    return 1000.0 * (len(stamps) - 1) / (stamps[-1] - stamps[0])


def probe(path: str) -> VideoInfo:
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise VideoReadError(f"Cannot open video: {path}")
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if width <= 0 or height <= 0:
            ok, img = cap.read()
            if not ok:
                raise VideoReadError(f"Video has no readable frames: {path}")
            height, width = img.shape[:2]
        if not 1.0 <= fps <= 240.0:
            # e.g. WebM/Matroska with a 1 ms timebase: OpenCV reports 1000 "fps" and a
            # frame count in milliseconds. Use the real frame spacing instead.
            duration = count / fps if fps > 0 and count > 0 else 0.0
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            real = _measured_fps(cap)
            fps = real if real and 1.0 <= real <= 240.0 else 25.0
            count = int(round(duration * fps)) if duration else 0
        return VideoInfo(width=width, height=height, fps=fps, frame_count=max(count, 0))
    finally:
        cap.release()


def iter_frames(
    path: str, stride: int = 1, fps: float | None = None, start_frame: int = 0, end_frame: int | None = None
) -> Iterator[Frame]:
    """Yield every ``stride``-th frame from ``start_frame`` up to (excluding)
    ``end_frame``. Frames are decoded sequentially (grab() for skipped frames),
    which is far more reliable than seeking; only the jump to ``start_frame``
    seeks, and it is verified against the decoder's reported position."""
    stride = max(1, int(stride))
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise VideoReadError(f"Cannot open video: {path}")
    fps = fps or float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
    index = 0
    if start_frame > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        index = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        if index != start_frame:  # seek not supported/accurate: decode up to the start instead
            cap.release()
            cap = cv2.VideoCapture(path)
            index = 0
            while index < start_frame and cap.grab():
                index += 1
    first = index
    try:
        while end_frame is None or index < end_frame:
            if (index - first) % stride == 0:
                ok, img = cap.read()
                if not ok:
                    break
                yield Frame(index=index, timestamp=index / fps, image=img)
            elif not cap.grab():
                break
            index += 1
    finally:
        cap.release()
