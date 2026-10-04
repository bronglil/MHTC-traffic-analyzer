"""Rendering of annotated output: per-stage visualisations and videos.

``StageRenderer`` draws what each pipeline stage sees for the current frame:

1. Frame extraction   - the raw decoded frame
2. Detection          - detector boxes, class and confidence (before tracking)
3. Tracking           - persistent track ids with motion trails
4. Classification     - per-track vehicle type after refinement (e.g. truck→LGV2)
5. ROI analysis       - which area(s) each vehicle's ground point is in
6. Counting           - counting lines, direction of travel and running totals

These are served live while an analysis runs and can be written as a 3x2
"pipeline" video. ``layout="overlay"`` instead writes a single annotated frame.
"""

from __future__ import annotations

import colorsys
from collections import defaultdict, deque
from collections.abc import Sequence

import cv2
import numpy as np

from app.analysis.analyzer import LineSpec, TrafficAnalyzer, ZoneSpec
from app.analysis.geometry import point_in_polygon
from app.pipeline.types import Detection, TrackedObject
from app.vehicles import VEHICLE_LABELS


def _hex_bgr(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)


# Same fixed slot order as the dashboard's categorical palette.
TYPE_COLORS = {
    t: _hex_bgr(c)
    for t, c in {
        "car": "#2a78d6", "lgv1": "#eb6834", "lgv2": "#1baf7a", "truck": "#eda100",
        "bus": "#e87ba4", "motorcycle": "#008300", "bicycle": "#4a3aa7", "van": "#9b9b9b",
    }.items()
}
SHORT_LABELS = {"car": "Car", "lgv1": "LGV1", "lgv2": "LGV2", "truck": "HGV", "bus": "Bus",
                "motorcycle": "MC", "bicycle": "Cycle", "van": "Van"}

STAGES: list[tuple[str, str]] = [
    ("frame", "1. Frame extraction"),
    ("detection", "2. Detection"),
    ("tracking", "3. Tracking"),
    ("classification", "4. Classification"),
    ("roi", "5. ROI analysis"),
    ("counting", "6. Counting & direction"),
]

FONT = cv2.FONT_HERSHEY_SIMPLEX


def zone_color(i: int) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb((0.11 + i * 0.17) % 1.0, 0.8, 1.0)
    return int(b * 255), int(g * 255), int(r * 255)


def track_color(track_id: int) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb((track_id * 0.618034) % 1.0, 0.75, 1.0)
    return int(b * 255), int(g * 255), int(r * 255)


def _label(img: np.ndarray, text: str, x: int, y: int, bg: tuple[int, int, int], scale: float = 0.45) -> None:
    (tw, th), _ = cv2.getTextSize(text, FONT, scale, 1)
    y = max(th + 4, y)
    cv2.rectangle(img, (x, y - th - 5), (x + tw + 4, y), bg, -1)
    lum = 0.114 * bg[0] + 0.587 * bg[1] + 0.299 * bg[2]
    cv2.putText(img, text, (x + 2, y - 3), FONT, scale, (0, 0, 0) if lum > 140 else (255, 255, 255), 1, cv2.LINE_AA)


def _panel_text(img: np.ndarray, rows: Sequence[str], scale: float = 0.5) -> None:
    if not rows:
        return
    line_h = int(22 * scale / 0.5)
    w = max(cv2.getTextSize(r, FONT, scale, 1)[0][0] for r in rows) + 14
    overlay = img.copy()
    cv2.rectangle(overlay, (6, 6), (6 + w, 12 + line_h * len(rows)), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.65, img, 0.35, 0, img)
    for i, r in enumerate(rows):
        cv2.putText(img, r, (13, 6 + line_h * (i + 1)), FONT, scale, (255, 255, 255), 1, cv2.LINE_AA)


