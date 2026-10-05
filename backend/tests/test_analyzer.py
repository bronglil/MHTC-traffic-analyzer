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
