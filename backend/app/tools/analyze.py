"""Analyse a video from the command line and print the counts per road.

Use it to check a video quickly or to compare settings, without the web UI.
Coordinates are pixels of the video frame; ``--grid`` saves a frame with a
labelled pixel grid so you can read them off.

Examples::

    # 1. Save a frame with a coordinate grid to pick the road boxes
    python -m app.tools.analyze traffic.mp4 --grid grid.jpg --at 5

    # 2. Count two roads (a box and a polygon) from 0 to 20 s, save an annotated video
    python -m app.tools.analyze traffic.mp4 \\
        --road "Left carriageway=0,45,595,586" \\
        --polygon "Slip road=790,70;1366,260;1366,430;840,150" \\
        --from 0 --to 20 --annotate counted.mp4

    # In Docker (videos in ./videos are mounted at /videos):
    docker compose run --rm -v "$PWD/videos:/videos" api \\
        python -m app.tools.analyze /videos/traffic.mp4 --road "Box=100,200,400,500"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import cv2

from app.pipeline.classifier import create_refiner
from app.pipeline.detector import MotionDetector, YoloDetector
from app.pipeline.engine import PipelineConfig, RegionDef, run_pipeline
from app.pipeline.frames import probe
from app.pipeline.tracker import create_tracker
from app.vehicles import ALL_VEHICLE_TYPES, VEHICLE_LABELS


def _name_and_numbers(spec: str, flag: str) -> tuple[str, list[float]]:
    if "=" not in spec:
        raise SystemExit(f"{flag}: expected NAME=..., got {spec!r}")
    name, nums = spec.split("=", 1)
    try:
        return name.strip(), [float(v) for v in nums.replace(";", ",").split(",") if v.strip()]
    except ValueError:
        raise SystemExit(f"{flag}: coordinates must be numbers, got {spec!r}") from None


def build_regions(args, width: int, height: int) -> list[RegionDef]:
    def norm(x: float, y: float) -> list[float]:
        return [min(1.0, max(0.0, x / width)), min(1.0, max(0.0, y / height))]

    regions: list[RegionDef] = []
    for i, spec in enumerate(args.road or []):
        name, v = _name_and_numbers(spec, "--road")
        if len(v) != 4:
            raise SystemExit(f"--road needs NAME=x1,y1,x2,y2, got {spec!r}")
        x1, y1, x2, y2 = min(v[0], v[2]), min(v[1], v[3]), max(v[0], v[2]), max(v[1], v[3])
        regions.append(RegionDef(f"road{i}", name, "polygon", [norm(x1, y1), norm(x2, y1), norm(x2, y2), norm(x1, y2)]))
    for i, spec in enumerate(args.polygon or []):
        name, v = _name_and_numbers(spec, "--polygon")
        if len(v) < 6 or len(v) % 2:
            raise SystemExit(f"--polygon needs NAME=x,y;x,y;x,y[;...], got {spec!r}")
        regions.append(RegionDef(f"poly{i}", name, "polygon", [norm(v[j], v[j + 1]) for j in range(0, len(v), 2)]))
    for i, spec in enumerate(args.line or []):
        name, v = _name_and_numbers(spec, "--line")
        if len(v) != 4:
            raise SystemExit(f"--line needs NAME=x1,y1,x2,y2, got {spec!r}")
        regions.append(RegionDef(f"line{i}", name, "line", [norm(v[0], v[1]), norm(v[2], v[3])]))
    names = [r.name for r in regions]
    if len(set(n.lower() for n in names)) != len(names):
        raise SystemExit("road/area/line names must be unique")
    return regions


def save_grid(video: str, out: str, at_seconds: float) -> None:
    info = probe(video)
    cap = cv2.VideoCapture(video)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(at_seconds * info.fps))
    ok, img = cap.read()
    cap.release()
    if not ok:
        raise SystemExit("could not read a frame at that time")
    step = 100 if info.width <= 2000 else 200
    scale = max(0.5, info.width / 1600)
    for x in range(0, info.width, step):
        cv2.line(img, (x, 0), (x, info.height), (0, 255, 255), 1)
        cv2.putText(img, str(x), (x + 3, info.height - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5 * scale, (0, 255, 255), 1)
    for y in range(0, info.height, step // 2):
        cv2.line(img, (0, y), (info.width, y), (255, 255, 0), 1)
        cv2.putText(img, str(y), (3, y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.5 * scale, (255, 255, 0), 1)
    cv2.imwrite(out, img)
    print(f"Saved {out} ({info.width}x{info.height}, frame at {at_seconds:.1f} s)")


def print_report(result, regions: list[RegionDef], whole_frame: bool) -> None:
    by_zone: dict[str, list[dict]] = {}
    for c in result.zone_counts:
        by_zone.setdefault(c["zone_name"], []).append(c)
    by_line: dict[str, list[dict]] = {}
    for lc in result.line_crossings:
        by_line.setdefault(lc["line_name"], []).append(lc)
    names = (["Whole Frame"] if whole_frame else []) + [r.name for r in regions if r.kind == "polygon"]
    width = max([len(n) for n in names + [r.name for r in regions]] + [12])
    print()
    print(f"{'Road / area':<{width}}  Total  By type                         Directions")
    print("-" * (width + 70))
    for n in names:
        rows = by_zone.get(n, [])
        types = Counter(c["vehicle_type"] for c in rows)
        dirs = Counter(c["direction"] for c in rows)
        t = ", ".join(f"{VEHICLE_LABELS.get(k, k)} {v}" for k, v in types.most_common()) or "-"
        d = ", ".join(f"{k} {v}" for k, v in dirs.most_common()) or "-"
        print(f"{n:<{width}}  {len(rows):>5}  {t:<30}  {d}")
    for r in regions:
        if r.kind != "line":
            continue
        rows = by_line.get(r.name, [])
        d = ", ".join(f"{k} {v}" for k, v in Counter(x["direction"] for x in rows).most_common()) or "-"
        print(f"{r.name + ' (line)':<{width}}  {len(rows):>5}  {'':<30}  {d}")
    print()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video")
    p.add_argument("--road", action="append", metavar="NAME=x1,y1,x2,y2", help="rectangle over a road (repeatable)")
    p.add_argument("--polygon", action="append", metavar="NAME=x,y;x,y;...", help="polygon area (repeatable)")
    p.add_argument("--line", action="append", metavar="NAME=x1,y1,x2,y2", help="counting line (repeatable)")
    p.add_argument("--whole-frame", action="store_true", help="also count the whole picture")
    p.add_argument("--count", dest="count_rule", choices=["crossing", "entering", "present"], default="crossing",
                   help="crossing: comes in and leaves the area (default); entering: comes in; present: seen inside")
    p.add_argument("--from", dest="start", type=float, default=0.0, help="start time in seconds")
    p.add_argument("--to", dest="end", type=float, default=None, help="end time in seconds")
    p.add_argument("--detector", choices=["yolo", "motion"], default="yolo")
    p.add_argument("--model", default="yolo11n.pt", help="YOLO weights (file or official name)")
    p.add_argument("--imgsz", type=int, default=None, help="detector resolution (default: from video size)")
    p.add_argument("--sliced", action="store_true",
                   help="also detect on 2x2 tiles (finds small / distant vehicles, slower)")
    p.add_argument("--low-light", choices=["off", "auto", "on"], default="off",
                   help="CLAHE contrast boost before detection on dark frames")
    p.add_argument("--tracker", choices=["bytetrack", "botsort", "iou", "timelapse"], default="bytetrack")
    p.add_argument("--timelapse", action="store_true",
                   help="time-lapse / low frame-rate footage (time-lapse tracker, 2-frame minimum in an area)")
    p.add_argument("--camera", choices=["oblique", "overhead"], default="oblique")
    p.add_argument("--stride", type=int, default=1, help="process every Nth frame")
    p.add_argument("--confidence", type=float, default=0.3)
    p.add_argument("--types", default=",".join(ALL_VEHICLE_TYPES), help="comma-separated vehicle types")
    p.add_argument("--count-parked", action="store_true", help="also count vehicles that never move")
    p.add_argument("--annotate", metavar="OUT.mp4", help="write an annotated video")
    p.add_argument("--layout", choices=["overlay", "pipeline"], default="overlay")
    p.add_argument("--json", metavar="OUT.json", help="write every counted vehicle as JSON")
    p.add_argument("--grid", metavar="OUT.jpg", help="only save a frame with a pixel grid, then exit")
    p.add_argument("--at", type=float, default=0.0, help="time of the --grid frame in seconds")
    args = p.parse_args(argv)

    if not Path(args.video).exists():
        raise SystemExit(f"no such file: {args.video}")
    if args.grid:
        save_grid(args.video, args.grid, args.at)
        return 0

    info = probe(args.video)
    regions = build_regions(args, info.width, info.height)
    polygons = [r for r in regions if r.kind == "polygon"]
    whole_frame = args.whole_frame or not polygons
    imgsz = args.imgsz or (1280 if info.width >= 3000 else 960 if info.width >= 1800 else 640)
    print(f"{args.video}: {info.width}x{info.height} @ {info.fps:.2f} fps, {info.duration:.1f} s")
    print(f"Detector {args.detector}" + (f" ({args.model}, {imgsz}px)" if args.detector == "yolo" else "")
          + f", tracker {args.tracker}, {args.camera} camera, count rule '{args.count_rule}', "
          + f"{args.start:g}-{args.end or info.duration:g} s")

    if args.timelapse:
        args.tracker = "timelapse"
    if args.detector == "motion":
        detector, classification = MotionDetector(), "detector"
    else:
        detector, classification = YoloDetector(args.model, confidence=min(0.1, args.confidence), image_size=imgsz,
                                tiles=2 if args.sliced else 1), "size"
    cfg = PipelineConfig(
        vehicle_types=[t.strip() for t in args.types.split(",") if t.strip()],
        regions=regions,
        include_whole_frame=whole_frame,
        frame_stride=args.stride,
        anchor="center" if args.camera == "overhead" else "bottom_center",
        count_stationary=args.count_parked,
        min_frames_in_zone=2 if args.timelapse else None,
        count_rule=args.count_rule,
        low_light=args.low_light,
        start_seconds=args.start,
        end_seconds=args.end,
        annotated_video_path=args.annotate,
        annotated_video_layout=args.layout,
    )
    started = time.monotonic()
    last = [0.0]

    def progress(pct: float, frame: int, _counts) -> None:
        if pct >= 1 or time.monotonic() - last[0] > 2:
            last[0] = time.monotonic()
            print(f"  {pct * 100:5.1f}%  frame {frame}", file=sys.stderr)

    result = run_pipeline(
        args.video, cfg, detector, create_tracker(args.tracker, info.fps / args.stride, args.confidence),
        on_progress=progress, refiner=create_refiner(classification, info.height),
    )
    print(f"Processed {result.frames_processed} frames in {time.monotonic() - started:.1f} s")
    print_report(result, regions, whole_frame)
    if args.annotate:
        from app.workers.worker import _transcode_for_web

        _transcode_for_web(Path(args.annotate))
        print(f"Annotated video: {args.annotate}")
    if args.json:
        Path(args.json).write_text(json.dumps({"zone_counts": result.zone_counts,
                                               "line_crossings": result.line_crossings}, indent=2))
        print(f"Vehicle records: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
