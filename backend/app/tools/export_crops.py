"""Build a vehicle-classification dataset from your own footage.

Runs detection + tracking over one or more videos and saves the best few crops
of every tracked vehicle into a folder per *suggested* class::

    out/
      _unsorted/car/<video>_t12_f0450.jpg
      _unsorted/lgv2/...
      _unsorted/truck/...

A person then moves each image into the correct final folder
(``car/``, ``lgv1/``, ``lgv2/``, ``truck/``, ``bus/``, ``motorcycle/``,
``bicycle/``), split into ``train/`` and ``val/``, and trains a classifier::

    yolo classify train data=out model=yolo11s-cls.pt imgsz=224 epochs=50

Copy the resulting ``best.pt`` into the server's models directory and select
"Custom classification model" in the UI (or set ``TV_CLASSIFIER_MODEL``).

Usage::

    python -m app.tools.export_crops survey1.mp4 survey2.mp4 --out dataset --stride 2
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import cv2

from app.pipeline.classifier import SizeHeuristicRefiner
from app.pipeline.detector import MotionDetector, YoloDetector
from app.pipeline.frames import iter_frames, probe
from app.pipeline.tracker import create_tracker


def export(video: Path, out: Path, detector, crops_per_track: int, stride: int, min_size: int, pad: float) -> int:
    info = probe(str(video))
    tracker = create_tracker("bytetrack", info.fps / stride, 0.3)
    refiner = SizeHeuristicRefiner(info.height)
    best: dict[int, list[tuple[float, int, object, str]]] = defaultdict(list)
    for frame in iter_frames(str(video), stride=stride, fps=info.fps):
        tracked = refiner.refine(tracker.update(detector.detect(frame.image), frame.image), frame.image)
        h, w = frame.image.shape[:2]
        for o in tracked:
            bw, bh = o.x2 - o.x1, o.y2 - o.y1
            if min(bw, bh) < min_size:
                continue
            # Prefer large, fully visible crops: score by area, penalise touching the border.
            touching = o.x1 <= 2 or o.y1 <= 2 or o.x2 >= w - 2 or o.y2 >= h - 2
            score = bw * bh * (0.3 if touching else 1.0) * o.confidence
            x1, y1 = int(max(0, o.x1 - pad * bw)), int(max(0, o.y1 - pad * bh))
            x2, y2 = int(min(w, o.x2 + pad * bw)), int(min(h, o.y2 + pad * bh))
            entry = (score, frame.index, frame.image[y1:y2, x1:x2].copy(), o.vehicle_type)
            items = best[o.track_id]
            items.append(entry)
            items.sort(key=lambda e: -e[0])
            del items[crops_per_track:]
    saved = 0
    for tid, items in best.items():
        for _, frame_index, crop, vtype in items:
            d = out / "_unsorted" / vtype
            d.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(d / f"{video.stem}_t{tid}_f{frame_index:06d}.jpg"), crop)
            saved += 1
    return saved


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("videos", nargs="+", type=Path)
    p.add_argument("--out", type=Path, default=Path("vehicle_dataset"))
    p.add_argument("--detector", choices=["yolo", "motion"], default="yolo")
    p.add_argument("--model", default="yolo11s.pt", help="YOLO detector weights")
    p.add_argument("--crops-per-track", type=int, default=3)
    p.add_argument("--stride", type=int, default=2)
    p.add_argument("--min-size", type=int, default=32, help="Skip crops smaller than this (pixels)")
    p.add_argument("--pad", type=float, default=0.05, help="Context padding around each box (fraction)")
    args = p.parse_args(argv)

    detector = MotionDetector() if args.detector == "motion" else YoloDetector(args.model, confidence=0.1)
    total = 0
    for v in args.videos:
        n = export(v, args.out, detector, args.crops_per_track, args.stride, args.min_size, args.pad)
        print(f"{v}: {n} crops")
        total += n
    print(f"Saved {total} crops under {args.out / '_unsorted'} — sort them into class folders before training.")


if __name__ == "__main__":
    main()
