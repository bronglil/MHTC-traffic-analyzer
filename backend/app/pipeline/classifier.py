"""Vehicle classification stage (runs after tracking, before ROI analysis).

The detector gives a coarse class per box. Traffic surveys need finer classes
than generic detectors provide — in particular LGV1 (small car-derived vans)
vs LGV2 (large vans), which COCO models cannot see at all (they label vans as
"car" or "truck"). This stage refines the class **per track**, so evidence is
accumulated across many frames of the same vehicle rather than decided from a
single frame.

Refiners, best first:

1. ``CropClassifierRefiner`` — a YOLO *classification* model trained on crops
   of your own footage (classes e.g. car / lgv1 / lgv2 / truck / bus ...). Most
   accurate; see docs/vehicle-classification.md for how to build one.
2. ``SizeHeuristicRefiner`` — no extra model. Learns how big a car appears at
   each image row (perspective) from confidently detected cars, then uses each
   track's size relative to that to split van/truck/car detections into
   LGV1 / LGV2 / truck. Approximate: it cannot tell a small van from a car of
   the same size, so LGV1 recall depends on the detector emitting "van".

A detector trained directly on lgv1/lgv2 classes needs no refiner at all.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import replace
from typing import Protocol

import numpy as np

from app.pipeline.types import TrackedObject
from app.vehicles import UNSPLIT_VAN, to_vehicle_type

REFINABLE = {"car", UNSPLIT_VAN, "lgv1", "lgv2", "truck"}


class ClassRefiner(Protocol):
    def refine(self, objects: list[TrackedObject], image: np.ndarray) -> list[TrackedObject]: ...


class PassThroughRefiner:
    """Keeps detector classes; only resolves an unsplit "van"."""

    def __init__(self, unsplit_van_default: str = "lgv2") -> None:
        self.default = unsplit_van_default

    def refine(self, objects: list[TrackedObject], image: np.ndarray) -> list[TrackedObject]:
        return [replace(o, vehicle_type=self.default) if o.vehicle_type == UNSPLIT_VAN else o for o in objects]


class SizeHeuristicRefiner:
    """Perspective-normalised size rules for car / LGV1 / LGV2 / truck.

    ``ratio`` = (sqrt of box area) / (expected sqrt-area of a car at that image
    row). Thresholds are linear-size ratios and can be calibrated per site.
    """

    def __init__(
        self,
        frame_height: int,
        lgv1_max_ratio: float = 1.25,
        lgv2_max_ratio: float = 1.6,
        car_as_lgv2_min_ratio: float = 1.4,
        min_calibration_samples: int = 15,
        calibration_confidence: float = 0.5,
        unsplit_van_default: str = "lgv2",
    ) -> None:
        self.h = float(max(1, frame_height))
        self.lgv1_max = lgv1_max_ratio
        self.lgv2_max = lgv2_max_ratio
        self.car_lgv2_min = car_as_lgv2_min_ratio
        self.min_samples = min_calibration_samples
        self.calib_conf = calibration_confidence
        self.default = unsplit_van_default
        self._samples: deque[tuple[float, float]] = deque(maxlen=2000)  # (y_norm, sqrt_area)
        self._coef: np.ndarray | None = None
        self._since_fit = 0
        self._ratios: dict[int, deque[float]] = defaultdict(lambda: deque(maxlen=60))

    # -- perspective model ---------------------------------------------------
    def _observe_car(self, o: TrackedObject) -> None:
        self._samples.append((o.y2 / self.h, float(np.sqrt(max(1.0, (o.x2 - o.x1) * (o.y2 - o.y1))))))
        self._since_fit += 1
        if len(self._samples) >= self.min_samples and (self._coef is None or self._since_fit >= 5):
            ys, ss = np.array(self._samples).T
            deg = 1 if np.ptp(ys) > 0.05 else 0  # flat model when all samples sit on one row
            self._coef = np.polyfit(ys, ss, deg)
            self._since_fit = 0

    def expected_car_size(self, y_norm: float) -> float | None:
        if self._coef is None:
            return None
        return float(max(4.0, np.polyval(self._coef, y_norm)))

    # -- classification ------------------------------------------------------
    def _classify(self, detector_type: str, ratio: float) -> str:
        if detector_type in (UNSPLIT_VAN, "lgv1", "lgv2"):
            return "lgv1" if ratio <= self.lgv1_max else "lgv2"
        if detector_type == "truck":
            return "lgv2" if ratio <= self.lgv2_max else "truck"
        if detector_type == "car":
            return "lgv2" if self.car_lgv2_min <= ratio <= self.lgv2_max else "car"
        return detector_type

    def refine(self, objects: list[TrackedObject], image: np.ndarray) -> list[TrackedObject]:
        for o in objects:
            if o.vehicle_type == "car" and o.confidence >= self.calib_conf:
                self._observe_car(o)
        out = []
        for o in objects:
            if o.vehicle_type not in REFINABLE:
                out.append(o)
                continue
            expected = self.expected_car_size(o.y2 / self.h)
            if expected is None:  # not calibrated yet
                out.append(replace(o, vehicle_type=self.default) if o.vehicle_type == UNSPLIT_VAN else o)
                continue
            size = float(np.sqrt(max(1.0, (o.x2 - o.x1) * (o.y2 - o.y1))))
            hist = self._ratios[o.track_id]
            hist.append(size / expected)
            out.append(replace(o, vehicle_type=self._classify(o.vehicle_type, float(np.median(hist)))))
        return out


class CropClassifierRefiner:
    """Classifies vehicle crops with a YOLO classification model, per track.

    Probabilities are summed over up to ``max_samples`` crops per track
    (sampled every ``every_n`` updates), so the decision improves as the
    vehicle approaches the camera and is stable once made.
    """

    def __init__(
        self,
        model_path: str | None = None,
        every_n: int = 3,
        max_samples: int = 15,
        min_crop_size: int = 24,
        device: str | None = None,
        fallback: ClassRefiner | None = None,
        predict_fn=None,
        class_names: Iterable[str] | None = None,
    ) -> None:
        if predict_fn is None:
            from ultralytics import YOLO

            model = YOLO(model_path)
            names = [model.names[i] for i in sorted(model.names)]

            def predict_fn(crops: list[np.ndarray]) -> np.ndarray:
                res = model.predict(crops, device=device, verbose=False)
                return np.stack([r.probs.data.cpu().numpy() for r in res])

            class_names = names
        self._predict = predict_fn
        self._class_types = [to_vehicle_type(n) for n in class_names]
        self.every_n = every_n
        self.max_samples = max_samples
        self.min_crop = min_crop_size
        self.fallback = fallback or PassThroughRefiner()
        self._scores: dict[int, np.ndarray] = {}
        self._samples: dict[int, int] = defaultdict(int)
        self._seen: dict[int, int] = defaultdict(int)

    def _decision(self, track_id: int) -> str | None:
        s = self._scores.get(track_id)
        if s is None:
            return None
        idx = int(np.argmax(s))
        return self._class_types[idx]

    def refine(self, objects: list[TrackedObject], image: np.ndarray) -> list[TrackedObject]:
        h, w = image.shape[:2]
        to_classify: list[tuple[int, np.ndarray]] = []
        for o in objects:
            if o.vehicle_type not in REFINABLE:
                continue
            self._seen[o.track_id] += 1
            if self._samples[o.track_id] >= self.max_samples or (self._seen[o.track_id] - 1) % self.every_n:
                continue
            x1, y1 = max(0, int(o.x1)), max(0, int(o.y1))
            x2, y2 = min(w, int(o.x2)), min(h, int(o.y2))
            if min(x2 - x1, y2 - y1) < self.min_crop:
                continue
            to_classify.append((o.track_id, image[y1:y2, x1:x2]))
        if to_classify:
            probs = self._predict([c for _, c in to_classify])
            for (tid, _), p in zip(to_classify, probs, strict=True):
                weights = np.where([t is not None for t in self._class_types], p, 0.0)
                self._scores[tid] = self._scores.get(tid, 0) + weights
                self._samples[tid] += 1

        base = self.fallback.refine(objects, image)
        out = []
        for o, b in zip(objects, base, strict=True):
            decided = self._decision(o.track_id) if o.vehicle_type in REFINABLE else None
            out.append(replace(o, vehicle_type=decided) if decided and decided != UNSPLIT_VAN else b)
        return out


def create_refiner(
    mode: str,
    frame_height: int,
    classifier_model: str | None = None,
    device: str | None = None,
) -> ClassRefiner:
    """``mode``: "detector" (keep detector classes), "size" (heuristic) or
    "classifier" (crop classifier, falling back to the size heuristic)."""
    if mode == "detector":
        return PassThroughRefiner()
    size = SizeHeuristicRefiner(frame_height)
    if mode == "size":
        return size
    if mode == "classifier":
        if not classifier_model:
            raise ValueError("classification mode 'classifier' needs a classifier model (TV_CLASSIFIER_MODEL)")
        return CropClassifierRefiner(classifier_model, device=device, fallback=size)
    raise ValueError(f"Unknown classification mode {mode!r}")


CLASSIFICATION_MODES = ("size", "detector", "classifier")
