from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.pipeline.tracker import TRACKER_TYPES
from app.vehicles import ALL_VEHICLE_TYPES

HEX_COLOR = r"^#[0-9a-fA-F]{6}$"

# Plain weight-file names only (no paths): weights are pickles, see worker.resolve_model.
MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.(pt|onnx|engine|torchscript)$")

AnalysisStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ----------------------------------------------------------------- regions
class RegionBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["polygon", "line"]
    points: list[list[float]] = Field(description="Normalized [x, y] pairs in 0..1")
    color: str | None = Field(None, pattern=HEX_COLOR)
    label_forward: str = Field("A→B", max_length=64)
    label_backward: str = Field("B→A", max_length=64)
    role: Literal["count", "in", "out", "both"] | None = Field(
        None, description="Areas: road role for movement counting (in / out / both); count = totals only")

    @field_validator("points")
    @classmethod
    def _points_valid(cls, pts: list[list[float]]) -> list[list[float]]:
        for p in pts:
            if len(p) != 2:
                raise ValueError("each point must be [x, y]")
            if not all(-0.001 <= v <= 1.001 for v in p):
                raise ValueError("points must be normalized to 0..1")
        return [[min(1.0, max(0.0, x)), min(1.0, max(0.0, y))] for x, y in pts]

    @model_validator(mode="after")
    def _shape(self) -> RegionBase:
        if self.kind == "polygon" and len(self.points) < 3:
            raise ValueError("a polygon needs at least 3 points")
        if self.kind == "line" and len(self.points) != 2:
            raise ValueError("a counting line needs exactly 2 points")
        return self


class RegionCreate(RegionBase):
    pass


class RegionUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    role: Literal["count", "in", "out", "both"] | None = None
    points: list[list[float]] | None = None
    color: str | None = Field(None, pattern=HEX_COLOR)
    label_forward: str | None = None
    label_backward: str | None = None


class RegionOut(RegionBase, ORM):
    id: str
    video_id: str
    created_at: datetime


# ------------------------------------------------------------------ videos
class VideoOut(ORM):
    id: str
    original_name: str
    size_bytes: int
    width: int
    height: int
    fps: float
    frame_count: int
    duration_seconds: float
    imported: bool | None = False
    created_at: datetime


class VideoListItem(VideoOut):
    area_count: int = 0
    line_count: int = 0
    region_names: list[str] = []
    latest_analysis_id: str | None = None
    latest_status: AnalysisStatus | None = None


class VideoDetail(VideoOut):
    regions: list[RegionOut]


class ImportRequest(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=1000, description="Paths relative to the import folder")


class CopyRegionsRequest(BaseModel):
    from_video_id: str
    replace: bool = Field(True, description="Remove this video's own areas/lines first")


# ---------------------------------------------------------------- analyses
class AnalysisSettings(BaseModel):
    vehicle_types: list[str] = Field(default_factory=lambda: list(ALL_VEHICLE_TYPES), min_length=1)
    region_ids: list[str] | None = Field(None, description="Subset of the video's regions; default all")
    include_whole_frame: bool = True
    detector: Literal["yolo", "motion"] = Field(
        "yolo", description="yolo: neural detector; motion: background subtraction (fixed cameras, no classes)")
    model_path: str | None = Field(None, description="YOLO weights; default from server settings")
    tracker: str = "bytetrack"
    count_rule: Literal["crossing", "entering", "present"] = Field(
        "crossing", description="crossing: comes in and leaves the drawn area; entering: comes in; "
                                "present: seen inside it")
    footage: Literal["normal", "timelapse"] = Field(
        "normal", description="timelapse: vehicles jump far between frames; uses the time-lapse tracker")
    classification: Literal["size", "detector", "classifier"] = Field(
        "size", description="How car/LGV1/LGV2/truck are decided; see docs/vehicle-classification.md")
    classifier_model: str | None = Field(None, description="YOLO classification model for 'classifier' mode")
    confidence: float = Field(0.3, ge=0.01, le=0.99)
    frame_stride: int = Field(1, ge=1, le=30, description="Process every Nth frame")
    min_seconds_in_zone: float = Field(0.3, ge=0.0, le=60.0)
    anchor: Literal["bottom_center", "center"] = Field(
        "bottom_center", description="Vehicle ground point: bottom_center for oblique cameras, center for overhead")
    start_seconds: float = Field(0.0, ge=0, description="Analyse from this time in the video (s)")
    end_seconds: float | None = Field(None, gt=0, description="Analyse up to this time (s); default end of video")
    speed: Literal["accurate", "balanced", "fast", "fastest"] = Field(
        "accurate", description="Processing speed preset: accurate analyses every frame; balanced ~15, fast ~10, "
                                "fastest ~6 frames per second of video (see app/pipeline/speed.py)")
    image_size: Literal[640, 960, 1280, 1920] | None = Field(
        640, description="Detector input size; larger finds small/distant vehicles in HD/4K video but is slower. "
                         "None = choose from the video's width")
    sliced_detection: bool | None = Field(
        False, description="Also detect on 2x2 overlapping tiles (SAHI): finds small/distant vehicles, ~2.5x slower. "
                           "None = on for HD/4K video")
    low_light: Literal["off", "auto", "on"] = Field(
        "off", description="CLAHE contrast boost before detection on dark frames (unlit roads)")
    count_stationary: bool = Field(
        False, description="Also count vehicles that never move (parked cars); off = moving traffic only")
    time_bin_seconds: int = Field(60, ge=1, le=86400)
    generate_annotated_video: bool = False
    annotated_video_layout: Literal["overlay", "pipeline"] = "overlay"

    @field_validator("vehicle_types")
    @classmethod
    def _types(cls, v: list[str]) -> list[str]:
        bad = set(v) - set(ALL_VEHICLE_TYPES)
        if bad:
            raise ValueError(f"unknown vehicle types: {sorted(bad)}")
        return list(dict.fromkeys(v))

    @field_validator("model_path", "classifier_model")
    @classmethod
    def _model_name(cls, v: str | None) -> str | None:
        if v and not MODEL_NAME_RE.match(v):
            raise ValueError("use a model file name (e.g. yolo11s.pt or my-lgv-model.pt), not a path")
        return v or None

    @model_validator(mode="after")
    def _time_range(self) -> AnalysisSettings:
        if self.end_seconds is not None and self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be after start_seconds")
        return self

    @field_validator("tracker")
    @classmethod
    def _tracker(cls, v: str) -> str:
        if v not in TRACKER_TYPES:
            raise ValueError(f"tracker must be one of {TRACKER_TYPES}")
        return v


class AnalysisOut(ORM):
    id: str
    video_id: str
    batch_id: str | None = None
    batch_position: int | None = None
    status: AnalysisStatus
    progress: float
    message: str | None
    config: dict[str, Any]
    live_counts: dict[str, int]
    live_breakdown: dict[str, Any] | None = None
    frames_processed: int
    has_annotated_video: bool = False
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class AnalysisResults(AnalysisOut):
    summary: dict[str, Any] | None


# ----------------------------------------------------------------- batches
class BatchCreate(BaseModel):
    name: str | None = Field(None, max_length=200)
    video_ids: list[str] = Field(min_length=1, max_length=2000, description="Processed in this order")
    settings: AnalysisSettings = Field(default_factory=AnalysisSettings)

    @field_validator("video_ids")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))
