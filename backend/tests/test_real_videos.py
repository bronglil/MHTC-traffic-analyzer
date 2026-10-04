"""Accuracy tests on real traffic footage with hand-counted ground truth.

Each ``tests/data/videos/*.json`` describes one clip: where it came from, the
manually counted vehicles, the ROIs/lines to analyse, the expected counts and
the detector/tracker configurations to evaluate. Adding a new clip is just a
matter of dropping ``<name>.mp4`` + ``<name>.json`` in that folder — e.g. MHTC
survey footage with LGV1/LGV2 ground truth to validate a custom model.

Configurations marked ``known_limitation`` document a case the configuration
is *expected* to get wrong (they run as xfail so a future improvement shows up
as XPASS). YOLO-based configurations are skipped when weights are unavailable.
Run only the fast motion-based cases with ``pytest -m "not model"``.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from app.pipeline.classifier import create_refiner
from app.pipeline.detector import MotionDetector
from app.pipeline.engine import PipelineConfig, RegionDef, run_pipeline
from app.pipeline.frames import probe
from app.pipeline.tracker import create_tracker
from app.vehicles import ALL_VEHICLE_TYPES

DATA = Path(__file__).parent / "data" / "videos"
MODEL_DIRS = [Path("."), Path("data/models"), Path(__file__).parent.parent / "data" / "models"]


def _cases():
    for spec_path in sorted(DATA.glob("*.json")):
        spec = json.loads(spec_path.read_text())
        for cfg in spec["configs"]:
            for tracker in cfg["trackers"]:
                for stride in cfg["strides"]:
                    marks = []
                    if cfg["detector"] == "yolo":
                        marks.append(pytest.mark.model)
                    if cfg.get("known_limitation"):
                        marks.append(pytest.mark.xfail(reason=cfg["known_limitation"], strict=False))
                    yield pytest.param(spec_path, cfg, tracker, stride, marks=marks,
                                       id=f"{spec_path.stem}-{cfg['name']}-{tracker}-s{stride}")


_yolo_cache: dict[str, object] = {}


def _detector(cfg):
    if cfg["detector"] == "motion":
        return MotionDetector()
    pytest.importorskip("ultralytics")
    from app.pipeline.detector import YoloDetector

    name = cfg["model"]
    if name not in _yolo_cache:
        path = next((str(d / name) for d in MODEL_DIRS if (d / name).exists()), name)
        try:
            _yolo_cache[name] = YoloDetector(path, confidence=min(0.1, cfg.get("confidence", 0.3)))
        except Exception as exc:  # noqa: BLE001 - e.g. offline and weights not cached
            pytest.skip(f"YOLO weights {name} unavailable: {exc}")
    return _yolo_cache[name]


def _assert_close(actual, expected, tol, what):
    assert abs(actual - expected) <= tol, f"{what}: got {actual}, expected {expected} (±{tol})"


@pytest.mark.parametrize("spec_path,cfg,tracker_kind,stride", list(_cases()))
def test_real_video_counts(spec_path, cfg, tracker_kind, stride):
    spec = json.loads(spec_path.read_text())
    video = DATA / spec["video"]
    info = probe(str(video))
    regions = [RegionDef(**r) for r in spec["regions"]]
    pcfg = PipelineConfig(
        vehicle_types=ALL_VEHICLE_TYPES,
        regions=regions,
        frame_stride=stride,
        anchor=cfg.get("anchor", "bottom_center"),
        min_seconds_in_zone=cfg.get("min_seconds_in_zone", 0.3),
    )
    result = run_pipeline(
        str(video), pcfg, _detector(cfg),
        create_tracker(tracker_kind, info.fps / stride, cfg.get("confidence", 0.3)),
        refiner=create_refiner(cfg.get("classification", "detector"), info.height),
    )
    tol = cfg.get("tolerance", 0)
    exp = spec["expected"]

    per_area = Counter(c["zone_name"] for c in result.zone_counts)
    for area, n in exp.get("areas", {}).items():
        _assert_close(per_area[area], n, tol, f"{area} total")

    for line, by_dir in exp.get("lines", {}).items():
        got = Counter(lc["direction"] for lc in result.line_crossings if lc["line_name"] == line)
        for direction, n in by_dir.items():
            _assert_close(got[direction], n, tol, f"{line} {direction}")

    for area, by_dir in exp.get("directions", {}).items():
        got = Counter(c["direction"] for c in result.zone_counts if c["zone_name"] == area)
        for direction, n in by_dir.items():
            _assert_close(got[direction], n, tol, f"{area} heading {direction}")

    if cfg.get("check_types", True) and cfg["detector"] != "motion":
        for area, by_type in exp.get("types", {}).items():
            got = Counter(c["vehicle_type"] for c in result.zone_counts if c["zone_name"] == area)
            for vtype, n in by_type.items():
                _assert_close(got[vtype], n, cfg.get("type_tolerance", tol), f"{area} {vtype}")


def test_ground_truth_files_are_consistent():
    """Expected totals must agree with the per-vehicle annotations."""
    specs = list(DATA.glob("*.json"))
    assert specs, "no real-video ground truth found"
    for spec_path in specs:
        spec = json.loads(spec_path.read_text())
        assert (DATA / spec["video"]).exists()
        assert spec.get("license"), f"{spec_path.name}: record the footage licence"
        vehicles = spec["vehicles"]
        for area, n in spec["expected"].get("types", {}).items():
            assert sum(n.values()) == spec["expected"]["areas"][area]
        if "lane" in vehicles[0]:
            lanes = Counter(v["lane"] for v in vehicles)
            for lane, n in lanes.items():
                assert spec["expected"]["areas"].get(lane, n) == n
