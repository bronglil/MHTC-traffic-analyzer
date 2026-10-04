"""Multi-object tracking stage.

Trackers assign persistent ids to detections across frames, which is what
prevents a vehicle visible in hundreds of frames from being counted hundreds
of times.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from app.pipeline.types import Detection, TrackedObject

TRACKER_TYPES = ("bytetrack", "botsort", "iou")


class Tracker(Protocol):
    def update(self, detections: list[Detection], image: np.ndarray) -> list[TrackedObject]: ...


class _DetBatch:
    """Duck-typed stand-in for ultralytics ``Boxes`` as consumed by its trackers."""

    def __init__(self, xyxy: np.ndarray, conf: np.ndarray, cls: np.ndarray) -> None:
        self.xyxy = xyxy
        self.conf = conf
        self.cls = cls

    @property
    def xywh(self) -> np.ndarray:
        out = self.xyxy.copy()
        out[:, 2] = self.xyxy[:, 2] - self.xyxy[:, 0]
        out[:, 3] = self.xyxy[:, 3] - self.xyxy[:, 1]
        out[:, 0] = self.xyxy[:, 0] + out[:, 2] / 2
        out[:, 1] = self.xyxy[:, 1] + out[:, 3] / 2
        return out

    def __len__(self) -> int:
        return len(self.conf)

    def __getitem__(self, idx) -> _DetBatch:
        return _DetBatch(self.xyxy[idx], self.conf[idx], self.cls[idx])


class UltralyticsTracker:
    """ByteTrack or BoT-SORT, using the implementations shipped with ultralytics."""

    def __init__(self, kind: str = "bytetrack", frame_rate: float = 30.0, confidence: float | None = None) -> None:
        from ultralytics.trackers.bot_sort import BOTSORT
        from ultralytics.trackers.byte_tracker import BYTETracker
        from ultralytics.utils import IterableSimpleNamespace, YAML
        from ultralytics.utils.checks import check_yaml

        if kind not in ("bytetrack", "botsort"):
            raise ValueError(f"Unknown tracker {kind!r}")
        cfg = YAML.load(check_yaml(f"{kind}.yaml"))
        # Detections come from our own detector, so appearance ReID via the
        # YOLO model is not available; BoT-SORT still adds camera-motion comp.
        cfg["with_reid"] = False
        if confidence is not None:
            # The detector runs with a low threshold so ByteTrack's second
            # association stage can use weak boxes; `confidence` gates which
            # detections may start or strongly match a track.
            cfg["track_high_thresh"] = confidence
            cfg["new_track_thresh"] = confidence
        fps = max(1, round(frame_rate))
        cls = BYTETracker if kind == "bytetrack" else BOTSORT
        try:  # ultralytics < 8.4 takes frame_rate and scales the buffer itself
            self._tracker = cls(args=IterableSimpleNamespace(**cfg), frame_rate=fps)
        except TypeError:
            cfg["track_buffer"] = max(1, round(cfg["track_buffer"] * fps / 30))
            self._tracker = cls(IterableSimpleNamespace(**cfg))
        self._types: list[str] = []

    def update(self, detections: list[Detection], image: np.ndarray) -> list[TrackedObject]:
        self._types = sorted(set(self._types) | {d.vehicle_type for d in detections})
        type_idx = {t: i for i, t in enumerate(self._types)}
        if detections:
            xyxy = np.array([[d.x1, d.y1, d.x2, d.y2] for d in detections], dtype=np.float32)
            conf = np.array([d.confidence for d in detections], dtype=np.float32)
            cls = np.array([type_idx[d.vehicle_type] for d in detections], dtype=np.float32)
        else:
            xyxy = np.zeros((0, 4), dtype=np.float32)
            conf = np.zeros((0,), dtype=np.float32)
            cls = np.zeros((0,), dtype=np.float32)
        out = self._tracker.update(_DetBatch(xyxy, conf, cls), image)
        results = []
        for row in out:
            x1, y1, x2, y2, tid, score, c = row[:7]
            results.append(
                TrackedObject(int(tid), float(x1), float(y1), float(x2), float(y2), float(score), self._types[int(c)])
            )
        return results


def _iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / np.maximum(area_a[:, None] + area_b[None, :] - inter, 1e-9)


class IoUTracker:
    """Minimal greedy IoU tracker with no heavy dependencies.

    Useful for tests and very low-resource environments; prefer ByteTrack or
    BoT-SORT for real footage.
    """

    def __init__(self, iou_threshold: float = 0.3, max_age: int = 30, confidence: float = 0.0) -> None:
        self.iou_threshold = iou_threshold
        self.confidence = confidence
        self.max_age = max_age
        self._next_id = 1
        self._tracks: dict[int, tuple[np.ndarray, int]] = {}  # id -> (box, age)

    def update(self, detections: list[Detection], image: np.ndarray | None = None) -> list[TrackedObject]:
        detections = [d for d in detections if d.confidence >= self.confidence]
        ids = list(self._tracks)
        prev = np.array([self._tracks[i][0] for i in ids]).reshape(-1, 4)
        cur = np.array([[d.x1, d.y1, d.x2, d.y2] for d in detections]).reshape(-1, 4)
        iou = _iou_matrix(prev, cur)
        assigned: dict[int, int] = {}
        used_tracks: set[int] = set()
        for flat in np.argsort(-iou, axis=None):
            ti, di = divmod(int(flat), max(len(detections), 1))
            if iou.size == 0 or iou[ti, di] < self.iou_threshold:
                break
            if ti in used_tracks or di in assigned:
                continue
            assigned[di] = ids[ti]
            used_tracks.add(ti)

        out: list[TrackedObject] = []
        seen: set[int] = set()
        for di, d in enumerate(detections):
            tid = assigned.get(di)
            if tid is None:
                tid = self._next_id
                self._next_id += 1
            self._tracks[tid] = (cur[di], 0)
            seen.add(tid)
            out.append(TrackedObject(tid, d.x1, d.y1, d.x2, d.y2, d.confidence, d.vehicle_type))
        for tid in list(self._tracks):
            if tid not in seen:
                box, age = self._tracks[tid]
                if age + 1 > self.max_age:
                    del self._tracks[tid]
                else:
                    self._tracks[tid] = (box, age + 1)
        return out


def create_tracker(kind: str, frame_rate: float, confidence: float) -> Tracker:
    if kind == "iou":
        return IoUTracker(max_age=max(1, round(frame_rate)), confidence=confidence)
    return UltralyticsTracker(kind, frame_rate, confidence)