class StageRenderer:
    def __init__(
        self,
        zones: Sequence[ZoneSpec],
        lines: Sequence[LineSpec],
        anchor: str = "bottom_center",
        trail_length: int = 40,
    ) -> None:
        self.zones = list(zones)
        self.lines = list(lines)
        self.anchor = anchor
        self._trails: dict[int, deque[tuple[int, int]]] = defaultdict(lambda: deque(maxlen=trail_length))
        self._last_seen: dict[int, int] = {}

    def _pt(self, o: TrackedObject) -> tuple[float, float]:
        return o.bottom_center if self.anchor == "bottom_center" else o.center

    def observe(self, frame_index: int, tracked: Sequence[TrackedObject]) -> None:
        """Call every processed frame so trails are continuous."""
        for o in tracked:
            x, y = self._pt(o)
            self._trails[o.track_id].append((int(x), int(y)))
            self._last_seen[o.track_id] = frame_index
        stale = [t for t, f in self._last_seen.items() if frame_index - f > 150]
        for t in stale:
            self._trails.pop(t, None)
            self._last_seen.pop(t, None)

    # ------------------------------------------------------------------ stages
    def render(
        self,
        image: np.ndarray,
        frame_index: int,
        timestamp: float,
        detections: Sequence[Detection],
        tracked: Sequence[TrackedObject],
        classified: Sequence[TrackedObject],
        analyzer: TrafficAnalyzer,
    ) -> dict[str, np.ndarray]:
        h, w = image.shape[:2]
        out: dict[str, np.ndarray] = {}

        img = image.copy()
        _panel_text(img, [f"Frame {frame_index}", f"t = {timestamp:6.2f} s", f"{w}x{h}"])
        out["frame"] = img

        img = image.copy()
        for d in detections:
            c = TYPE_COLORS.get(d.vehicle_type, (200, 200, 200))
            cv2.rectangle(img, (int(d.x1), int(d.y1)), (int(d.x2), int(d.y2)), c, 2)
            _label(img, f"{SHORT_LABELS.get(d.vehicle_type, d.vehicle_type)} {d.confidence:.2f}", int(d.x1), int(d.y1), c)
        _panel_text(img, [f"{len(detections)} detections"])
        out["detection"] = img

        img = image.copy()
        for o in tracked:
            c = track_color(o.track_id)
            trail = list(self._trails.get(o.track_id, ()))
            for i in range(1, len(trail)):
                cv2.line(img, trail[i - 1], trail[i], c, 2, cv2.LINE_AA)
            cv2.rectangle(img, (int(o.x1), int(o.y1)), (int(o.x2), int(o.y2)), c, 2)
            _label(img, f"ID {o.track_id}", int(o.x1), int(o.y1), c)
        _panel_text(img, [f"{len(tracked)} active tracks"])
        out["tracking"] = img

        img = image.copy()
        raw = {o.track_id: o.vehicle_type for o in tracked}
        for o in classified:
            vtype = analyzer.active_track_type(o.track_id) or o.vehicle_type
            c = TYPE_COLORS.get(vtype, (200, 200, 200))
            cv2.rectangle(img, (int(o.x1), int(o.y1)), (int(o.x2), int(o.y2)), c, 2)
            before = raw.get(o.track_id, vtype)
            text = SHORT_LABELS.get(vtype, vtype)
            if before != vtype:
                text = f"{SHORT_LABELS.get(before, before)}>{text}"
            _label(img, f"#{o.track_id} {text}", int(o.x1), int(o.y1), c)
        counts: dict[str, int] = defaultdict(int)
        for o in classified:
            counts[analyzer.active_track_type(o.track_id) or o.vehicle_type] += 1
        _panel_text(img, [f"{VEHICLE_LABELS.get(t, t)}: {n}" for t, n in sorted(counts.items())] or ["no vehicles"])
        out["classification"] = img

        img = image.copy()
        overlay = img.copy()
        for i, z in enumerate(self.zones):
            if z.polygon is not None:
                cv2.fillPoly(overlay, [np.array(z.polygon, dtype=np.int32)], zone_color(i))
        cv2.addWeighted(overlay, 0.25, img, 0.75, 0, img)
        for i, z in enumerate(self.zones):
            if z.polygon is None:
                cv2.rectangle(img, (1, 1), (w - 2, h - 2), zone_color(i), 2)
                continue
            pts = np.array(z.polygon, dtype=np.int32)
            cv2.polylines(img, [pts], True, zone_color(i), 2, cv2.LINE_AA)
            _label(img, z.name, int(pts[0][0]), int(pts[0][1]) + 18, zone_color(i))
        for o in classified:
            p = self._pt(o)
            inside = [i for i, z in enumerate(self.zones) if z.polygon is not None and point_in_polygon(p, z.polygon)]
            c = zone_color(inside[0]) if inside else (255, 255, 255)
            cv2.circle(img, (int(p[0]), int(p[1])), 6, c, -1)
            cv2.circle(img, (int(p[0]), int(p[1])), 6, (0, 0, 0), 1)
            names = ",".join(self.zones[i].name for i in inside) or "-"
            _label(img, f"#{o.track_id} in {names}", int(p[0]) + 8, int(p[1]), c, 0.4)
        _panel_text(img, [f"{len(self.zones)} area(s), anchor: {self.anchor.replace('_', ' ')}"])
        out["roi"] = img

        img = image.copy()
        for ln in self.lines:
            a, b = (int(ln.a[0]), int(ln.a[1])), (int(ln.b[0]), int(ln.b[1]))
            cv2.line(img, a, b, (0, 0, 255), 3, cv2.LINE_AA)
            _label(img, ln.name, a[0], a[1] + 18, (0, 0, 255))
        for o in classified:
            trail = list(self._trails.get(o.track_id, ()))
            direction = analyzer.active_track_direction(o.track_id) or ""
            c = TYPE_COLORS.get(analyzer.active_track_type(o.track_id) or o.vehicle_type, (200, 200, 200))
            if len(trail) >= 2:
                cv2.arrowedLine(img, trail[0], trail[-1], c, 3, cv2.LINE_AA, tipLength=0.2)
            _label(img, f"#{o.track_id} {direction}", int(o.x1), int(o.y1), c)
        live = analyzer.live_counts()
        rows = [f"{z.name}: {live.get(z.id, 0)}" for z in self.zones]
        rows += [f"{ln.name}: {live.get(ln.id, 0)}" for ln in self.lines]
        _panel_text(img, rows)
        out["counting"] = img
        return out

    def overlay(self, image: np.ndarray, classified: Sequence[TrackedObject], analyzer: TrafficAnalyzer) -> np.ndarray:
        """Single annotated frame: ROIs, lines, boxes, class, id, direction, counts."""
        img = image.copy()
        overlay = img.copy()
        for i, z in enumerate(self.zones):
            if z.polygon is not None:
                cv2.fillPoly(overlay, [np.array(z.polygon, dtype=np.int32)], zone_color(i))
        cv2.addWeighted(overlay, 0.15, img, 0.85, 0, img)
        for i, z in enumerate(self.zones):
            if z.polygon is not None:
                pts = np.array(z.polygon, dtype=np.int32)
                cv2.polylines(img, [pts], True, zone_color(i), 2, cv2.LINE_AA)
                _label(img, z.name, int(pts[0][0]), int(pts[0][1]) + 18, zone_color(i))
        for ln in self.lines:
            a, b = (int(ln.a[0]), int(ln.a[1])), (int(ln.b[0]), int(ln.b[1]))
            cv2.line(img, a, b, (0, 0, 255), 3, cv2.LINE_AA)
            _label(img, ln.name, a[0], a[1] + 18, (0, 0, 255))
        for o in classified:
            vtype = analyzer.active_track_type(o.track_id) or o.vehicle_type
            c = TYPE_COLORS.get(vtype, (255, 255, 255))
            cv2.rectangle(img, (int(o.x1), int(o.y1)), (int(o.x2), int(o.y2)), c, 2)
            direction = analyzer.active_track_direction(o.track_id) or ""
            _label(img, f"#{o.track_id} {SHORT_LABELS.get(vtype, vtype)} {direction}".strip(), int(o.x1), int(o.y1), c)
        live = analyzer.live_counts()
        _panel_text(img, [f"{z.name}: {live.get(z.id, 0)}" for z in self.zones]
                    + [f"{ln.name}: {live.get(ln.id, 0)}" for ln in self.lines])
        return img


