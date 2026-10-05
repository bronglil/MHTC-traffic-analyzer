from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.colors import next_region_color
from app.config import get_settings
from app.db import get_db
from app.models import Region, Video
from app.pipeline.frames import VideoReadError, probe
from app.schemas import (
    CopyRegionsRequest,
    ImportRequest,
    RegionCreate,
    RegionOut,
    RegionUpdate,
    VideoDetail,
    VideoListItem,
    VideoOut,
)

router = APIRouter(prefix="/api/videos", tags=["videos"])

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".ogv", ".ogg", ".m4v", ".mpg", ".mpeg", ".ts", ".wmv", ".flv", ".3gp"}
CHUNK = 1024 * 1024


def get_video_or_404(video_id: str, db: Session) -> Video:
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    return video


@router.post("", response_model=VideoOut, status_code=status.HTTP_201_CREATED)
def upload_video(file: UploadFile = File(...), db: Session = Depends(get_db)) -> Video:
    settings = get_settings()
    name = Path(file.filename or "video").name
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"Unsupported file type {ext!r}")

    video = Video(original_name=name, stored_path="")
    db.add(video)
    db.flush()
    dest = settings.upload_dir / f"{video.id}{ext}"
    limit = settings.max_upload_mb * 1024 * 1024
    size = 0
    try:
        with dest.open("wb") as out:
            while chunk := file.file.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large")
                out.write(chunk)
        info = probe(str(dest))
    except VideoReadError as exc:
        dest.unlink(missing_ok=True)
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    except BaseException:
        dest.unlink(missing_ok=True)
        db.rollback()
        raise

    video.stored_path = str(dest)
    video.size_bytes = size
    video.width, video.height = info.width, info.height
    video.fps, video.frame_count = info.fps, info.frame_count
    video.duration_seconds = info.duration
    db.commit()
    return video


@router.get("", response_model=list[VideoListItem])
def list_videos(db: Session = Depends(get_db)) -> list[VideoListItem]:
    out = []
    for v in db.scalars(select(Video).order_by(Video.created_at.desc())):
        item = VideoListItem.model_validate(v)
        item.area_count = sum(r.kind == "polygon" for r in v.regions)
        item.line_count = sum(r.kind == "line" for r in v.regions)
        item.region_names = [r.name for r in v.regions]
        if v.analyses:  # newest first
            item.latest_analysis_id, item.latest_status = v.analyses[0].id, v.analyses[0].status
        out.append(item)
    return out


# ------------------------------------------------------------ import folder
def _import_root() -> Path:
    root = get_settings().import_dir
    if root is None or not Path(root).is_dir():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No import folder is configured (set TV_IMPORT_DIR)")
    return Path(root).resolve()


@router.get("/import")
def list_import_folder(db: Session = Depends(get_db)) -> dict:
    """Video files in the import folder, so long recordings need not be uploaded through the browser."""
    root = get_settings().import_dir
    if root is None or not Path(root).is_dir():
        return {"enabled": False, "folder": str(root) if root else None, "files": []}
    root = Path(root).resolve()
    known = set(db.scalars(select(Video.stored_path).where(Video.imported.is_(True))))
    files = []
    for f in sorted(root.rglob("*")):
        if f.is_file() and f.suffix.lower() in ALLOWED_EXTENSIONS and not any(p.startswith(".") for p in f.parts):
            files.append({"path": f.relative_to(root).as_posix(), "size_bytes": f.stat().st_size,
                          "imported": str(f) in known})
    return {"enabled": True, "folder": str(root), "files": files}


@router.post("/import", response_model=list[VideoOut], status_code=status.HTTP_201_CREATED)
def import_videos(body: ImportRequest, db: Session = Depends(get_db)) -> list[Video]:
    """Register files from the import folder in place (nothing is copied)."""
    root = _import_root()
    created = []
    for rel in body.paths:
        path = (root / rel).resolve()
        if root not in path.parents or not path.is_file():
            raise HTTPException(422, f"Not a file in the import folder: {rel!r}")
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"Unsupported file type: {rel!r}")
        existing = db.scalars(select(Video).where(Video.stored_path == str(path))).first()
        if existing is not None:
            created.append(existing)
            continue
        try:
            info = probe(str(path))
        except VideoReadError as exc:
            raise HTTPException(422, f"{rel}: {exc}") from exc
        video = Video(original_name=rel, stored_path=str(path), size_bytes=path.stat().st_size, imported=True,
                      width=info.width, height=info.height, fps=info.fps, frame_count=info.frame_count,
                      duration_seconds=info.duration)
        db.add(video)
        db.flush()
        created.append(video)
    db.commit()
    return created


@router.get("/{video_id}", response_model=VideoDetail)
def get_video(video_id: str, db: Session = Depends(get_db)) -> Video:
    return get_video_or_404(video_id, db)


@router.delete("/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_video(video_id: str, db: Session = Depends(get_db)) -> None:
    video = get_video_or_404(video_id, db)
    if any(a.status in ("queued", "running") for a in video.analyses):
        raise HTTPException(status.HTTP_409_CONFLICT, "Cancel running analyses before deleting the video")
    files = [] if video.imported else [video.stored_path]  # imported files stay in the import folder
    files += [a.annotated_video_path for a in video.analyses if a.annotated_video_path]
    dirs = [get_settings().output_dir / a.id for a in video.analyses]
    db.delete(video)
    db.commit()
    for f in files:
        Path(f).unlink(missing_ok=True)
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)


