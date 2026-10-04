"""Background analysis worker.

Jobs are rows in the ``analyses`` table. Workers claim queued rows (with
``FOR UPDATE SKIP LOCKED`` on PostgreSQL so several workers can run safely),
run the pipeline and write progress / results back to the database. The API's
WebSocket endpoint streams progress by watching the same rows, so API and
workers can run as separate processes or machines.

Run standalone with::

    python -m app.workers.worker
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine, get_sessionmaker, init_db
from app.models import Analysis, LineCrossingRecord, Video, ZoneCountRecord
from app.pipeline.classifier import ClassRefiner, create_refiner
from app.pipeline.detector import Detector, MotionDetector, YoloDetector
from app.pipeline.engine import AnalysisCancelled, PipelineConfig, RegionDef, run_pipeline
from app.pipeline.tracker import create_tracker
from app.reporting.aggregate import summarize
from app.schemas import MODEL_NAME_RE

log = logging.getLogger("traffic_vision.worker")

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"

# Factories are module attributes so tests can swap in fakes.
_detector_cache: dict[tuple, Detector] = {}


def resolve_model(name: str) -> str:
    """Model weights are pickles, so only plain file names are accepted: they are
    looked up in the server's models directory, otherwise treated as official
    Ultralytics weights (e.g. ``yolo11s.pt``) which are downloaded on first use."""
    settings = get_settings()
    if name in (settings.model_path, settings.classifier_model) and Path(name).exists():
        return name  # path configured by the server operator
    if not MODEL_NAME_RE.match(name):
        raise ValueError(f"Invalid model name {name!r}: use a file name from the models directory")
    local = get_settings().models_dir / name
    return str(local) if local.exists() else name


def default_detector_factory(kind: str, model_path: str, confidence: float, device: str | None) -> Detector:
    if kind == "motion":
        return MotionDetector()  # stateful background model: never shared between jobs
    key = (model_path, confidence, device)
    if key not in _detector_cache:
        _detector_cache[key] = YoloDetector(resolve_model(model_path), confidence=confidence, device=device)
    return _detector_cache[key]


def default_refiner_factory(mode: str, frame_height: int, classifier_model: str | None,
                            device: str | None) -> ClassRefiner:
    return create_refiner(mode, frame_height, resolve_model(classifier_model) if classifier_model else None, device)


detector_factory = default_detector_factory
refiner_factory = default_refiner_factory


def stage_dir(analysis_id: str) -> Path:
    return get_settings().output_dir / analysis_id / "stages"


def _write_stages(analysis_id: str, stages: dict, frame_index: int, timestamp: float) -> None:
    """Persist the latest per-stage images (atomic replace) for the live view."""
    import cv2

    d = stage_dir(analysis_id)
    d.mkdir(parents=True, exist_ok=True)
    for name, img in stages.items():
        h, w = img.shape[:2]
        if w > 960:
            img = cv2.resize(img, (960, int(h * 960 / w)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            tmp = d / f".{name}.jpg.tmp"
            tmp.write_bytes(buf.tobytes())
            tmp.replace(d / f"{name}.jpg")
    (d / "meta.json").write_text(json.dumps({"frame_index": frame_index, "timestamp": timestamp}))


def claim_next(db: Session) -> Analysis | None:
    stmt = select(Analysis).where(Analysis.status == "queued").order_by(Analysis.created_at).limit(1)
    if get_engine().dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    job = db.execute(stmt).scalar_one_or_none()
    if job is None:
        db.rollback()
        return None
    # Conditional update guards against a race on databases without row locks.
    claimed = db.execute(
        update(Analysis)
        .where(Analysis.id == job.id, Analysis.status == "queued")
        .values(status="running", worker_id=WORKER_ID, started_at=datetime.now(UTC), message="Starting")
    ).rowcount
    db.commit()
    if not claimed:
        return None
    db.refresh(job)
    return job


def _transcode_for_web(path: Path) -> None:
    """OpenCV writes mp4v, which browsers will not play; convert to H.264 if ffmpeg exists."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return
    tmp = path.with_suffix(".h264.mp4")
    proc = subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(path), "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(tmp)],
        capture_output=True,
    )
    if proc.returncode == 0 and tmp.exists():
        tmp.replace(path)
    else:
        tmp.unlink(missing_ok=True)
        log.warning("ffmpeg transcode failed: %s", proc.stderr.decode(errors="replace")[-500:])


