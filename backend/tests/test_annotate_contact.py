"""The picture paints the vehicle's base in the road's own colour."""

import numpy as np

from app.analysis.analyzer import TrafficAnalyzer, ZoneSpec
from app.pipeline.annotate import StageRenderer
from app.pipeline.types import TrackedObject


def test_base_is_painted_in_the_road_colour_where_the_point_misses():
    road = ZoneSpec("slip", "Slip", ((100, 40), (140, 40), (140, 70), (100, 70)), "#ff0000")
    img = np.zeros((150, 300, 3), np.uint8)
    renderer = StageRenderer([road], [])
    frame = renderer.overlay(img, [TrackedObject(1, 70, 39, 110, 55, 0.9, "car")], TrafficAnalyzer((300, 150), [road]))
    # Bottom edge runs x=70..110 at y=55. The point x=90 is outside the road;
    # the part from x=100 is on it and must be that road's red.
    assert tuple(int(v) for v in frame[55, 105]) == (0, 0, 255)
    assert tuple(int(v) for v in frame[55, 85]) == (255, 255, 255)


def test_a_still_frame_keeps_the_base_black_and_white():
    road = ZoneSpec("slip", "Slip", ((100, 40), (140, 40), (140, 70), (100, 70)), "#ff0000")
    car = TrackedObject(1, 70, 39, 110, 55, 0.9, "car")
    analyzer = TrafficAnalyzer((300, 150), [road])
    analyzer.update(1, 0.1, [car])
    analyzer.note_motion(1, False)
    frame = StageRenderer([road], []).overlay(np.zeros((150, 300, 3), np.uint8), [car], analyzer)
    # On the road, but the frame did not change: the bar is not the road's red.
    assert int(frame[55, 105][2]) < 40
