"""Vehicle detection stage."""

from __future__ import annotations

from typing import Protocol

import numpy as np

from app.pipeline.types import Detection
from app.vehicles import to_vehicle_type


class Detector(Protocol):
    def detect(self, image: np.ndarray) -> list[Detection]: ...


class YoloDetector:
    """Ultralytics YOLO detector restricted to vehicle classes.

    Works with any YOLO checkpoint (``yolov8n.pt``, ``yolo11s.pt``, or a custom
    model with e.g. ``lgv1``/``lgv2`` classes); class names are mapped to
    canonical vehicle types via :mod:`app.vehicles`. Oriented-bounding-box
    (``-obb``) models are supported; their boxes are converted to upright ones.
    """

    def __init__(
        self,
        model_path: str = "yolo11n.pt",
        confidence: float = 0.3,
        iou: float = 0.5,
        image_size: int = 640,
        device: str | None = None,
        tiles: int = 1,
        tile_overlap: float = 0.2,
    ) -> None:
        from ultralytics import YOLO  # heavy import, deferred

        self.model = YOLO(model_path)
        self.confidence = confidence
        self.iou = iou
        self.image_size = image_size
        self.device = device or None
        # Sliced inference (SAHI, Akyon et al. 2022): also detect on an n x n grid of
        # overlapping tiles so small / distant vehicles are larger in the model input.
        self.tiles = max(1, int(tiles))
        self.tile_overlap = tile_overlap
        names = self.model.names  # {id: name}
        self._class_map = {i: vt for i, n in names.items() if (vt := to_vehicle_type(n)) is not None}
        if not self._class_map:
            raise ValueError(f"Model {model_path!r} has no recognised vehicle classes: {list(names.values())}")

    def _predict(self, images: list[np.ndarray]) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
        results = self.model.predict(
            images,
            conf=self.confidence,
            iou=self.iou,
            imgsz=self.image_size,
            classes=list(self._class_map),
            device=self.device,
            verbose=False,
        )
        out = []
        for result in results:
            boxes = result.boxes if result.boxes is not None else result.obb
            if boxes is None or len(boxes) == 0:
                out.append((np.zeros((0, 4)), np.zeros(0), np.zeros(0, dtype=int)))
                continue
            out.append((boxes.xyxy.cpu().numpy(), boxes.conf.cpu().numpy(), boxes.cls.cpu().numpy().astype(int)))
        return out

    def _tiles(self, h: int, w: int) -> list[tuple[int, int, int, int]]:
        n = self.tiles
        tw, th = int(w / (n - (n - 1) * self.tile_overlap)), int(h / (n - (n - 1) * self.tile_overlap))
        xs = np.linspace(0, w - tw, n).astype(int)
        ys = np.linspace(0, h - th, n).astype(int)
        return [(x, y, x + tw, y + th) for y in ys for x in xs]

    def detect(self, image: np.ndarray) -> list[Detection]:
        h, w = image.shape[:2]
        regions = [(0, 0, w, h)] + (self._tiles(h, w) if self.tiles > 1 else [])
        crops = [image] + [image[y1:y2, x1:x2] for x1, y1, x2, y2 in regions[1:]]
        boxes, confs, classes = [], [], []
        for (ox, oy, rx2, ry2), (xyxy, conf, cls) in zip(regions, self._predict(crops), strict=True):
            for b, c, k in zip(xyxy, conf, cls, strict=True):
                if k not in self._class_map:
                    continue
                bx1, by1, bx2, by2 = b[0] + ox, b[1] + oy, b[2] + ox, b[3] + oy
                if (ox, oy) != (0, 0) or (rx2, ry2) != (w, h):
                    # Drop tile detections cut by an inner tile edge (the full frame or a
                    # neighbouring tile sees that vehicle whole).
                    m = 2
                    if (bx1 <= ox + m and ox > 0) or (by1 <= oy + m and oy > 0) \
                            or (bx2 >= rx2 - m and rx2 < w) or (by2 >= ry2 - m and ry2 < h):
                        continue
                boxes.append([bx1, by1, bx2, by2])
                confs.append(float(c))
                classes.append(int(k))
        if not boxes:
            return []
        keep = list(range(len(boxes)))
        if len(regions) > 1:
            import cv2

            xywh = [[b[0], b[1], b[2] - b[0], b[3] - b[1]] for b in boxes]
            keep = [int(i) for i in np.array(cv2.dnn.NMSBoxes(xywh, confs, 0.0, 0.5)).reshape(-1)]
        return [
            Detection(float(boxes[i][0]), float(boxes[i][1]), float(boxes[i][2]), float(boxes[i][3]), confs[i],
                      self._class_map[classes[i]])
            for i in keep
        ]


class MotionDetector:
    """Background-subtraction detector for fixed cameras (no neural network).

    Finds moving blobs with OpenCV MOG2. It works from any camera angle, including
    overhead views where COCO-trained YOLO models fail, but it cannot tell vehicle
    types apart: every blob is labelled ``label`` (refine with the size heuristic
    or a crop classifier). Blobs from vehicles that touch or overlap merge.
    """

    def __init__(
        self,
        min_area_fraction: float = 0.002,
        history: int = 300,
        var_threshold: float = 32.0,
        warmup_frames: int = 5,
        merge_gap_fraction: float = 0.1,
        label: str = "car",
    ) -> None:
        import cv2

        self._cv2 = cv2
        self._bg = cv2.createBackgroundSubtractorMOG2(history=history, varThreshold=var_threshold, detectShadows=True)
        self.min_area_fraction = min_area_fraction
        self.warmup = warmup_frames
        self.label = label
        self.merge_gap = merge_gap_fraction
        self._frames = 0
        self._open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        self._close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))

    def detect(self, image: np.ndarray) -> list[Detection]:
        cv2 = self._cv2
        mask = self._bg.apply(image)
        self._frames += 1
        if self._frames <= self.warmup:
            return []
        _, mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)  # drop shadows (127)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._open)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._close)
        h, w = mask.shape[:2]
        min_area = self.min_area_fraction * w * h
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = [list(cv2.boundingRect(c)) + [cv2.contourArea(c)] for c in contours]
        boxes = [[x, y, x + bw, y + bh, a] for x, y, bw, bh, a in boxes if a >= min_area / 4]
        boxes = _merge_nearby(boxes, self.merge_gap)
        out = []
        for x1, y1, x2, y2, area in boxes:
            if area < min_area:
                continue
            fill = area / max(1.0, (x2 - x1) * (y2 - y1))
            out.append(Detection(float(x1), float(y1), float(x2), float(y2), float(min(0.99, 0.5 + fill / 2)),
                                 self.label))
        return out


def _merge_nearby(boxes: list[list[float]], gap_fraction: float) -> list[list[float]]:
    """Merge boxes that overlap or nearly touch: one vehicle often yields several
    blobs (windscreen, roof, shadow edges)."""
    boxes = [b[:] for b in boxes]
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                gap = gap_fraction * max(a[2] - a[0], a[3] - a[1], b[2] - b[0], b[3] - b[1])
                if a[0] - gap <= b[2] and b[0] - gap <= a[2] and a[1] - gap <= b[3] and b[1] - gap <= a[3]:
                    boxes[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]), a[4] + b[4]]
                    del boxes[j]
                    merged = True
                    break
            if merged:
                break
    return boxes


DETECTOR_TYPES = ("yolo", "motion")
