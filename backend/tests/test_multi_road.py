"""Several roads in one video: count only the roads the user selected, each
under its own name, plus origin -> destination movements between roads.

Uses ``tests/data/videos/synthetic_junction.mp4`` (regenerate with
``python tests/data/make_synthetic_junction.py``): a crossroads with five
vehicles whose routes are known exactly:

    car  North -> South      bus  West -> East      car  South -> East
    car  East  -> North      car  West -> South
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from app.analysis.analyzer import WHOLE_FRAME_ZONE_ID
from app.pipeline.engine import PipelineConfig, RegionDef, run_pipeline
from app.pipeline.tracker import create_tracker
from app.reporting.aggregate import summarize
from tests.conftest import FakeDetector
from tests.data.make_synthetic_junction import ARMS, FPS, H, W

VIDEO = Path(__file__).parent / "data" / "videos" / "synthetic_junction.mp4"
TRACKERS = ["bytetrack", "botsort"]


def road(arm: str, name: str | None = None, role: str = "count") -> RegionDef:
    """A rectangle drawn over one road arm, as the UI's rectangle tool would save it."""
    xs = [x for x, _ in ARMS[arm]]
    ys = [y for _, y in ARMS[arm]]
    x1, x2, y1, y2 = min(xs) / W, max(xs) / W, min(ys) / H, max(ys) / H
    return RegionDef(arm.lower(), name or f"{arm} Road", "polygon", [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
                     role=role)


def run(regions, tracker, include_whole_frame=False):
    cfg = PipelineConfig(vehicle_types=["car", "bus"], regions=regions, include_whole_frame=include_whole_frame,
                         anchor="center")
    # Colour-blob detector: knows cars (green) from buses (blue) in this synthetic clip.
    return run_pipeline(str(VIDEO), cfg, FakeDetector(), create_tracker(tracker, FPS, 0.3))


@pytest.mark.parametrize("tracker", TRACKERS)
def test_count_only_two_selected_roads(tracker):
    # Four roads in view; the user draws rectangles over just two and names them.
    result = run([road("North", "A1 Northbound"), road("East", "High Street")], tracker)
    per_road = Counter(c["zone_name"] for c in result.zone_counts)
    assert per_road == {"A1 Northbound": 2, "High Street": 3}
    assert WHOLE_FRAME_ZONE_ID not in {c["zone_id"] for c in result.zone_counts}
    by_type = Counter((c["zone_name"], c["vehicle_type"]) for c in result.zone_counts)
    assert by_type[("High Street", "bus")] == 1 and by_type[("High Street", "car")] == 2
    assert result.movements == []  # count-only roads produce no movements


@pytest.mark.parametrize("tracker", TRACKERS)
def test_all_roads_each_counted_separately_with_movements(tracker):
    result = run([road(a, role="both") for a in ARMS], tracker)
    per_road = Counter(c["zone_name"] for c in result.zone_counts)
    assert per_road == {"North Road": 2, "South Road": 3, "West Road": 2, "East Road": 3}
    moves = Counter((m["from_name"], m["to_name"], m["vehicle_type"]) for m in result.movements)
    assert moves == {
        ("North Road", "South Road", "car"): 1,
        ("West Road", "East Road", "bus"): 1,
        ("South Road", "East Road", "car"): 1,
        ("East Road", "North Road", "car"): 1,
        ("West Road", "South Road", "car"): 1,
    }
    summary = summarize(result.zone_counts, result.line_crossings, 10, result.movements)
    assert {(m["from"], m["to"]): m["total"] for m in summary["movements"]} == {
        ("East Road", "North Road"): 1, ("North Road", "South Road"): 1, ("South Road", "East Road"): 1,
        ("West Road", "East Road"): 1, ("West Road", "South Road"): 1,
    }


@pytest.mark.parametrize("tracker", TRACKERS)
def test_in_and_out_roles(tracker):
    # West is an inbound road and East an outbound one: only West -> East counts as a movement,
    # even though another vehicle travels East -> North and another South -> East.
    result = run([road("West", "Station Rd (in)", "in"), road("East", "High St (out)", "out")], tracker)
    assert [(m["from_name"], m["to_name"], m["vehicle_type"]) for m in result.movements] == [
        ("Station Rd (in)", "High St (out)", "bus")
    ]


def test_whole_frame_still_available():
    result = run([road("North")], "bytetrack", include_whole_frame=True)
    per_zone = Counter(c["zone_name"] for c in result.zone_counts)
    assert per_zone == {"Whole Frame": 5, "North Road": 2}


@pytest.mark.parametrize("tracker", TRACKERS)
def test_motion_detector_counts_selected_roads(tracker):
    """No neural network: background subtraction gives the same per-road totals."""
    from app.pipeline.detector import MotionDetector

    cfg = PipelineConfig(vehicle_types=["car"], regions=[road("North"), road("East")], include_whole_frame=False,
                         anchor="center")
    result = run_pipeline(str(VIDEO), cfg, MotionDetector(), create_tracker(tracker, FPS, 0.3))
    assert Counter(c["zone_name"] for c in result.zone_counts) == {"North Road": 2, "East Road": 3}
