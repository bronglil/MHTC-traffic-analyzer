from app.analysis.analyzer import WHOLE_FRAME_ZONE_ID, LineSpec, TrafficAnalyzer, ZoneSpec
from app.analysis.geometry import compass_direction, point_in_polygon, segments_intersect
from app.pipeline.types import TrackedObject

WHOLE = ZoneSpec(WHOLE_FRAME_ZONE_ID, "Whole Frame", None)
LEFT = ZoneSpec("left", "Left half", ((0, 0), (50, 0), (50, 100), (0, 100)))


def obj(tid, x, y, vtype="car", conf=0.9):
    # 10x10 box whose bottom-centre is (x, y)
    return TrackedObject(tid, x - 5, y - 10, x + 5, y, conf, vtype)


def test_geometry():
    sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert point_in_polygon((5, 5), sq)
    assert not point_in_polygon((15, 5), sq)
    assert segments_intersect((0, 0), (10, 10), (0, 10), (10, 0))
    assert not segments_intersect((0, 0), (1, 1), (5, 5), (6, 7))
    assert compass_direction((0, 0), (10, 0)) == "E"
    assert compass_direction((0, 10), (0, 0)) == "N"  # image y grows down
    assert compass_direction((0, 0), (0, 10)) == "S"
    assert compass_direction((10, 10), (0, 0)) == "NW"


def test_vehicle_counted_once_per_zone_across_many_frames():
    a = TrafficAnalyzer((100, 100), [WHOLE, LEFT])
    for f in range(50):
        a.update(f, f / 10, [obj(1, 10 + f * 1.6, 50)])
    a.finish()
    by_zone = {c.zone_id: c for c in a.zone_counts}
    assert set(by_zone) == {WHOLE_FRAME_ZONE_ID, "left"}
    assert len(a.zone_counts) == 2  # one per zone, not one per frame
    assert by_zone[WHOLE_FRAME_ZONE_ID].direction == "E"


def test_reentry_does_not_double_count():
    a = TrafficAnalyzer((100, 100), [LEFT])
    xs = [10] * 5 + [80] * 5 + [10] * 5  # in, out, back in
    for f, x in enumerate(xs):
        a.update(f, f, [obj(7, x, 50)])
    a.finish()
    assert len(a.zone_counts) == 1
    assert a.zone_counts[0].frames_in_zone == 10


def test_min_frames_filters_flicker():
    a = TrafficAnalyzer((100, 100), [WHOLE], min_frames_in_zone=3)
    a.update(0, 0, [obj(1, 10, 10)])
    a.update(1, 0.1, [obj(1, 10, 10)])
    a.finish()
    assert a.zone_counts == []


def test_majority_vote_type_and_filter():
    a = TrafficAnalyzer((100, 100), [WHOLE], vehicle_types=["truck"])
    for f in range(10):
        a.update(f, f, [obj(1, 10 + f * 3, 10, "truck" if f != 4 else "bus")])
    for f in range(10):
        a.update(f, f, [obj(2, 60, 60 - f * 3, "car")])
    a.finish()
    assert [(c.track_id, c.vehicle_type) for c in a.zone_counts] == [(1, "truck")]


def test_stationary_vehicles_not_counted_by_default():
    """Parked cars / static false detections (a bollard read as a car) are not traffic."""
    a = TrafficAnalyzer((100, 100), [WHOLE])
    for f in range(30):
        a.update(f, f, [obj(1, 50 + (f % 2) * 0.5, 50), obj(2, 10 + f * 2, 80)])
    assert a.live_counts() == {WHOLE_FRAME_ZONE_ID: 1}
    a.finish()
    assert [c.track_id for c in a.zone_counts] == [2]


def test_stationary_direction_when_counting_parked():
    a = TrafficAnalyzer((100, 100), [WHOLE], count_stationary=True)
    for f in range(10):
        a.update(f, f, [obj(1, 50 + (f % 2) * 0.5, 50)])
    a.finish()
    assert a.zone_counts[0].direction == "stationary"