@router.get("/{video_id}/file")
def stream_video(video_id: str, db: Session = Depends(get_db)) -> FileResponse:
    video = get_video_or_404(video_id, db)
    return FileResponse(video.stored_path, filename=video.original_name, content_disposition_type="inline")


@router.get("/{video_id}/frame")
def frame_at(video_id: str, t: float = 0.0, max_width: int = 1280, db: Session = Depends(get_db)) -> Response:
    """A decoded frame as JPEG. Lets the UI show any codec OpenCV can read, even
    ones the browser cannot play (e.g. some AVI / H.265 files)."""
    video = get_video_or_404(video_id, db)
    cap = cv2.VideoCapture(video.stored_path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        target = max(0, int(t * fps))
        if target:
            cap.set(cv2.CAP_PROP_POS_FRAMES, target)
        ok, img = cap.read()
    finally:
        cap.release()
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No frame at that time")
    h, w = img.shape[:2]
    max_width = max(64, min(max_width, 3840))
    if w > max_width:
        img = cv2.resize(img, (max_width, int(h * max_width / w)), interpolation=cv2.INTER_AREA)
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return Response(buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


@router.get("/{video_id}/thumbnail")
def thumbnail(video_id: str, db: Session = Depends(get_db)) -> Response:
    video = get_video_or_404(video_id, db)
    cap = cv2.VideoCapture(video.stored_path)
    ok, img = cap.read()
    cap.release()
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No frame available")
    h, w = img.shape[:2]
    scale = 320 / max(w, 1)
    img = cv2.resize(img, (320, max(1, int(h * scale))))
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return Response(buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


# ----------------------------------------------------------------- regions
@router.get("/{video_id}/regions", response_model=list[RegionOut])
def list_regions(video_id: str, db: Session = Depends(get_db)) -> list[Region]:
    return get_video_or_404(video_id, db).regions


@router.post("/{video_id}/regions", response_model=RegionOut, status_code=status.HTTP_201_CREATED)
def create_region(video_id: str, body: RegionCreate, db: Session = Depends(get_db)) -> Region:
    video = get_video_or_404(video_id, db)
    _ensure_unique_name(video, body.name)
    data = body.model_dump()
    # Every area/line gets its own colour, used consistently in the editor,
    # live view, annotated video and results.
    data["color"] = data.get("color") or next_region_color([r.color for r in video.regions])
    region = Region(video_id=video_id, **data)
    db.add(region)
    db.commit()
    return region


@router.post("/{video_id}/regions/copy", response_model=list[RegionOut])
def copy_regions(video_id: str, body: CopyRegionsRequest, db: Session = Depends(get_db)) -> list[Region]:
    """Copy another video's areas and lines (same camera position): positions are
    stored relative to the picture, so they fit any resolution of the same view."""
    video = get_video_or_404(video_id, db)
    source = get_video_or_404(body.from_video_id, db)
    if source.id == video.id:
        raise HTTPException(422, "Choose a different video to copy from")
    if body.replace:
        for r in list(video.regions):
            db.delete(r)
        db.flush()
        db.refresh(video)
    taken = {r.name.strip().lower() for r in video.regions}
    base = datetime.now(UTC)
    for i, r in enumerate(source.regions):
        name = r.name
        n = 2
        while name.strip().lower() in taken:
            name = f"{r.name} ({n})"
            n += 1
        taken.add(name.strip().lower())
        db.add(Region(video_id=video.id, name=name, kind=r.kind, points=r.points, color=r.color, role=r.role,
                      label_forward=r.label_forward, label_backward=r.label_backward,
                      created_at=base + timedelta(milliseconds=i)))  # keep the source's order
    db.commit()
    db.refresh(video)
    return video.regions


def _ensure_unique_name(video: Video, name: str, exclude_id: str | None = None) -> None:
    """Results are reported per road name, so names must be unique within a video."""
    if any(r.name.strip().lower() == name.strip().lower() and r.id != exclude_id for r in video.regions):
        raise HTTPException(status.HTTP_409_CONFLICT, f"A road/area/line named {name!r} already exists")


def _get_region(video_id: str, region_id: str, db: Session) -> Region:
    region = db.get(Region, region_id)
    if region is None or region.video_id != video_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Region not found")
    return region


@router.patch("/{video_id}/regions/{region_id}", response_model=RegionOut)
def update_region(video_id: str, region_id: str, body: RegionUpdate, db: Session = Depends(get_db)) -> Region:
    region = _get_region(video_id, region_id, db)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"]:
        _ensure_unique_name(region.video, changes["name"], exclude_id=region.id)
    # Re-validate the merged region so edits cannot produce invalid shapes.
    try:
        merged = RegionCreate(
            name=changes.get("name", region.name),
            kind=region.kind,
            points=changes.get("points", region.points),
            color=changes.get("color", region.color),
            label_forward=changes.get("label_forward", region.label_forward),
            label_backward=changes.get("label_backward", region.label_backward),
            role=changes.get("role", region.role),
        )
    except ValidationError as exc:
        raise HTTPException(422, jsonable_encoder(exc.errors())) from exc
    for k, v in merged.model_dump().items():
        setattr(region, k, v)
    db.commit()
    return region


@router.delete("/{video_id}/regions/{region_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_region(video_id: str, region_id: str, db: Session = Depends(get_db)) -> None:
    db.delete(_get_region(video_id, region_id, db))
    db.commit()

