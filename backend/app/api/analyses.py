from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.videos import get_video_or_404
from app.colors import REGION_COLORS
from app.config import get_settings
from app.db import get_db, get_sessionmaker
from app.models import Analysis, line_dict, movement_dict, zone_dict
from app.pipeline.annotate import STAGES
from app.reporting import exporters
from app.schemas import AnalysisOut, AnalysisResults, AnalysisSettings

router = APIRouter(tags=["analyses"])

TERMINAL = ("completed", "failed", "cancelled")


def _out(a: Analysis, model=AnalysisOut):
    data = model.model_validate(a)
    data.has_annotated_video = bool(a.annotated_video_path)
    return data


def _get(analysis_id: str, db: Session) -> Analysis:
    a = db.get(Analysis, analysis_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found")
    return a


@router.post("/api/videos/{video_id}/analyses", response_model=AnalysisOut, status_code=status.HTTP_201_CREATED)
def create_analysis(video_id: str, body: AnalysisSettings, db: Session = Depends(get_db)) -> AnalysisOut:
    video = get_video_or_404(video_id, db)
    regions = video.regions
    if body.region_ids is not None:
        wanted = set(body.region_ids)
        unknown = wanted - {r.id for r in regions}
        if unknown:
            raise HTTPException(422, f"Unknown region ids: {sorted(unknown)}")
        regions = [r for r in regions if r.id in wanted]
    config = body.model_dump(exclude={"region_ids"})
    config["regions"] = [
        {"id": r.id, "name": r.name, "kind": r.kind, "points": r.points,
         # regions created before colours were stored get a stable palette slot
         "color": r.color or REGION_COLORS[i % len(REGION_COLORS)], "role": r.role or "count",
         "label_forward": r.label_forward, "label_backward": r.label_backward}
        for i, r in enumerate(regions)
    ]
    analysis = Analysis(video_id=video_id, config=config, live_counts={}, message="Queued")
    db.add(analysis)
    db.commit()
    return _out(analysis)


@router.get("/api/videos/{video_id}/analyses", response_model=list[AnalysisOut])
def list_analyses(video_id: str, db: Session = Depends(get_db)) -> list[AnalysisOut]:
    return [_out(a) for a in get_video_or_404(video_id, db).analyses]


@router.get("/api/analyses/{analysis_id}", response_model=AnalysisResults)
def get_analysis(analysis_id: str, db: Session = Depends(get_db)) -> AnalysisResults:
    return _out(_get(analysis_id, db), AnalysisResults)


@router.post("/api/analyses/{analysis_id}/cancel", response_model=AnalysisOut)
def cancel_analysis(analysis_id: str, db: Session = Depends(get_db)) -> AnalysisOut:
    a = _get(analysis_id, db)
    if a.status == "queued":
        a.status = "cancelled"
        a.message = "Cancelled before start"
    elif a.status == "running":
        a.cancel_requested = True
        a.message = "Cancelling…"
    db.commit()
    return _out(a)


@router.delete("/api/analyses/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_analysis(analysis_id: str, db: Session = Depends(get_db)) -> None:
    a = _get(analysis_id, db)
    if a.status == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, "Cancel the analysis before deleting it")
    path = a.annotated_video_path
    db.delete(a)
    db.commit()
    if path:
        Path(path).unlink(missing_ok=True)
    shutil.rmtree(get_settings().output_dir / analysis_id, ignore_errors=True)


@router.get("/api/analyses/{analysis_id}/vehicles")
def list_vehicle_counts(
    analysis_id: str,
    zone_id: str | None = None,
    vehicle_type: str | None = None,
    limit: int = Query(500, le=10000),
    offset: int = 0,
    db: Session = Depends(get_db),
) -> dict:
    a = _get(analysis_id, db)
    rows = [zone_dict(r) for r in a.zone_counts
            if (zone_id is None or r.zone_id == zone_id) and (vehicle_type is None or r.vehicle_type == vehicle_type)]
    return {"total": len(rows), "items": rows[offset: offset + limit],
            "line_crossings": [line_dict(r) for r in a.line_crossings][:limit],
            "movements": [movement_dict(r) for r in a.movements][:limit]}


def _meta(a: Analysis) -> dict:
    return {
        "analysis_id": a.id,
        "video_id": a.video_id,
        "video_name": a.video.original_name,
        "status": a.status,
        "created_at": a.created_at.isoformat(),
        "finished_at": a.finished_at.isoformat() if a.finished_at else None,
        "vehicle_types": a.config.get("vehicle_types"),
        "tracker": a.config.get("tracker"),
        "time_bin_seconds": a.config.get("time_bin_seconds"),
        "regions": [{"id": r["id"], "name": r["name"], "kind": r["kind"], "role": r.get("role")}
                    for r in a.config.get("regions", [])],
    }


@router.get("/api/analyses/{analysis_id}/export")
def export(
    analysis_id: str,
    format: Literal["csv", "csv_bundle", "xlsx", "json"] = "csv",
    db: Session = Depends(get_db),
) -> Response:
    a = _get(analysis_id, db)
    if a.status != "completed" or a.summary is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Results are available once the analysis has completed")
    zones = [zone_dict(r) for r in a.zone_counts]
    lines = [line_dict(r) for r in a.line_crossings]
    moves = [movement_dict(r) for r in a.movements]
    stem = f"{Path(a.video.original_name).stem}_{a.id[:8]}"
    meta = _meta(a)
    if format == "json":
        body, mime, ext = exporters.to_json(meta, a.summary, zones, lines, moves), "application/json", "json"
    elif format == "xlsx":
        body = exporters.to_xlsx(meta, a.summary, zones, lines, moves)
        mime, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    elif format == "csv_bundle":
        body, mime, ext = exporters.to_csv_zip(meta, a.summary, zones, lines, moves), "application/zip", "zip"
    else:
        body, mime, ext = exporters.to_csv(zones), "text/csv", "csv"
    return Response(body, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{stem}.{ext}"'})


@router.get("/api/analyses/{analysis_id}/annotated-video")
def annotated_video(analysis_id: str, download: bool = False, db: Session = Depends(get_db)) -> FileResponse:
    a = _get(analysis_id, db)
    if not a.annotated_video_path or not Path(a.annotated_video_path).exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No annotated video for this analysis")
    return FileResponse(
        a.annotated_video_path,
        media_type="video/mp4",
        filename=f"{Path(a.video.original_name).stem}_annotated.mp4",
        content_disposition_type="attachment" if download else "inline",
    )


@router.get("/api/analyses/{analysis_id}/stages")
def list_stages(analysis_id: str, db: Session = Depends(get_db)) -> dict:
    """Latest per-stage preview images (updated about once a second while running)."""
    _get(analysis_id, db)
    d = get_settings().output_dir / analysis_id / "stages"
    meta = {}
    if (d / "meta.json").exists():
        try:
            meta = json.loads((d / "meta.json").read_text())
        except ValueError:
            meta = {}
    items = []
    for key, title in STAGES:
        f = d / f"{key}.jpg"
        if f.exists():
            items.append({"key": key, "title": title, "url": f"/api/analyses/{analysis_id}/stages/{key}.jpg",
                          "version": int(f.stat().st_mtime_ns // 1_000_000)})
    live = d / "live.jpg"
    live_url = (f"/api/analyses/{analysis_id}/stages/live.jpg?v={int(live.stat().st_mtime_ns // 1_000_000)}"
                if live.exists() else None)
    return {"frame_index": meta.get("frame_index"), "timestamp": meta.get("timestamp"), "stages": items,
            "live_url": live_url}


@router.get("/api/analyses/{analysis_id}/stages/{key}.jpg")
def stage_image(analysis_id: str, key: str, db: Session = Depends(get_db)) -> FileResponse:
    _get(analysis_id, db)
    if key not in dict(STAGES) and key != "live":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown stage")
    f = get_settings().output_dir / analysis_id / "stages" / f"{key}.jpg"
    if not f.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No preview yet")
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.websocket("/api/analyses/{analysis_id}/ws")
async def progress_ws(websocket: WebSocket, analysis_id: str) -> None:
    """Pushes progress snapshots whenever they change, until a terminal state."""
    await websocket.accept()
    SessionLocal = get_sessionmaker()
    last = None

    def snapshot() -> dict | None:
        with SessionLocal() as db:
            row = db.execute(
                select(Analysis.status, Analysis.progress, Analysis.message, Analysis.live_counts,
                       Analysis.live_breakdown, Analysis.frames_processed).where(Analysis.id == analysis_id)
            ).one_or_none()
        if row is None:
            return None
        return {"status": row.status, "progress": row.progress, "message": row.message,
                "live_counts": row.live_counts or {}, "live_breakdown": row.live_breakdown or {},
                "frames_processed": row.frames_processed}

    try:
        while True:
            snap = await asyncio.to_thread(snapshot)
            if snap is None:
                await websocket.send_json({"error": "not_found"})
                break
            if snap != last:
                await websocket.send_json(snap)
                last = snap
            if snap["status"] in TERMINAL:
                break
            await asyncio.sleep(0.5)
        await websocket.close()
    except WebSocketDisconnect:
        pass
