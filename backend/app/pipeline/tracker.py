"""Multi-object tracking stage.

Trackers assign persistent ids to detections across frames, which is what
prevents a vehicle visible in hundreds of frames from being counted hundreds
of times.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from app.pipeline.types import Detection, TrackedObject

TRACKER_TYPES = ("bytetrack", "botsort", "iou", "timelapse")


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
    """ByteTrack or BoT-SORT, using the implementations shipped with ultralytics.

    ``buffer`` enlarges every box by that fraction of its size on each side before
    matching and shrinks the tracker's output back (buffered IoU, Yang et al. 2023,
    "Hard to Track Objects with Irregular Motions and Similar Appearances? Make It
    Easier by Buffering the Matching Space"). When frames are skipped a vehicle can
    move more than its own length between analysed frames, so plain boxes stop
    overlapping and tracks break; buffered boxes still overlap.
    """

    def __init__(self, kind: str = "bytetrack", frame_rate: float = 30.0, confidence: float | None = None,
                 buffer: float = 0.0) -> None:
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
        self.buffer = max(0.0, buffer)

    def update(self, detections: list[Detection], image: np.ndarray) -> list[TrackedObject]:
        self._types = sorted(set(self._types) | {d.vehicle_type for d in detections})
        type_idx = {t: i for i, t in enumerate(self._types)}
        if detections:
            xyxy = np.array([[d.x1, d.y1, d.x2, d.y2] for d in detections], dtype=np.float32)
            conf = np.array([d.confidence for d in detections], dtype=np.float32)
            cls = np.array([type_idx[d.vehicle_type] for d in detections], dtype=np.float32)
            if self.buffer:
                wh = (xyxy[:, 2:] - xyxy[:, :2]) * self.buffer
                xyxy = np.concatenate([xyxy[:, :2] - wh, xyxy[:, 2:] + wh], axis=1)
        else:
            xyxy = np.zeros((0, 4), dtype=np.float32)
            conf = np.zeros((0,), dtype=np.float32)
            cls = np.zeros((0,), dtype=np.float32)
        out = self._tracker.update(_DetBatch(xyxy, conf, cls), image)
        results = []
        for row in out:
            x1, y1, x2, y2, tid, score, c = row[:7]
            if self.buffer:  # undo the buffering: w_out = w * (1 + 2b) around the same centre
                k = self.buffer / (1 + 2 * self.buffer)
                bw, bh = (x2 - x1) * k, (y2 - y1) * k
                x1, y1, x2, y2 = x1 + bw, y1 + bh, x2 - bw, y2 - bh
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


class TimelapseTracker:
    """Tracker for time-lapse / very low frame-rate footage.

    Between two time-lapse frames a vehicle can move several times its own
    length, so box overlap (IoU) and Kalman motion models — what ByteTrack and
    BoT-SORT rely on — no longer connect it. This tracker matches by position
    with a wide search radius (relative to the vehicle's size, around a
    constant-velocity prediction) combined with appearance (colour
    histogram), solved as an optimal assignment.
    """

    def __init__(self, confidence: float = 0.3, max_age: int = 2, gate: float = 3.0,
                 appearance_weight: float = 0.5, max_cost: float = 0.75) -> None:
        import cv2

        self._cv2 = cv2
        self.confidence = confidence
        self.max_age = max_age
        self.gate = gate
        self.w = appearance_weight
        self.max_cost = max_cost
        self._next_id = 1
        # id -> dict(center, vel, diag, hist, age, type)
        self._tracks: dict[int, dict] = {}

    def _hist(self, image: np.ndarray | None, d: Detection) -> np.ndarray | None:
        if image is None:
            return None
        cv2 = self._cv2
        h, w = image.shape[:2]
        x1, y1, x2, y2 = max(0, int(d.x1)), max(0, int(d.y1)), min(w, int(d.x2)), min(h, int(d.y2))
        if x2 - x1 < 4 or y2 - y1 < 4:
            return None
        hsv = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256])
        return cv2.normalize(hist, hist).flatten()

    def update(self, detections: list[Detection], image: np.ndarray | None = None) -> list[TrackedObject]:
        import lap

        dets = [d for d in detections if d.confidence >= self.confidence]
        centers = [((d.x1 + d.x2) / 2, (d.y1 + d.y2) / 2) for d in dets]
        diags = [max(1.0, ((d.x2 - d.x1) ** 2 + (d.y2 - d.y1) ** 2) ** 0.5) for d in dets]
        hists = [self._hist(image, d) for d in dets]
        ids = list(self._tracks)
        assigned: dict[int, int] = {}
        if ids and dets:
            big = 1e6
            cost = np.full((len(ids), len(dets)), big)
            for i, tid in enumerate(ids):
                t = self._tracks[tid]
                steps = t["age"] + 1
                px, py = t["center"][0] + t["vel"][0] * steps, t["center"][1] + t["vel"][1] * steps
                for j, d in enumerate(dets):
                    scale = max(t["diag"], diags[j])
                    dist = ((centers[j][0] - px) ** 2 + (centers[j][1] - py) ** 2) ** 0.5 / scale
                    if dist > self.gate or max(t["diag"], diags[j]) > 2.5 * min(t["diag"], diags[j]):
                        continue
                    app = 0.5
                    if t["hist"] is not None and hists[j] is not None:
                        corr = float(self._cv2.compareHist(t["hist"], hists[j], self._cv2.HISTCMP_CORREL))
                        app = min(1.0, max(0.0, 1.0 - corr))
                    c = (1 - self.w) * dist / self.gate + self.w * app
                    if c <= self.max_cost:
                        cost[i, j] = c
            _, rows, _ = lap.lapjv(cost, extend_cost=True, cost_limit=self.max_cost)
            for i, j in enumerate(rows):
                if j >= 0 and cost[i, j] < big:
                    assigned[j] = ids[i]

        out: list[TrackedObject] = []
        seen: set[int] = set()
        for j, d in enumerate(dets):
            tid = assigned.get(j)
            if tid is None:
                tid = self._next_id
                self._next_id += 1
                self._tracks[tid] = {"center": centers[j], "vel": (0.0, 0.0), "diag": diags[j], "hist": hists[j],
                                     "age": 0}
            else:
                t = self._tracks[tid]
                steps = t["age"] + 1
                vel = ((centers[j][0] - t["center"][0]) / steps, (centers[j][1] - t["center"][1]) / steps)
                t.update(center=centers[j], vel=vel, diag=diags[j], age=0,
                         hist=hists[j] if hists[j] is not None else t["hist"])
            seen.add(tid)
            out.append(TrackedObject(tid, d.x1, d.y1, d.x2, d.y2, d.confidence, d.vehicle_type))
        for tid in list(self._tracks):
            if tid not in seen:
                self._tracks[tid]["age"] += 1
                if self._tracks[tid]["age"] > self.max_age:
                    del self._tracks[tid]
        return out


def create_tracker(kind: str, frame_rate: float, confidence: float, buffer: float = 0.0) -> Tracker:
    """``buffer``: box enlargement for matching (ByteTrack / BoT-SORT), see UltralyticsTracker."""
    if kind == "timelapse":
        return TimelapseTracker(confidence=confidence)
    if kind == "iou":
        return IoUTracker(max_age=max(1, round(frame_rate)), confidence=confidence)
    return UltralyticsTracker(kind, frame_rate, confidence, buffer)
