"""End-to-end analysis pipeline:

Video -> Frame extraction -> Detection -> Tracking -> Classification
      -> ROI / whole-frame analysis -> Counting & direction -> Results
      (-> live stage previews, annotated / pipeline video)
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from app.analysis.analyzer import WHOLE_FRAME_ZONE_ID, LineSpec, TrafficAnalyzer, ZoneSpec
from app.pipeline.annotate import StageRenderer, VideoAnnotator
from app.pipeline.classifier import ClassRefiner, PassThroughRefiner
from app.pipeline.detector import Detector, MotionDetector
from app.pipeline.enhance import LowLightEnhancer
from app.pipeline.frames import iter_frames, probe
from app.pipeline.motion import base_changed, to_gray
from app.pipeline.tracker import Tracker


@dataclass
class RegionDef:
    """User-configured area or line in *normalized* [0, 1] coordinates."""

    id: str
    name: str
    kind: str  # "polygon" | "line"
    points: list[list[float]]
    label_forward: str = "A→B"
    label_backward: str = "B→A"
    color: str | None = None
    role: str = "count"  # polygons: count | in | out | both (movement counting)


@dataclass
class PipelineConfig:
    vehicle_types: list[str]
    regions: list[RegionDef] = field(default_factory=list)
    include_whole_frame: bool = True
    frame_stride: int = 1
    min_seconds_in_zone: float = 0.3
    low_light: str = "off"  # off | auto | on - CLAHE before detection on dark frames
    count_rule: str = "present"  # crossing | entering | present (see TrafficAnalyzer)
    min_frames_in_zone: int | None = None  # overrides min_seconds_in_zone (e.g. 2 for time-lapse)
    anchor: str = "bottom_center"
    count_stationary: bool = False
    start_seconds: float = 0.0  # analyse only this part of the video
    end_seconds: float | None = None
    relink_gap_seconds: float = 2.0  # max time a vehicle may be hidden (sign, lamp post) and still re-link
    track_timeout_seconds: float = 3.0
    annotated_video_path: str | None = None
    annotated_video_layout: str = "overlay"  # "overlay" | "pipeline"


@dataclass
class PipelineResult:
    zone_counts: list[dict[str, Any]]
    line_crossings: list[dict[str, Any]]
    movements: list[dict[str, Any]]
    frames_processed: int
    duration_seconds: float
    elapsed_seconds: float


class AnalysisCancelled(Exception):
    pass


# (fraction done, frame index, live breakdown {zone/line id: {total, by_type, by_direction}})
ProgressCallback = Callable[[float, int, dict[str, dict]], None]
# Receives the per-stage images (see annotate.STAGES) for the current frame.
StageCallback = Callable[[dict[str, np.ndarray], int, float], None]


def build_specs(
    regions: Sequence[RegionDef], width: int, height: int, include_whole_frame: bool
) -> tuple[list[ZoneSpec], list[LineSpec]]:
    zones: list[ZoneSpec] = []
    lines: list[LineSpec] = []

    def px(p: Sequence[float]) -> tuple[float, float]:
        return (float(p[0]) * width, float(p[1]) * height)

    polygons = [r for r in regions if r.kind == "polygon" and len(r.points) >= 3]
    # With no custom area configured the whole frame is always analysed.
    if include_whole_frame or not polygons:
        zones.append(ZoneSpec(WHOLE_FRAME_ZONE_ID, "Whole Frame", None))
    for r in polygons:
        zones.append(ZoneSpec(r.id, r.name, tuple(px(p) for p in r.points), r.color, r.role or "count"))
    for r in regions:
        if r.kind == "line" and len(r.points) >= 2:
            lines.append(LineSpec(r.id, r.name, px(r.points[0]), px(r.points[1]), r.label_forward, r.label_backward,
                                  r.color))
    return zones, lines


def run_pipeline(
    video_path: str,
    config: PipelineConfig,
    detector: Detector,
    tracker: Tracker,
    on_progress: ProgressCallback | None = None,
    should_cancel: Callable[[], bool] | None = None,
    progress_interval: float = 0.5,
    refiner: ClassRefiner | None = None,
    on_stages: StageCallback | None = None,
    stage_interval: float = 1.0,
) -> PipelineResult:
    info = probe(video_path)
    zones, lines = build_specs(config.regions, info.width, info.height, config.include_whole_frame)
    refiner = refiner or PassThroughRefiner()
    analyzer = TrafficAnalyzer(
        frame_size=(info.width, info.height),
        zones=zones,
        lines=lines,
        vehicle_types=config.vehicle_types,
        # Dwell threshold is in seconds so it behaves the same at any fps / stride.
        min_frames_in_zone=config.min_frames_in_zone
        or max(2, round(config.min_seconds_in_zone * info.fps / max(1, config.frame_stride))),
        track_timeout_frames=max(1, int(config.track_timeout_seconds * info.fps)),
        anchor=config.anchor,
        count_stationary=config.count_stationary,
        count_rule=config.count_rule,
        relink_gap_frames=round(config.relink_gap_seconds * info.fps),
    )
    renderer = StageRenderer(zones, lines, anchor=config.anchor)
    # Background subtraction must not see per-frame contrast changes.
    enhancer = LowLightEnhancer("off" if isinstance(detector, MotionDetector) else config.low_light)
    annotator = None
    if config.annotated_video_path:
        annotator = VideoAnnotator(
            config.annotated_video_path,
            info.fps / max(1, config.frame_stride),
            (info.width, info.height),
            config.annotated_video_layout,
        )

    started = time.monotonic()
    last_report = last_stage = float("-inf")
    processed = 0
    prev_gray: np.ndarray | None = None
    start_f = max(0, int(round(config.start_seconds * info.fps)))
    end_f = int(round(config.end_seconds * info.fps)) if config.end_seconds else None
    if info.frame_count:
        end_f = min(end_f, info.frame_count) if end_f is not None else info.frame_count
    total = max(0, (end_f or 0) - start_f)
    try:
        for frame in iter_frames(video_path, stride=config.frame_stride, fps=info.fps, start_frame=start_f,
                                 end_frame=end_f):
            if should_cancel and should_cancel():
                raise AnalysisCancelled()
            detections = detector.detect(enhancer(frame.image))      # Detection (low-light enhanced if dark)
            tracked = tracker.update(detections, frame.image)         # Tracking
            classified = refiner.refine(tracked, frame.image)         # Classification
            analyzer.update(frame.index, frame.timestamp, classified)  # ROI analysis + counting
            gray = to_gray(frame.image)
            if prev_gray is not None:
                for obj in classified:
                    analyzer.note_motion(obj.track_id, base_changed(prev_gray, gray, obj, config.anchor))
            prev_gray = gray
            renderer.observe(frame.index, tracked)
            processed += 1

            now = time.monotonic()
            want_stages = on_stages is not None and now - last_stage >= stage_interval
            grid_video = annotator is not None and annotator.layout == "pipeline"
            if want_stages or grid_video:
                stages = renderer.render(frame.image, frame.index, frame.timestamp, detections, tracked,
                                         classified, analyzer)
                if grid_video:
                    annotator.write_stages(stages)
                if want_stages:
                    last_stage = now
                    on_stages(stages, frame.index, frame.timestamp)
            if annotator and not grid_video:
                annotator.write_overlay(renderer.overlay(frame.image, classified, analyzer))

            if on_progress and now - last_report >= progress_interval:
                last_report = now
                pct = min(0.99, (frame.index + 1 - start_f) / total) if total else 0.0
                on_progress(pct, frame.index, analyzer.live_breakdown())
    finally:
        if annotator:
            annotator.close()

    analyzer.finish()
    if on_progress:
        on_progress(1.0, (end_f or start_f + processed) - 1, analyzer.live_breakdown())
    return PipelineResult(
        zone_counts=[asdict(c) for c in analyzer.zone_counts],
        line_crossings=[asdict(c) for c in analyzer.line_crossings],
        movements=[asdict(m) for m in analyzer.movements],
        frames_processed=processed,
        duration_seconds=info.duration,
        elapsed_seconds=time.monotonic() - started,
    )
