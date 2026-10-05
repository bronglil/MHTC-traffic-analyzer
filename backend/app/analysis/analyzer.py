"""ROI / whole-frame analysis, counting and direction detection.

Consumes ``TrackedObject`` streams frame by frame and produces finalized count
records. Counting rules:

* A track is counted **at most once per zone** (whole frame or ROI), no matter
  how many frames it appears in or whether it briefly leaves and re-enters.
  It counts when it **passes through** the zone (seen outside, then inside —
  or jumping across it between two samples — then outside again), however
  briefly; otherwise it must stay inside for ``min_frames_in_zone`` processed
  frames, which suppresses flicker and false positives.
* A track is counted **at most once per counting line**, on its first crossing.
* The vehicle type of a track is resolved by confidence-weighted majority vote
  over all its detections, so a single misclassified frame does not change it.
  All records for a track share that resolved type.
* The same vehicle legitimately appears in several zones/lines: each is an
  independent counting event.
* Tracks that never travel more than ``min_direction_displacement`` (parked
  vehicles, static false detections) are not counted unless
  ``count_stationary`` is set.
* A vehicle briefly hidden behind a sign, lamp post or another vehicle often
  comes back with a new tracker id; it is re-linked to its earlier track (see
  ``relink_gap_frames``) so it is still counted once.
* **Movements** (origin → destination, e.g. turning counts at a junction):
  areas can be marked as roads with a role — ``in`` (vehicles enter the scene
  through it), ``out`` (vehicles leave through it) or ``both``. A track that
  is seen in an in-road and *later* in a different out-road is counted once as
  a movement from the earliest in-road to the last out-road it visited.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.analysis.geometry import (
    Point,
    compass_direction,
    line_chord,
    point_in_polygon,
    segments_intersect,
    side_of_line,
)
from app.pipeline.types import TrackedObject

WHOLE_FRAME_ZONE_ID = "whole_frame"
STATIONARY = "stationary"
ANCHORS = ("bottom_center", "center")
COUNT_RULES = ("crossing", "entering", "present")
# A vehicle whose track starts or ends *inside* an area (detection range ends there,
# the analysed part of the video starts there, or the track broke at night) still
# crosses the area when its path covers at least this share of the area along its
# direction of travel. Below 1/2 one vehicle split into two tracks could count twice.
CROSSING_COVERAGE = 0.6
START_GRACE_SECONDS = 0.25
# Trackers confirm a new track one to three analysed frames after a vehicle appears
# (more video time when frames are skipped). A track whose box, moved back along its
# motion this many samples, reaches the picture edge drove in through that edge.
CONFIRM_SAMPLES = 3
# Area roles for movement (origin -> destination) counting.
ROLES = ("count", "in", "out", "both")


@dataclass(frozen=True)
class ZoneSpec:
    id: str
    name: str
    polygon: tuple[Point, ...] | None  # pixel coordinates; None = whole frame
    color: str | None = None  # "#rrggbb" display colour
    role: str = "count"  # count | in | out | both (see ROLES)


@dataclass(frozen=True)
class LineSpec:
    id: str
    name: str
    a: Point
    b: Point
    # Labels for crossing from the left side of a->b to the right side and back.
    label_forward: str = "A→B"
    label_backward: str = "B→A"
    color: str | None = None



@dataclass
class ZoneCount:
    zone_id: str
    zone_name: str
    track_id: int
    vehicle_type: str
    direction: str
    first_frame: int
    last_frame: int
    first_time: float
    last_time: float
    frames_in_zone: int
    mean_confidence: float


@dataclass
class LineCrossing:
    line_id: str
    line_name: str
    track_id: int
    vehicle_type: str
    direction: str
    frame: int
    time: float


@dataclass
class Movement:
    """One vehicle travelling from an in-road to a different out-road."""

    from_id: str
    from_name: str
    to_id: str
    to_name: str
    track_id: int
    vehicle_type: str
    start_frame: int
    end_frame: int
    start_time: float
    end_time: float


@dataclass
class _ZoneVisit:
    first_frame: int
    first_time: float
    entry_point: Point
    last_frame: int = 0
    last_time: float = 0.0
    exit_point: Point = (0.0, 0.0)
    frames: int = 0
    entered_from_outside: bool = False  # the track was seen outside before entering
    left: bool = False  # ...and seen outside again afterwards
    outside_before: Point | None = None  # last position outside, just before entering
    traversal: float = 0.0  # distance from outside_before to the furthest exit position
    after_point: Point | None = None  # first position outside after the latest stretch inside
    after_frame: int = -1


@dataclass
class _TrackState:
    track_id: int
    class_votes: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    conf_sum: float = 0.0
    hits: int = 0
    last_seen_frame: int = 0
    first_point: Point | None = None
    first_box: tuple[float, float, float, float] | None = None
    max_travel: float = 0.0  # furthest distance from the first position (pixels)
    at_border: bool = False  # last box touched the picture edge (vehicle driving out of view)
    last_point: Point | None = None
    # Recent (frame, point) samples, used to predict where a lost vehicle went.
    recent: deque[tuple[int, Point]] = field(default_factory=lambda: deque(maxlen=8))
    visits: dict[str, _ZoneVisit] = field(default_factory=dict)
    # line_id -> (frame, time, forward?) of first crossing
    crossings: dict[str, tuple[int, float, bool]] = field(default_factory=dict)

    @property
    def vehicle_type(self) -> str:
        return max(self.class_votes.items(), key=lambda kv: kv[1])[0]

    @property
    def mean_confidence(self) -> float:
        return self.conf_sum / self.hits if self.hits else 0.0


def _segment_crosses(a: Point, b: Point, polygon: Sequence[Point]) -> bool:
    n = len(polygon)
    return any(segments_intersect(a, b, polygon[i], polygon[(i + 1) % n]) for i in range(n))


class TrafficAnalyzer:
    def __init__(
        self,
        frame_size: tuple[int, int],
        zones: Sequence[ZoneSpec],
        lines: Sequence[LineSpec] = (),
        vehicle_types: Iterable[str] | None = None,
        min_frames_in_zone: int = 3,
        min_direction_displacement: float = 0.03,
        track_timeout_frames: int = 90,
        anchor: str = "bottom_center",
        count_stationary: bool = False,
        relink_gap_frames: int = 30,
        count_rule: str = "present",
    ) -> None:
        """
        :param frame_size: (width, height) in pixels.
        :param min_direction_displacement: minimum movement, as a fraction of the
            frame diagonal, for a direction other than ``stationary``.
        :param track_timeout_frames: source frames without an update after which a
            track is considered finished and finalized.
        :param relink_gap_frames: a vehicle whose track is lost mid-frame (occluded
            by a sign, lamp post or another vehicle) and re-appears as a new track id
            within this many source frames, near where it was heading, is treated as
            the same vehicle. 0 disables re-linking.
        :param count_rule: when a vehicle counts for a drawn area (see COUNT_RULES):
            ``crossing`` - it comes in from outside and leaves again;
            ``entering`` - it comes in from outside (it may stay);
            ``present`` - it is seen inside (passing through, or for min_frames).
            The picture's edge counts as "outside" for areas touching it. The
            whole-frame zone always uses ``present``.
        :param anchor: point of the box used as the vehicle's ground position:
            ``bottom_center`` for oblique/side cameras (where the wheels touch the
            road) or ``center`` for overhead cameras.
        """
        if count_rule not in COUNT_RULES:
            raise ValueError(f"count_rule must be one of {COUNT_RULES}")
        self.count_rule = count_rule
        if anchor not in ANCHORS:
            raise ValueError(f"anchor must be one of {ANCHORS}")
        self.anchor = anchor
        # Parked vehicles and static false detections (bollards, signs) never move;
        # traffic counts only vehicles that travel at least min_direction_displacement.
        self.count_stationary = count_stationary
        width, height = frame_size
        self.zones = list(zones)
        self.lines = list(lines)
        self.vehicle_types = set(vehicle_types) if vehicle_types else None
        self.min_frames_in_zone = max(1, min_frames_in_zone)
        self.min_disp = min_direction_displacement * (width**2 + height**2) ** 0.5
        self.track_timeout_frames = track_timeout_frames
        self.relink_gap_frames = relink_gap_frames
        self._size = (width, height)
        self._start_time: float | None = None  # time of the first analysed frame
        self._tracks: dict[int, _TrackState] = {}
        self._alias: dict[int, int] = {}  # tracker id -> id of the vehicle it continues
        self.zone_counts: list[ZoneCount] = []
        self.line_crossings: list[LineCrossing] = []
        self.movements: list[Movement] = []
        self._zone_by_id = {z.id: z for z in self.zones}
        # Distance a vehicle must travel across an area to count as passing through it:
        # ~3% of the frame diagonal, or half the area's narrow side for small boxes.
        self._pass_dist: dict[str, float] = {}
        for z in self.zones:
            if z.polygon is None:
                self._pass_dist[z.id] = self.min_disp
            else:
                xs, ys = [p[0] for p in z.polygon], [p[1] for p in z.polygon]
                self._pass_dist[z.id] = max(6.0, min(self.min_disp, 0.5 * min(max(xs) - min(xs), max(ys) - min(ys))))

    # ------------------------------------------------------------------ update
    def update(self, frame_index: int, timestamp: float, objects: Iterable[TrackedObject]) -> None:
        objects = list(objects)
        if self._start_time is None:
            self._start_time = timestamp
        # Vehicles already in an area when the analysed period begins (trackers confirm a
        # track a few frames late) count as having come in: like a survey count, a vehicle
        # counts in the period in which it completes its crossing.
        at_start = timestamp - self._start_time <= START_GRACE_SECONDS
        seen: set[int] = {self._alias.get(o.track_id, o.track_id) for o in objects}
        for obj in objects:
            tid = self._alias.get(obj.track_id, obj.track_id)
            st = self._tracks.get(tid)
            if st is None:
                st = self._relink(obj, frame_index, seen)
                if st is not None:
                    self._alias[obj.track_id] = st.track_id
                else:
                    st = self._tracks[obj.track_id] = _TrackState(obj.track_id)
                seen.add(st.track_id)
            st.class_votes[obj.vehicle_type] += max(obj.confidence, 1e-3)
            st.conf_sum += obj.confidence
            st.hits += 1
            st.last_seen_frame = frame_index
            pt = self._anchor(obj)
            st.recent.append((frame_index, pt))
            if st.first_point is None:
                st.first_point = pt
                st.first_box = (obj.x1, obj.y1, obj.x2, obj.y2)
            else:
                d = ((pt[0] - st.first_point[0]) ** 2 + (pt[1] - st.first_point[1]) ** 2) ** 0.5
                st.max_travel = max(st.max_travel, d)

            prev = st.last_point
            if st.hits == CONFIRM_SAMPLES + 1 and st.first_point is not None:
                self._came_into_view(st, pt)
            edge = self._touches_border(obj)
            st.at_border = edge
            for zone in self.zones:
                inside = zone.polygon is None or point_in_polygon(pt, zone.polygon)
                visit = st.visits.get(zone.id)
                if inside:
                    if visit is None:
                        visit = st.visits[zone.id] = _ZoneVisit(frame_index, timestamp, pt)
                        # From outside the area - or into view through the picture edge.
                        visit.entered_from_outside = prev is not None or edge or at_start
                        visit.outside_before = prev if prev is not None else pt
                    visit.frames += 1
                    visit.last_frame = frame_index
                    visit.last_time = timestamp
                    visit.exit_point = pt
                elif visit is not None:
                    visit.left = True
                    if visit.last_frame > visit.after_frame:
                        visit.after_point, visit.after_frame = pt, frame_index
                    if visit.outside_before is not None:
                        d = ((pt[0] - visit.outside_before[0]) ** 2 + (pt[1] - visit.outside_before[1]) ** 2) ** 0.5
                        visit.traversal = max(visit.traversal, d)
                elif prev is not None and _segment_crosses(prev, pt, zone.polygon):
                    # Fast vehicle (or frame stride) jumped right across the area between samples.
                    visit = st.visits[zone.id] = _ZoneVisit(frame_index, timestamp, prev, frame_index, timestamp, pt)
                    visit.entered_from_outside = visit.left = True
                    visit.outside_before = prev
                    visit.traversal = ((pt[0] - prev[0]) ** 2 + (pt[1] - prev[1]) ** 2) ** 0.5

            if prev is not None:
                for line in self.lines:
                    if line.id in st.crossings:
                        continue
                    if segments_intersect(prev, pt, line.a, line.b):
                        s_prev = side_of_line(prev, line.a, line.b)
                        s_now = side_of_line(pt, line.a, line.b)
                        if s_prev != s_now and s_now != 0:
                            # In image coords (y down) a positive cross product is
                            # the right-hand side of a->b as seen on screen.
                            st.crossings[line.id] = (frame_index, timestamp, s_now > 0)
            st.last_point = pt

        self._expire(frame_index)

    def _came_into_view(self, st: _TrackState, now: Point) -> None:
        """A few samples into a track: if its first box, moved back along the track's
        average motion by CONFIRM_SAMPLES samples, reaches the picture edge, the areas it
        was already inside when first seen were entered from outside (through the picture
        edge), not appeared in. Averaging over several samples matters because tracker
        output is Kalman-smoothed and starts at zero velocity."""
        w, h = self._size
        if st.first_box is None or st.first_point is None:
            return
        first = st.first_point
        x1, y1, x2, y2 = st.first_box
        n = st.hits - 1
        bx, by = (first[0] - now[0]) / n, (first[1] - now[1]) / n  # backwards motion per sample
        steps = []  # samples back until the box reaches the picture edge
        if bx > 0:
            steps.append((w - x2) / bx)
        elif bx < 0:
            steps.append(x1 / -bx)
        if by > 0:
            steps.append((h - y2) / by)
        elif by < 0:
            steps.append(y1 / -by)
        if not steps or min(steps) > CONFIRM_SAMPLES:
            return
        k = min(steps)
        start = (min(max(first[0] + k * bx, 0.0), w), min(max(first[1] + k * by, 0.0), h))
        for visit in st.visits.values():
            if not visit.entered_from_outside and visit.entry_point == first:
                visit.entered_from_outside = True
                visit.outside_before = start

    def _anchor(self, obj: TrackedObject) -> Point:
        return obj.bottom_center if self.anchor == "bottom_center" else obj.center

    def _relink(self, obj: TrackedObject, frame_index: int, seen: set[int]) -> _TrackState | None:
        """Find a recently lost track this new detection continues (occlusion ID switch)."""
        if self.relink_gap_frames <= 0:
            return None
        w, h = self._size
        margin_x, margin_y = 0.05 * w, 0.05 * h
        pt = self._anchor(obj)
        diag = ((obj.x2 - obj.x1) ** 2 + (obj.y2 - obj.y1) ** 2) ** 0.5
        max_dist = max(20.0, 1.5 * diag)
        best, best_d = None, max_dist
        for st in self._tracks.values():
            gap = frame_index - st.last_seen_frame
            if st.track_id in seen or gap <= 0 or gap > self.relink_gap_frames or st.last_point is None:
                continue
            lx, ly = st.last_point
            # A track lost at the frame edge left the scene; a new one there is a new vehicle.
            if lx < margin_x or lx > w - margin_x or ly < margin_y or ly > h - margin_y:
                continue
            (f0, p0), (f1, p1) = st.recent[0], st.recent[-1]
            vx, vy = ((p1[0] - p0[0]) / (f1 - f0), (p1[1] - p0[1]) / (f1 - f0)) if f1 > f0 else (0.0, 0.0)
            px, py = lx + vx * gap, ly + vy * gap
            if not (0 <= px <= w and 0 <= py <= h):
                continue  # it would have driven out of view by now
            d = ((pt[0] - px) ** 2 + (pt[1] - py) ** 2) ** 0.5
            if d <= best_d:
                best, best_d = st, d
        return best

    def _expire(self, frame_index: int) -> None:
        stale = [tid for tid, st in self._tracks.items() if frame_index - st.last_seen_frame > self.track_timeout_frames]
        for tid in stale:
            self._finalize(self._tracks.pop(tid))

    def finish(self) -> None:
        for st in self._tracks.values():
            self._finalize(st)
        self._tracks.clear()

    # ------------------------------------------------------------ finalization
    def _accepts(self, vehicle_type: str) -> bool:
        return self.vehicle_types is None or vehicle_type in self.vehicle_types

    def _direction(self, start: Point, end: Point) -> str:
        if ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5 < self.min_disp:
            return STATIONARY
        return compass_direction(start, end)

    def _touches_border(self, obj: TrackedObject) -> bool:
        """Box at (or within half its own size of) the picture edge: the vehicle is
        coming into or going out of view. The size-relative margin covers trackers
        that confirm a track a frame or two after it first appears at the edge."""
        w, h = self._size
        mx = max(0.01 * w, 0.5 * (obj.x2 - obj.x1))
        my = max(0.01 * h, 0.5 * (obj.y2 - obj.y1))
        return obj.x1 <= mx or obj.y1 <= my or obj.x2 >= w - mx or obj.y2 >= h - my

    def _close_edge_exits(self, st: _TrackState) -> None:
        """A track that ended while touching the picture edge drove out of view: for
        areas it was still inside, that counts as leaving them."""
        if not st.at_border or st.last_point is None:
            return
        for visit in st.visits.values():
            if visit.last_frame == st.last_seen_frame and not visit.left:
                visit.left = True
                start = visit.outside_before or visit.entry_point
                d = ((st.last_point[0] - start[0]) ** 2 + (st.last_point[1] - start[1]) ** 2) ** 0.5
                visit.traversal = max(visit.traversal, d)

    def _qualifies(self, visit: _ZoneVisit, zone_id: str) -> bool:
        """Whether a visit counts, per ``count_rule``. A vehicle "passes through" when
        it entered from outside and left again having really travelled across the
        area, however briefly it was inside; the travel requirement stops objects
        parked or queued on the area's edge from passing on every jitter of their box."""
        passed = visit.entered_from_outside and visit.left and visit.traversal >= self._pass_dist[zone_id]
        rule = "present" if self._zone_by_id[zone_id].polygon is None else self.count_rule
        if rule == "crossing":
            return passed or self._covers(visit, zone_id)
        if rule == "entering":
            return visit.entered_from_outside and (visit.left or visit.frames >= 2)
        return passed or visit.frames >= self.min_frames_in_zone

    def _covers(self, visit: _ZoneVisit, zone_id: str) -> bool:
        """The path through the area covers most of the area along the direction of
        travel, even though the track was not seen on both sides of it. Ends seen
        outside (or at the picture edge) count as reaching the area's outline."""
        polygon = self._zone_by_id[zone_id].polygon
        start = visit.outside_before if visit.entered_from_outside and visit.outside_before else visit.entry_point
        end = visit.after_point if visit.left and visit.after_point else visit.exit_point
        dist = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
        if dist < self._pass_dist[zone_id]:
            return False
        chord = line_chord(polygon, start, ((end[0] - start[0]) / dist, (end[1] - start[1]) / dist))
        if chord is None:
            return False
        t0, t1 = chord  # outline crossings, as distances along the path from `start`
        span = t1 - t0
        if span <= 0:
            return False
        missing = (0.0 if visit.entered_from_outside else max(0.0, -t0)) + (0.0 if visit.left else max(0.0, t1 - dist))
        return missing <= (1 - CROSSING_COVERAGE) * span

    def _moved(self, st: _TrackState) -> bool:
        return self.count_stationary or st.max_travel >= self.min_disp

    def _finalize(self, st: _TrackState) -> None:
        if not st.hits:
            return
        vtype = st.vehicle_type
        if not self._accepts(vtype) or not self._moved(st):
            return
        zone_by_id = {z.id: z for z in self.zones}
        self._close_edge_exits(st)
        for zone_id, visit in st.visits.items():
            if not self._qualifies(visit, zone_id):
                continue
            zone = zone_by_id[zone_id]
            self.zone_counts.append(
                ZoneCount(
                    zone_id=zone.id,
                    zone_name=zone.name,
                    track_id=st.track_id,
                    vehicle_type=vtype,
                    direction=self._direction(visit.entry_point, visit.exit_point),
                    first_frame=visit.first_frame,
                    last_frame=visit.last_frame,
                    first_time=visit.first_time,
                    last_time=visit.last_time,
                    frames_in_zone=visit.frames,
                    mean_confidence=round(st.mean_confidence, 4),
                )
            )
        mv = self._movement(st)
        if mv is not None:
            (o, ov), (d, dv) = mv
            self.movements.append(
                Movement(o.id, o.name, d.id, d.name, st.track_id, vtype,
                         ov.first_frame, dv.last_frame, ov.first_time, dv.last_time)
            )
        line_by_id = {ln.id: ln for ln in self.lines}
        for line_id, (frame, t, forward) in st.crossings.items():
            line = line_by_id[line_id]
            self.line_crossings.append(
                LineCrossing(
                    line_id=line.id,
                    line_name=line.name,
                    track_id=st.track_id,
                    vehicle_type=vtype,
                    direction=line.label_forward if forward else line.label_backward,
                    frame=frame,
                    time=t,
                )
            )

    def _movement(self, st: _TrackState):
        """(origin zone, visit), (destination zone, visit) or None."""
        visits = [
            (self._zone_by_id[zid], v) for zid, v in st.visits.items()
            if self._qualifies(v, zid) and self._zone_by_id[zid].role != "count"
            and self._zone_by_id[zid].polygon is not None
        ]
        origins = [zv for zv in visits if zv[0].role in ("in", "both")]
        if not origins:
            return None
        origin = min(origins, key=lambda zv: zv[1].first_frame)
        dests = [zv for zv in visits if zv[0].role in ("out", "both") and zv[0].id != origin[0].id
                 and zv[1].last_frame > origin[1].first_frame and zv[1].first_frame > origin[1].first_frame]
        if not dests:
            return None
        return origin, max(dests, key=lambda zv: zv[1].last_frame)

    # ------------------------------------------------------------- live state
    def live_breakdown(self) -> dict[str, dict]:
        """Provisional per-zone/line counts by vehicle type and direction,
        including still-active tracks (using their current majority type)."""
        out: dict[str, dict] = {}

        def add(key: str, vtype: str, direction: str) -> None:
            b = out.setdefault(key, {"total": 0, "by_type": defaultdict(int), "by_direction": defaultdict(int)})
            b["total"] += 1
            b["by_type"][vtype] += 1
            b["by_direction"][direction] += 1

        def add_movement(o: str, o_name: str, d: str, d_name: str, vtype: str) -> None:
            key = f"mv:{o}>{d}"
            b = out.setdefault(key, {"total": 0, "by_type": defaultdict(int), "by_direction": defaultdict(int),
                                     "from": o_name, "to": d_name})
            b["total"] += 1
            b["by_type"][vtype] += 1

        for m in self.movements:
            add_movement(m.from_id, m.from_name, m.to_id, m.to_name, m.vehicle_type)
        for c in self.zone_counts:
            add(c.zone_id, c.vehicle_type, c.direction)
        for lc in self.line_crossings:
            add(lc.line_id, lc.vehicle_type, lc.direction)
        line_by_id = {ln.id: ln for ln in self.lines}
        for st in self._tracks.values():
            if not st.hits or not self._accepts(st.vehicle_type) or not self._moved(st):
                continue
            vtype = st.vehicle_type
            for zone_id, visit in st.visits.items():
                if self._qualifies(visit, zone_id):
                    add(zone_id, vtype, self._direction(visit.entry_point, visit.exit_point))
            for line_id, (_, _, forward) in st.crossings.items():
                ln = line_by_id[line_id]
                add(line_id, vtype, ln.label_forward if forward else ln.label_backward)
            mv = self._movement(st)
            if mv is not None:
                (o, _), (d, _) = mv
                add_movement(o.id, o.name, d.id, d.name, vtype)
        return {k: {**v, "by_type": dict(v["by_type"]), "by_direction": dict(v["by_direction"])}
                for k, v in out.items()}

    def live_counts(self) -> dict[str, int]:
        """Provisional per-zone/line totals including still-active tracks."""
        return {k: v["total"] for k, v in self.live_breakdown().items() if not k.startswith("mv:")}

    def active_track_type(self, track_id: int) -> str | None:
        st = self._tracks.get(self._alias.get(track_id, track_id))
        return st.vehicle_type if st and st.hits else None

    def active_track_direction(self, track_id: int) -> str | None:
        st = self._tracks.get(self._alias.get(track_id, track_id))
        if not st or st.first_point is None or st.last_point is None or not self._moved(st):
            return None
        return self._direction(st.first_point, st.last_point)
