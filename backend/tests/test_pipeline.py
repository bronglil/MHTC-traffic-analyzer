import io
import json
import zipfile

import pytest
from openpyxl import load_workbook

from app.analysis.analyzer import WHOLE_FRAME_ZONE_ID
from app.pipeline.engine import PipelineConfig, RegionDef, run_pipeline
from app.pipeline.tracker import IoUTracker, create_tracker
from app.reporting import exporters
from app.reporting.aggregate import summarize
from tests.conftest import FPS, FakeDetector

LEFT_HALF = RegionDef("left", "Left half", "polygon", [[0, 0], [0.5, 0], [0.5, 1], [0, 1]])
GATE = RegionDef("gate", "Centre gate", "line", [[0.5, 0], [0.5, 1]], "westbound", "eastbound")


def _run(video, tracker, **kw):
    cfg = PipelineConfig(vehicle_types=["car", "bus"], regions=[LEFT_HALF, GATE], **kw)
    return run_pipeline(str(video), cfg, FakeDetector(), tracker)


@pytest.mark.parametrize("tracker_kind", ["iou", "bytetrack", "botsort"])
def test_pipeline_counts(video_file, tracker_kind):
    progress, breakdowns = [], []
    cfg = PipelineConfig(vehicle_types=["car", "bus"], regions=[LEFT_HALF, GATE])
    result = run_pipeline(
        str(video_file), cfg, FakeDetector(), create_tracker(tracker_kind, FPS, 0.3),
        on_progress=lambda p, f, c: (progress.append(p), breakdowns.append(c)), progress_interval=0,
    )
    zones = {(c["zone_id"], c["vehicle_type"]): c for c in result.zone_counts}
    assert set(zones) == {(WHOLE_FRAME_ZONE_ID, "car"), (WHOLE_FRAME_ZONE_ID, "bus"), ("left", "car")}
    assert zones[(WHOLE_FRAME_ZONE_ID, "car")]["direction"] == "E"
    assert zones[(WHOLE_FRAME_ZONE_ID, "bus")]["direction"] == "S"
    assert [(c["line_id"], c["vehicle_type"], c["direction"]) for c in result.line_crossings] == [
        ("gate", "car", "eastbound")
    ]
    assert progress[-1] == 1.0
    assert breakdowns[-1]["gate"] == {"total": 1, "by_type": {"car": 1}, "by_direction": {"eastbound": 1}}
    assert breakdowns[-1]["left"]["by_type"] == {"car": 1}
    assert result.frames_processed == 60


def test_vehicle_type_selection_and_stride(video_file):
    cfg = PipelineConfig(vehicle_types=["bus"], frame_stride=2)
    result = run_pipeline(str(video_file), cfg, FakeDetector(), IoUTracker())
    assert [(c["zone_id"], c["vehicle_type"]) for c in result.zone_counts] == [(WHOLE_FRAME_ZONE_ID, "bus")]
    assert result.frames_processed == 30


def test_whole_frame_forced_without_polygons(video_file):
    cfg = PipelineConfig(vehicle_types=["car"], include_whole_frame=False, regions=[GATE])
    result = run_pipeline(str(video_file), cfg, FakeDetector(), IoUTracker())
    assert {c["zone_id"] for c in result.zone_counts} == {WHOLE_FRAME_ZONE_ID}


def test_annotated_video(video_file, tmp_path):
    out = tmp_path / "annotated.mp4"
    _run(video_file, IoUTracker(), annotated_video_path=str(out))
    import cv2

    cap = cv2.VideoCapture(str(out))
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 60
    cap.release()


def test_summary_and_exports(video_file):
    result = _run(video_file, IoUTracker())
    summary = summarize(result.zone_counts, result.line_crossings, time_bin_seconds=1)
    areas = {a["id"]: a for a in summary["areas"]}
    assert areas[WHOLE_FRAME_ZONE_ID]["total"] == 2
    assert areas["left"]["by_type"] == {"car": 1}
    assert summary["lines"][0]["by_direction"] == {"eastbound": 1}
    assert summary["lines"][0]["by_direction_type"] == {"eastbound": {"car": 1}}
    assert sum(r["total"] for r in summary["by_time"] if r["source"] == "area") == 3

    meta = {"analysis_id": "x"}
    data = json.loads(exporters.to_json(meta, summary, result.zone_counts, result.line_crossings))
    assert len(data["zone_counts"]) == 3

    csv_text = exporters.to_csv(result.zone_counts).decode()
    assert csv_text.splitlines()[0].startswith("zone_id,zone_name,track_id")
    assert len(csv_text.strip().splitlines()) == 4

    zf = zipfile.ZipFile(io.BytesIO(exporters.to_csv_zip(meta, summary, result.zone_counts, result.line_crossings)))
    assert "summary_by_area.csv" in zf.namelist()

    wb = load_workbook(io.BytesIO(exporters.to_xlsx(meta, summary, result.zone_counts, result.line_crossings)))
    assert "Summary by area" in wb.sheetnames
    assert wb["Vehicle counts"].max_row == 4


def test_stage_previews_and_pipeline_video(video_file, tmp_path):
    import cv2

    from app.pipeline.annotate import STAGES

    snapshots = []
    out = tmp_path / "pipeline.mp4"
    cfg = PipelineConfig(vehicle_types=["car", "bus"], regions=[LEFT_HALF, GATE], annotated_video_path=str(out),
                         annotated_video_layout="pipeline")
    run_pipeline(str(video_file), cfg, FakeDetector(), IoUTracker(),
                 on_stages=lambda st, i, t: snapshots.append((st, i)), stage_interval=0)
    assert len(snapshots) == 60
    stages, _ = snapshots[30]
    assert list(stages) == [k for k, _ in STAGES] + ["live"]
    assert all(img.shape == (360, 640, 3) for img in stages.values())
    # The detection panel differs from the raw frame (boxes drawn).
    assert (stages["detection"] != stages["frame"]).any()

    cap = cv2.VideoCapture(str(out))
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 60
    assert (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))) == (960, 412)
    cap.release()