def compose_grid(stages: dict[str, np.ndarray], tile_size: tuple[int, int]) -> np.ndarray:
    """3x2 grid of stage panels, each with a title bar."""
    tw, th = tile_size
    bar = 26
    tiles = []
    for key, title in STAGES:
        tile = cv2.resize(stages[key], (tw, th), interpolation=cv2.INTER_AREA)
        head = np.full((bar, tw, 3), 32, np.uint8)
        cv2.putText(head, title, (8, 18), FONT, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        tiles.append(np.vstack([head, tile]))
    row1 = np.hstack(tiles[:3])
    row2 = np.hstack(tiles[3:])
    return np.vstack([row1, row2])


class VideoAnnotator:
    """Writes the annotated video, either as a single overlay or a 3x2 stage grid."""

    def __init__(self, out_path: str, fps: float, frame_size: tuple[int, int], layout: str = "overlay") -> None:
        w, h = frame_size
        self.layout = layout
        if layout == "pipeline":
            # Tiles at half resolution keep the grid close to the source size.
            tw = max(160, (w // 2) // 2 * 2)
            th = max(90, int(round(tw * h / w)) // 2 * 2)
            self.tile = (tw, th)
            size = (tw * 3, (th + 26) * 2)
        else:
            size = (w, h)
        self.writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
        if not self.writer.isOpened():
            raise RuntimeError(f"Cannot open video writer for {out_path}")

    def write_overlay(self, img: np.ndarray) -> None:
        self.writer.write(img)

    def write_stages(self, stages: dict[str, np.ndarray]) -> None:
        self.writer.write(compose_grid(stages, self.tile))

    def close(self) -> None:
        self.writer.release()