def test_line_crossing_direction_and_single_count():
    # vertical line top->bottom at x=50; walking down it, screen-left is the right-hand side
    line = LineSpec("gate", "Gate", (50, 0), (50, 100), "westbound", "eastbound")
    a = TrafficAnalyzer((100, 100), [WHOLE], [line])
    xs = [30, 40, 45, 55, 60, 48, 52, 70]  # crosses, jitters back and forth
    for f, x in enumerate(xs):
        a.update(f, f, [obj(1, x, 50)])
    for f, x in enumerate(reversed(xs)):
        a.update(10 + f, 10 + f, [obj(2, x, 70)])
    a.finish()
    crossings = sorted((c.track_id, c.direction) for c in a.line_crossings)
    assert crossings == [(1, "eastbound"), (2, "westbound")]


def test_track_expiry_finalizes():
    a = TrafficAnalyzer((100, 100), [WHOLE], track_timeout_frames=5)
    for f in range(5):
        a.update(f, f, [obj(1, 10 + f * 5, 10)])
    for f in range(5, 20):
        a.update(f, f, [])
    assert len(a.zone_counts) == 1  # finalized before finish()
    assert a.live_counts() == {WHOLE_FRAME_ZONE_ID: 1}


def test_live_breakdown_includes_active_tracks():
    line = LineSpec("gate", "Gate", (50, 0), (50, 100), "westbound", "eastbound")
    a = TrafficAnalyzer((100, 100), [WHOLE, LEFT], [line], track_timeout_frames=3)
    for f in range(8):  # track 1 finishes (east, crosses gate)
        a.update(f, f, [obj(1, 20 + f * 8, 50)])
    for f in range(8, 14):  # track 1 expires; track 2 (bus) still active in the left half
        a.update(f, f, [obj(2, 10, 30 + (f - 8) * 8, "bus")])
    live = a.live_breakdown()
    assert live[WHOLE_FRAME_ZONE_ID] == {"total": 2, "by_type": {"car": 1, "bus": 1}, "by_direction": {"E": 1, "S": 1}}
    assert live["left"]["by_type"] == {"car": 1, "bus": 1}
    assert live["gate"] == {"total": 1, "by_type": {"car": 1}, "by_direction": {"eastbound": 1}}
    assert a.live_counts() == {WHOLE_FRAME_ZONE_ID: 2, "left": 2, "gate": 1}


def test_occluded_vehicle_with_new_track_id_is_counted_once():
    """Hidden behind a lamp post for a few frames, the tracker gives it a new id."""
    a = TrafficAnalyzer((200, 100), [WHOLE, ZoneSpec("road", "Road", ((0, 0), (200, 0), (200, 100), (0, 100)))],
                        relink_gap_frames=10)
    for f in range(10):
        a.update(f, f, [obj(1, 30 + f * 5, 50)])       # moving right at 5 px/frame
    for f in range(10, 15):
        a.update(f, f, [])                            # occluded
    for f in range(15, 30):
        a.update(f, f, [obj(7, 30 + f * 5, 50)])       # re-appears where expected, new id
    a.finish()
    assert len([c for c in a.zone_counts if c.zone_id == WHOLE_FRAME_ZONE_ID]) == 1
    assert len([c for c in a.zone_counts if c.zone_id == "road"]) == 1


def test_no_relink_after_vehicle_left_or_far_from_prediction():
    a = TrafficAnalyzer((200, 100), [WHOLE], relink_gap_frames=10)
    for f in range(10):
        a.update(f, f, [obj(1, 120 + f * 8, 50)])      # drives out at the right edge (x=192)
    for f in range(12, 30):
        a.update(f, f, [obj(2, 196 - (f - 12) * 8, 60)])  # a different vehicle enters there
    for f in range(30, 40):
        a.update(f, f, [obj(3, 20 + (f - 30) * 3, 20)])
    a.update(41, 41, [])
    for f in range(42, 52):
        a.update(f, f, [obj(4, 150, 80 - (f - 42) * 4)])  # appears far from where 3 was heading
    a.finish()
    assert sorted(c.track_id for c in a.zone_counts) == [1, 2, 3, 4]


