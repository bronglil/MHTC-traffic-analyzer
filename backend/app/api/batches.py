"""Batches: many videos analysed one after another with the same settings.

Each video in a batch gets its own ordinary analysis (its own areas/lines, or
the whole frame when none are drawn, and its own report). The worker runs
queued analyses oldest first, so a batch is processed video by video in the
order it was submitted; more workers process several videos at once.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.analyses import meta, new_analysis
from app.api.videos import get_video_or_404
from app.db import get_db
from app.models import Analysis, Batch, line_dict, movement_dict, zone_dict
from app.reporting import exporters
from app.schemas import BatchCreate
from app.vehicles import ALL_VEHICLE_TYPES

router = APIRouter(prefix="/api/batches", tags=["batches"])

ACTIVE = ("queued", "running")
STATUSES = ("queued", "running", "completed", "failed", "cancelled")


def _get(batch_id: str, db: Session) -> Batch:
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Batch not found")
    return batch


def _item(a: Analysis) -> dict[str, Any]:
    regions = a.config.get("regions", [])
    areas = [r["name"] for r in regions if r["kind"] == "polygon"]
    summary = a.summary or {}
    rows = [*summary.get("areas", []), *({**ln, "name": f"{ln['name']} (line)"} for ln in summary.get("lines", []))]
    by_type: Counter[str] = Counter()
    for row in summary.get("areas", []):
        by_type.update(row.get("by_type", {}))
    return {
        "analysis_id": a.id,
        "position": a.batch_position,
        "video_id": a.video_id,
        "video_name": a.video.original_name,
        "duration_seconds": a.video.duration_seconds,
        "status": a.status,
        "progress": a.progress,
        "message": a.message,
        "areas": areas or ["Whole Frame"],
        "lines": [r["name"] for r in regions if r["kind"] == "line"],
        "whole_frame": not areas or bool(a.config.get("include_whole_frame")),
        "counts": {row["name"]: row["total"] for row in rows},
        "by_type": dict(by_type),
        "processing_seconds": summary.get("processing_seconds"),
        "started_at": a.started_at,
        "finished_at": a.finished_at,
    }


def _summary(batch: Batch, with_items: bool) -> dict[str, Any]:
    analyses = batch.analyses
    by_status = Counter(a.status for a in analyses)
    total_video = sum(a.video.duration_seconds for a in analyses)
    done_video = sum(a.video.duration_seconds * (1.0 if a.status in ("completed", "failed", "cancelled") else
                                                 a.progress if a.status == "running" else 0.0) for a in analyses)
    out = {
        "id": batch.id,
        "name": batch.name,
        "created_at": batch.created_at,
        "settings": batch.settings,
        "videos": len(analyses),
        "status_counts": {s: by_status.get(s, 0) for s in STATUSES},
        "status": ("running" if by_status.get("running") else "queued" if by_status.get("queued") else
                   "completed" if by_status.get("completed") == len(analyses) else "finished"),
        # Weighted by video length, so a 3-hour video counts more than a 1-minute one.
        "progress": round(done_video / total_video, 4) if total_video else 0.0,
        "total_video_seconds": total_video,
    }
    if with_items:
        out["items"] = [_item(a) for a in analyses]
    return out


@router.post("", status_code=status.HTTP_201_CREATED)
def create_batch(body: BatchCreate, db: Session = Depends(get_db)) -> dict:
    videos = [get_video_or_404(vid, db) for vid in body.video_ids]
    too_short = [v.original_name for v in videos if body.settings.start_seconds >= max(v.duration_seconds, 0.001)]
    if too_short:
        raise HTTPException(422, f"'From' is past the end of: {', '.join(too_short)}")
    # Each video counts its own drawn areas; only a video with none uses the whole frame.
    settings = body.settings.model_copy(update={"region_ids": None, "include_whole_frame": False})
    batch = Batch(name=body.name or f"Batch of {len(videos)} videos · {datetime.now(UTC):%Y-%m-%d %H:%M}",
                  settings=settings.model_dump(exclude={"region_ids"}))
    db.add(batch)
    db.flush()
    base = datetime.now(UTC)
    for i, video in enumerate(videos):
        # Every drawn area and line of each video; the whole frame when it has none.
        db.add(new_analysis(video, settings, list(video.regions), batch_id=batch.id, batch_position=i + 1,
                            created_at=base + timedelta(milliseconds=i)))  # queue order = submitted order
    db.commit()
    db.refresh(batch)
    return _summary(batch, with_items=True)


@router.get("")
def list_batches(db: Session = Depends(get_db)) -> list[dict]:
    return [_summary(b, with_items=False) for b in db.scalars(select(Batch).order_by(Batch.created_at.desc()))]


@router.get("/{batch_id}")
def get_batch(batch_id: str, db: Session = Depends(get_db)) -> dict:
    return _summary(_get(batch_id, db), with_items=True)


@router.post("/{batch_id}/cancel")
def cancel_batch(batch_id: str, db: Session = Depends(get_db)) -> dict:
    batch = _get(batch_id, db)
    for a in batch.analyses:
        if a.status == "queued":
            a.status, a.message = "cancelled", "Cancelled before start"
        elif a.status == "running":
            a.cancel_requested, a.message = True, "Cancelling…"
    db.commit()
    return _summary(batch, with_items=True)


@router.post("/{batch_id}/retry")
def retry_batch(batch_id: str, db: Session = Depends(get_db)) -> dict:
    """Queue failed and cancelled videos again (completed ones are kept)."""
    batch = _get(batch_id, db)
    for a in batch.analyses:
        if a.status in ("failed", "cancelled"):
            a.status, a.progress, a.message = "queued", 0.0, "Queued again"
            a.cancel_requested, a.started_at, a.finished_at = False, None, None
            a.live_counts, a.live_breakdown, a.frames_processed = {}, None, 0
    db.commit()
    return _summary(batch, with_items=True)


@router.delete("/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_batch(batch_id: str, db: Session = Depends(get_db)) -> None:
    """Delete the batch and its analyses (the videos are kept)."""
    from app.api.analyses import delete_analysis

    batch = _get(batch_id, db)
    if any(a.status in ACTIVE for a in batch.analyses):
        raise HTTPException(status.HTTP_409_CONFLICT, "Cancel the batch before deleting it")
    ids = [a.id for a in batch.analyses]
    db.delete(batch)
    db.commit()
    for aid in ids:
        delete_analysis(aid, db)


# ------------------------------------------------------------------ export
def _stem(a: Analysis) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(a.video.original_name).stem).strip("_") or "video"
    return f"{a.batch_position or 0:03d}_{stem}"


def _summary_rows(batch: Batch) -> tuple[list[str], list[list[Any]]]:
    """One row per video and area/line: the per-video report totals side by side."""
    types = ALL_VEHICLE_TYPES
    cols = ["#", "video", "status", "area / line", "kind", "total", *types, "directions", "video_seconds"]
    rows: list[list[Any]] = []
    for a in batch.analyses:
        s = a.summary or {}
        entries = [(r, "area") for r in s.get("areas", [])] + [(r, "line") for r in s.get("lines", [])]
        if not entries:
            rows.append([a.batch_position, a.video.original_name, a.status, "", "", 0 if a.status == "completed" else "",
                         *["" for _ in types], "", round(a.video.duration_seconds, 1)])
        for r, kind in entries:
            dirs = ", ".join(f"{d} {n}" for d, n in sorted(r.get("by_direction", {}).items(), key=lambda kv: -kv[1]))
            rows.append([a.batch_position, a.video.original_name, a.status, r["name"], kind, r["total"],
                         *[r.get("by_type", {}).get(t, 0) for t in types], dirs, round(a.video.duration_seconds, 1)])
    return cols, rows


@router.get("/{batch_id}/export")
def export_batch(batch_id: str, format: Literal["xlsx", "csv", "zip"] = "xlsx", db: Session = Depends(get_db)) -> Response:
    """xlsx/csv: every video's totals in one table; zip: that table plus each
    video's own full report (Excel), one file per video."""
    batch = _get(batch_id, db)
    cols, rows = _summary_rows(batch)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", batch.name).strip("_")[:80] or "batch"
    if format == "csv":
        return Response(exporters._csv(cols, rows).encode(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
    wb = Workbook()
    ws = wb.active
    ws.title = "All videos"
    ws.append(cols)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append(row)
    ws.freeze_panes = "A2"
    ws.column_dimensions["B"].width = 40
    ws.column_dimensions["D"].width = 24
    buf = io.BytesIO()
    wb.save(buf)
    if format == "xlsx":
        return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("all_videos.xlsx", buf.getvalue())
        zf.writestr("all_videos.csv", exporters._csv(cols, rows))
        for a in batch.analyses:
            if a.status != "completed" or a.summary is None:
                continue
            zones = [zone_dict(r) for r in a.zone_counts]
            lines = [line_dict(r) for r in a.line_crossings]
            moves = [movement_dict(r) for r in a.movements]
            zf.writestr(f"videos/{_stem(a)}.xlsx", exporters.to_xlsx(meta(a), a.summary, zones, lines, moves))
    return Response(out.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}.zip"'})
