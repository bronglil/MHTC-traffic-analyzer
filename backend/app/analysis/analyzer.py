"""ROI / whole-frame analysis, counting and direction detection.

Consumes ``TrackedObject`` streams frame by frame and produces finalized count
records. Counting rules:

* A track is counted **at most once per zone** (whole frame or ROI), no matter
  how many frames it appears in or whether it briefly leaves and re-enters.
  It must be inside the zone for ``min_frames_in_zone`` processed frames to
  suppress flicker/false positives.
* A track is counted **at most once per counting line**, on its first crossing.
* The vehicle type of a track is resolved by confidence-weighted majority vote
  over all its detections, so a single misclassified frame does not change it.
  All records for a track share that resolved type.
* The same vehicle legitimately appears in several zones/lines: each is an
  independent counting event.
* **Movements** (origin → destination, e.g. turning counts at a junction):
  areas can be marked as roads with a role — ``in`` (vehicles enter the scene
  through it), ``out`` (vehicles leave through it) or ``both``. A track that
  is seen in an in-road and *later* in a different out-road is counted once as
  a movement from the earliest in-road to the last out-road it visited.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.analysis.geometry import (
    Point,
    compass_direction,
    point_in_polygon,
    segments_intersect,
    side_of_line,
)
from app.pipeline.types import TrackedObject

WHOLE_FRAME_ZONE_ID = "whole_frame"
STATIONARY = "stationary"
ANCHORS = ("bottom_center", "center")
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


@dataclass
class _TrackState:
    track_id: int
    class_votes: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    conf_sum: float = 0.0
    hits: int = 0
    last_seen_frame: int = 0
    first_point: Point | None = None
    last_point: Point | None = None
    visits: dict[str, _ZoneVisit] = field(default_factory=dict)
    # line_id -> (frame, time, forward?) of first crossing
    crossings: dict[str, tuple[int, float, bool]] = field(default_factory=dict)

    @property
    def vehicle_type(self) -> str:
        return max(self.class_votes.items(), key=lambda kv: kv[1])[0]

    @property
    def mean_confidence(self) -> float:
        return self.conf_sum / self.hits if self.hits else 0.0


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
    ) -> None:
        """
        :param frame_size: (width, height) in pixels.
        :param min_direction_displacement: minimum movement, as a fraction of the
            frame diagonal, for a direction other than ``stationary``.
        :param track_timeout_frames: source frames without an update after which a
            track is considered finished and finalized.
        :param anchor: point of the box used as the vehicle's ground position:
            ``bottom_center`` for oblique/side cameras (where the wheels touch the
            road) or ``center`` for overhead cameras.
        """
        if anchor not in ANCHORS:
            raise ValueError(f"anchor must be one of {ANCHORS}")
        self.anchor = anchor
        width, height = frame_size
        self.zones = list(zones)
        self.lines = list(lines)
        self.vehicle_types = set(vehicle_types) if vehicle_types else None
        self.min_frames_in_zone = max(1, min_frames_in_zone)
        self.min_disp = min_direction_displacement * (width**2 + height**2) ** 0.5
        self.track_timeout_frames = track_timeout_frames
        self._tracks: dict[int, _TrackState] = {}
        self.zone_counts: list[ZoneCount] = []
        self.line_crossings: list[LineCrossing] = []
        self.movements: list[Movement] = []
        self._zone_by_id = {z.id: z for z in self.zones}

    # ------------------------------------------------------------------ update
    def update(self, frame_index: int, timestamp: float, objects: Iterable[TrackedObject]) -> None:
        for obj in objects:
            st = self._tracks.get(obj.track_id)
            if st is None:
                st = self._tracks[obj.track_id] = _TrackState(obj.track_id)
            st.class_votes[obj.vehicle_type] += max(obj.confidence, 1e-3)
            st.conf_sum += obj.confidence
            st.hits += 1
            st.last_seen_frame = frame_index
            pt = obj.bottom_center if self.anchor == "bottom_center" else obj.center
            if st.first_point is None:
                st.first_point = pt

            for zone in self.zones:
                if zone.polygon is not None and not point_in_polygon(pt, zone.polygon):
                    continue
                visit = st.visits.get(zone.id)
                if visit is None:
                    visit = st.visits[zone.id] = _ZoneVisit(frame_index, timestamp, pt)
                visit.frames += 1
                visit.last_frame = frame_index
                visit.last_time = timestamp
                visit.exit_point = pt

            prev = st.last_point
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

    def _finalize(self, st: _TrackState) -> None:
        if not st.hits:
            return
        vtype = st.vehicle_type
        if not self._accepts(vtype):
            return
        zone_by_id = {z.id: z for z in self.zones}
        for zone_id, visit in st.visits.items():
            if visit.frames < self.min_frames_in_zone:
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
            if v.frames >= self.min_frames_in_zone and self._zone_by_id[zid].role != "count"
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
            if not st.hits or not self._accepts(st.vehicle_type):
                continue
            vtype = st.vehicle_type
            for zone_id, visit in st.visits.items():
                if visit.frames >= self.min_frames_in_zone:
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
        st = self._tracks.get(track_id)
        return st.vehicle_type if st and st.hits else None

    def active_track_direction(self, track_id: int) -> str | None:
        st = self._tracks.get(track_id)
        if not st or st.first_point is None or st.last_point is None:
            return None
        return self._direction(st.first_point, st.last_point)