def test_relink_disabled():
    a = TrafficAnalyzer((200, 100), [WHOLE], relink_gap_frames=0)
    for f in range(10):
        a.update(f, f, [obj(1, 30 + f * 5, 50)])
    for f in range(12, 25):
        a.update(f, f, [obj(7, 30 + f * 5, 50)])
    a.finish()
    assert len(a.zone_counts) == 2


BOX = ZoneSpec("box", "Box by the sign", ((90, 0), (110, 0), (110, 100), (90, 100)))  # 20 px wide


def test_fast_vehicle_passing_small_box_is_counted():
    """Only one sample lands inside the box: it still passed through, so it counts."""
    a = TrafficAnalyzer((200, 100), [BOX], min_frames_in_zone=5)
    for f, x in enumerate([40, 65, 100, 135, 160]):
        a.update(f, f, [obj(1, x, 50)])
    a.finish()
    assert [c.zone_id for c in a.zone_counts] == ["box"]


def test_vehicle_jumping_across_box_between_samples_is_counted():
    """With a frame stride a fast vehicle can skip the box entirely; its path crossed it."""
    a = TrafficAnalyzer((200, 100), [BOX], min_frames_in_zone=5)
    for f, x in enumerate([20, 60, 130, 170]):
        a.update(f * 3, f * 0.1, [obj(1, x, 50)])
    a.finish()
    assert len(a.zone_counts) == 1 and a.zone_counts[0].direction == "E"


def test_vehicles_not_passing_box_are_not_counted():
    a = TrafficAnalyzer((200, 100), [BOX], min_frames_in_zone=5)
    for f in range(20):
        a.update(f, f, [obj(1, 10 + f * 3, 50),   # stops short of the box (x <= 67)
                        obj(2, 150 + f * 2, 50),  # drives away on the other side
                        obj(3, 30 + f * 4, 95)])  # drives through it (the box spans the full height)
    a.finish()
    assert sorted(c.track_id for c in a.zone_counts) == [3]  # only the one whose path went through it


def test_detection_flickering_inside_box_needs_dwell():
    """A track that only ever appears inside the box (no outside->inside->outside) needs min frames."""
    a = TrafficAnalyzer((200, 100), [BOX], min_frames_in_zone=5)
    for f in range(3):
        a.update(f, f, [obj(1, 95 + f * 4, 50)])
    a.finish()
    assert a.zone_counts == []


# --- count rules: crossing / entering / present ---------------------------------------
MID_BOX = ZoneSpec("box", "Box", ((80, 20), (120, 20), (120, 80), (80, 80)))  # inside the 200x100 frame


def _scenario(rule):
    a = TrafficAnalyzer((200, 100), [MID_BOX], count_rule=rule, min_frames_in_zone=3, track_timeout_frames=5)
    frames = 40
    for f in range(frames):
        objs = [
            obj(1, 20 + f * 5, 50),                         # drives right through the box -> crosses
            obj(2, 30 + min(f, 15) * 4, 60),                # drives in and parks inside (x stops at 90)
            obj(3, 100 + (f % 2), 70) if f < 25 else None,  # already inside at the start, sits still
            obj(4, 40 + f * 2, 50) if f < 15 else None,     # approaches, stops short (x <= 68), never enters
        ]
        if 10 <= f < 30:
            x = 75 + (f - 10) * 3 if f < 20 else 105 - (f - 20) * 3
            objs.append(obj(5, x, 30))                      # dips in and turns back out the same side
        a.update(f, f, [o for o in objs if o is not None])
    a.finish()
    return sorted(c.track_id for c in a.zone_counts)


