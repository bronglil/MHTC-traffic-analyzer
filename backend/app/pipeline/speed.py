"""Processing-speed presets: trade a little accuracy for a lot of speed on long videos.

Almost all of the time goes into the detector, which runs once per analysed
frame (five times with sliced detection). The presets therefore analyse fewer
frames per second of video and, for the fastest ones, use a smaller detector
input and no slicing. Frame rates are targets in *analysed* frames per second
of video, so a 25 fps and a 60 fps video get the same treatment.

Counting stays correct at lower rates because a vehicle that jumps across an
area between two analysed frames still counts as passing through it, and the
trackers are told the effective frame rate. Below about 8 analysed fps the
time-lapse tracker (position + colour matching) replaces ByteTrack, whose
box-overlap matching breaks down when vehicles move far between frames.
"""

from __future__ import annotations

from dataclasses import dataclass

SPEEDS = ("accurate", "balanced", "fast", "fastest")


@dataclass(frozen=True)
class SpeedPreset:
    target_fps: float | None  # analysed frames per second of video; None = every frame
    max_image_size: int | None  # cap on the detector input size; None = as configured
    allow_sliced: bool  # sliced (tiled) detection allowed
    label: str


PRESETS: dict[str, SpeedPreset] = {
    "accurate": SpeedPreset(None, None, True, "every frame, settings as chosen"),
    "balanced": SpeedPreset(15.0, None, True, "about 15 frames per second of video"),
    "fast": SpeedPreset(10.0, 960, False, "about 10 frames per second, no slicing"),
    "fastest": SpeedPreset(6.0, 640, False, "about 6 frames per second at 640 px"),
}

# ByteTrack / BoT-SORT match boxes by overlap; below this analysed rate vehicles
# move too far between frames for that and the time-lapse tracker is used.
MIN_FPS_FOR_IOU_TRACKERS = 8.0
# Buffered-IoU matching (see tracker.UltralyticsTracker): boxes grow by this fraction of
# their size on each side per skipped frame, so fast vehicles still overlap.
BUFFER_PER_SKIPPED_FRAME = 0.15


def matching_buffer(frame_stride: int, tracker: str) -> float:
    return BUFFER_PER_SKIPPED_FRAME * (frame_stride - 1) if tracker in ("bytetrack", "botsort") else 0.0


@dataclass(frozen=True)
class SpeedPlan:
    frame_stride: int
    image_size: int
    sliced: bool
    tracker: str
    analysed_fps: float
    buffer: float = 0.0  # tracker box buffer for matching


def plan(speed: str, fps: float, frame_stride: int = 1, image_size: int = 640, sliced: bool = False,
         tracker: str = "bytetrack", timelapse: bool = False) -> SpeedPlan:
    """Effective processing settings for one video.

    ``frame_stride`` is the user's own minimum stride; a preset only ever makes
    processing faster than that. Time-lapse footage already has few frames per
    event, so its frames are never skipped.
    """
    if speed not in PRESETS:
        raise ValueError(f"speed must be one of {SPEEDS}")
    p = PRESETS[speed]
    fps = fps if fps and fps > 0 else 25.0
    stride = max(1, frame_stride)
    if p.target_fps and not timelapse:
        stride = max(stride, round(fps / p.target_fps))
    size = min(image_size, p.max_image_size) if p.max_image_size else image_size
    analysed = fps / stride
    if (not timelapse and stride > 1 and analysed < MIN_FPS_FOR_IOU_TRACKERS
            and tracker in ("bytetrack", "botsort", "iou")):
        tracker = "timelapse"
    return SpeedPlan(stride, size, sliced and p.allow_sliced, tracker, analysed, matching_buffer(stride, tracker))