def process(analysis_id: str) -> None:
    settings = get_settings()
    SessionLocal = get_sessionmaker()
    with SessionLocal() as db:
        job = db.get(Analysis, analysis_id)
        video = db.get(Video, job.video_id) if job else None
        if job is None or video is None:
            return
        cfg = dict(job.config)
        video_path = video.stored_path
        fps = video.fps
        height = video.height

    annotated_path: Path | None = None
    if cfg.get("generate_annotated_video"):
        annotated_path = settings.output_dir / f"{analysis_id}_annotated.mp4"

    pipeline_cfg = PipelineConfig(
        vehicle_types=cfg["vehicle_types"],
        regions=[RegionDef(**r) for r in cfg.get("regions", [])],
        include_whole_frame=cfg.get("include_whole_frame", True),
        frame_stride=cfg.get("frame_stride", 1),
        min_seconds_in_zone=cfg.get("min_seconds_in_zone", 0.3),
        anchor=cfg.get("anchor", "bottom_center"),
        annotated_video_path=str(annotated_path) if annotated_path else None,
        annotated_video_layout=cfg.get("annotated_video_layout", "overlay"),
    )
    tracker_kind = cfg.get("tracker", settings.default_tracker)
    confidence = float(cfg.get("confidence", 0.3))
    # ByteTrack/BoT-SORT associate low-confidence boxes in a second stage, so
    # the detector threshold is kept low and `confidence` is applied by the tracker.
    det_conf = confidence if tracker_kind == "iou" else min(confidence, 0.1)
    detector_kind = cfg.get("detector", "yolo")
    classification = cfg.get("classification", "size")
    if detector_kind == "motion" and classification == "size":
        # Motion blobs carry no class; size rules would invent van/truck splits.
        classification = "detector"

    last_cancel_check = [0.0, False]

    def should_cancel() -> bool:
        now = time.monotonic()
        if now - last_cancel_check[0] > 1.0:
            last_cancel_check[0] = now
            with SessionLocal() as db:
                last_cancel_check[1] = bool(
                    db.execute(select(Analysis.cancel_requested).where(Analysis.id == analysis_id)).scalar()
                )
        return last_cancel_check[1]

    def on_progress(pct: float, frame_index: int, counts: dict[str, int]) -> None:
        with SessionLocal() as db:
            db.execute(
                update(Analysis)
                .where(Analysis.id == analysis_id)
                .values(progress=round(pct, 4), live_counts=counts, frames_processed=frame_index,
                        message=f"Processing frame {frame_index}")
            )
            db.commit()

    try:
        detector = detector_factory(detector_kind, cfg.get("model_path") or settings.model_path, det_conf,
                                    settings.device)
        tracker = create_tracker(tracker_kind, fps / max(1, pipeline_cfg.frame_stride), confidence)
        refiner = refiner_factory(classification, height, cfg.get("classifier_model") or settings.classifier_model,
                                  settings.device)
        result = run_pipeline(
            video_path, pipeline_cfg, detector, tracker, on_progress, should_cancel,
            refiner=refiner,
            on_stages=lambda stages, fi, ts: _write_stages(analysis_id, stages, fi, ts),
        )
        if annotated_path and annotated_path.exists():
            _transcode_for_web(annotated_path)
        summary = summarize(result.zone_counts, result.line_crossings, cfg.get("time_bin_seconds", 60))
        summary["frames_processed"] = result.frames_processed
        summary["video_duration_seconds"] = result.duration_seconds
        summary["processing_seconds"] = round(result.elapsed_seconds, 2)
        with SessionLocal() as db:
            job = db.get(Analysis, analysis_id)
            db.add_all(ZoneCountRecord(analysis_id=analysis_id, **c) for c in result.zone_counts)
            db.add_all(LineCrossingRecord(analysis_id=analysis_id, **c) for c in result.line_crossings)
            job.summary = summary
            job.status = "completed"
            job.progress = 1.0
            job.frames_processed = result.frames_processed
            job.message = (
                f"Counted {len(result.zone_counts)} area events and "
                f"{len(result.line_crossings)} line crossings"
            )
            job.annotated_video_path = str(annotated_path) if annotated_path and annotated_path.exists() else None
            job.finished_at = datetime.now(UTC)
            db.commit()
    except AnalysisCancelled:
        _finish(analysis_id, "cancelled", "Cancelled by user")
        if annotated_path:
            annotated_path.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001 - job must always reach a terminal state
        log.exception("Analysis %s failed", analysis_id)
        _finish(analysis_id, "failed", f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}")


def _finish(analysis_id: str, status: str, message: str) -> None:
    with get_sessionmaker()() as db:
        db.execute(
            update(Analysis)
            .where(Analysis.id == analysis_id)
            .values(status=status, message=message[:4000], finished_at=datetime.now(UTC))
        )
        db.commit()


def recover_stale_jobs() -> None:
    """Jobs left 'running' by a crashed worker on this host are re-queued."""
    with get_sessionmaker()() as db:
        db.execute(
            update(Analysis)
            .where(Analysis.status == "running", Analysis.worker_id.like(f"{socket.gethostname()}:%"))
            .values(status="queued", progress=0.0, message="Re-queued after worker restart")
        )
        db.commit()


def run_forever(stop: threading.Event | None = None) -> None:
    stop = stop or threading.Event()
    poll = get_settings().worker_poll_seconds
    log.info("Worker %s started", WORKER_ID)
    while not stop.is_set():
        try:
            with get_sessionmaker()() as db:
                job = claim_next(db)
        except Exception:  # noqa: BLE001 - e.g. database briefly unavailable
            log.exception("Failed to poll for jobs")
            job = None
        if job is None:
            stop.wait(poll)
            continue
        log.info("Processing analysis %s", job.id)
        process(job.id)


def start_embedded_worker() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=run_forever, args=(stop,), name="analysis-worker", daemon=True).start()
    return stop


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()
    recover_stale_jobs()
    run_forever()