def test_crossing_counts_only_vehicles_that_come_in_and_leave():
    # 2 parks inside, 3 was already inside, 4 never enters, 5 backs out the way it came.
    assert _scenario("crossing") == [1]


def test_entering_also_counts_vehicles_that_stay():
    assert _scenario("entering") == [1, 2, 5]


def test_present_counts_anything_seen_inside_long_enough():
    assert _scenario("present") == [1, 2, 5]  # 3 never moves (stationary filter), 4 never inside


def test_crossing_through_picture_edge():
    """A box touching the bottom of the picture: driving out of view through it is leaving."""
    edge_box = ZoneSpec("edge", "Edge box", ((60, 50), (140, 50), (140, 100), (60, 100)))
    a = TrafficAnalyzer((200, 100), [edge_box], count_rule="crossing", track_timeout_frames=3)
    for f in range(13):                       # comes down from the top and leaves at the bottom edge
        y = 20 + f * 7
        a.update(f, f, [TrackedObject(1, 95, y - 10, 105, min(99.5, y), 0.9, "car")])
    for f in range(13, 20):
        a.update(f, f, [])
    assert [c.track_id for c in a.zone_counts] == [1]


WIDE_BOX = ZoneSpec("wide", "Wide box", ((40, 20), (160, 20), (160, 80), (40, 80)))  # 120 px along x


def _crossing(tracks, start_offset=5):
    """tracks: {tid: [(frame, x, y)]}; an unrelated car at frame 0 sets the period start."""
    a = TrafficAnalyzer((200, 100), [WIDE_BOX], count_rule="crossing", track_timeout_frames=3)
    a.update(0, 0, [obj(99, 5, 95)])
    last = max(f for pts in tracks.values() for f, _, _ in pts)
    for f in range(start_offset, last + 5):
        a.update(f, f / 10, [obj(t, x, y) for t, pts in tracks.items() for (g, x, y) in pts if g == f])
    a.finish()
    return sorted(c.track_id for c in a.zone_counts if c.zone_id == "wide")


def test_crossing_counts_a_track_that_starts_inside_but_covers_most_of_the_area():
    # Night / distant vehicle: first detected 10 px inside the box, drives out the far side.
    covers = {1: [(f, 50 + (f - 5) * 8, 50) for f in range(5, 25)]}
    assert _crossing(covers) == [1]
    # Detected only for the last 30 % of the box: it did not cross the area.
    partial = {2: [(f, 125 + (f - 5) * 8, 50) for f in range(5, 15)]}
    assert _crossing(partial) == []


def test_crossing_counts_a_track_that_fades_out_inside_the_far_end():
    # Comes in from outside and is lost 10 px before the far side (vehicle shrinks away).
    fades = {3: [(f, 20 + (f - 5) * 6, 50) for f in range(5, 27)]}  # last x = 146 < 160
    assert _crossing(fades) == [3]
    # ...but one that stops a third of the way in is still not counted.
    stops = {4: [(f, 20 + min(f - 5, 10) * 6, 50) for f in range(5, 30)]}  # stops at x = 80
    assert _crossing(stops) == []


def test_crossing_counts_vehicle_inside_when_the_period_starts_that_then_leaves():
    a = TrafficAnalyzer((200, 100), [MID_BOX], count_rule="crossing", track_timeout_frames=3)
    for f in range(12):                      # inside at the first analysed frame, drives out
        a.update(f, f, [obj(1, 100 + f * 5, 50)])
    a.finish()
    assert [c.track_id for c in a.zone_counts] == [1]


def test_track_confirmed_late_after_driving_into_view_counts_as_entering():
    """Trackers confirm a track a few frames after a vehicle appears; with frames skipped it is
    already well inside the picture (and inside a box at the picture edge) when first seen."""
    top_box = ZoneSpec("top", "Top box", ((60, 0), (140, 0), (140, 60), (60, 60)))
    a = TrafficAnalyzer((200, 100), [top_box], count_rule="crossing", track_timeout_frames=3)
    a.update(0, 0, [obj(99, 5, 95)])         # the period started earlier
    for f in range(5, 16):                   # first box spans y 20..30, moving down 9 px per sample
        y = 30 + (f - 5) * 9
        a.update(f, f / 10, [TrackedObject(1, 95, y - 10, 105, y, 0.9, "car")])
    a.finish()
    assert [c.track_id for c in a.zone_counts if c.zone_id == "top"] == [1]


def test_crossing_counts_a_car_whose_body_crosses_the_area_but_whose_anchor_misses():
    """The wheel point can stay just outside a drawn road while the car itself crosses it."""
    road = ZoneSpec("slip", "Slip", ((100, 40), (140, 40), (140, 70), (100, 70)))
    a = TrafficAnalyzer((300, 150), [road], count_rule="crossing", track_timeout_frames=3)
    for f in range(20):
        y = 20 + f * 5  # bottom-centre x=90, left of the area; the box reaches x=110
        a.update(f, f / 10, [TrackedObject(1, 70, y - 16, 110, y, 0.9, "car")])
    a.finish()
    assert [c.track_id for c in a.zone_counts] == [1]

    # The next lane stops short of the area, so it is not counted.
    b = TrafficAnalyzer((300, 150), [road], count_rule="crossing", track_timeout_frames=3)
    for f in range(20):
        y = 20 + f * 5
        b.update(f, f / 10, [TrackedObject(2, 50, y - 16, 95, y, 0.9, "car")])
    b.finish()
    assert b.zone_counts == []


def test_crossing_counts_a_wide_car_that_jumps_a_small_area_between_samples():
    road = ZoneSpec("slip", "Slip", ((100, 40), (140, 40), (140, 70), (100, 70)))
    a = TrafficAnalyzer((300, 150), [road], count_rule="crossing", track_timeout_frames=3)
    a.update(0, 0.0, [TrackedObject(1, 70, 14, 110, 30, 0.9, "car")])  # above the area
    a.update(5, 0.5, [TrackedObject(1, 70, 64, 110, 80, 0.9, "car")])  # below it; the point at x=90 never enters
    a.finish()
    assert [c.track_id for c in a.zone_counts] == [1]


def test_crossing_counts_a_road_lying_inside_the_swept_base():
    """A small road in the middle of the jump, clear of the point and of the diagonals."""
    road = ZoneSpec("slip", "Slip", ((70, 60), (90, 60), (90, 75), (70, 75)))
    a = TrafficAnalyzer((400, 200), [road], count_rule="crossing", track_timeout_frames=3)
    a.update(0, 0.0, [TrackedObject(1, 50, 14, 250, 30, 0.9, "car")])
    a.update(5, 0.5, [TrackedObject(1, 50, 94, 250, 110, 0.9, "car")])
    a.finish()
    assert [c.track_id for c in a.zone_counts] == [1]


def test_black_and_white_stillness_drops_a_drifting_box():
    a = TrafficAnalyzer((200, 100), [WHOLE], count_rule="present", track_timeout_frames=3)
    for f in range(12):
        a.update(f, f / 10, [obj(1, 20 + f * 4, 50)])
        a.note_motion(1, False)
    a.finish()
    assert a.zone_counts == []


def test_black_and_white_change_keeps_a_moving_vehicle():
    a = TrafficAnalyzer((200, 100), [WHOLE], count_rule="present", track_timeout_frames=3)
    for f in range(12):
        a.update(f, f / 10, [obj(1, 20 + f * 4, 50)])
        a.note_motion(1, True)
    a.finish()
    assert [c.track_id for c in a.zone_counts] == [1]


def test_unknown_count_rule_rejected():
    import pytest

    with pytest.raises(ValueError):
        TrafficAnalyzer((100, 100), [WHOLE], count_rule="sometimes")
