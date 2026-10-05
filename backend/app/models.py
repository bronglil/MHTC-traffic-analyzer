from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    original_name: Mapped[str] = mapped_column(String(512))
    stored_path: Mapped[str] = mapped_column(String(1024))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    fps: Mapped[float] = mapped_column(Float, default=0.0)
    frame_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    # Registered in place from the import folder (TV_IMPORT_DIR): the file is not ours to delete.
    imported: Mapped[bool | None] = mapped_column(default=False, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    regions: Mapped[list[Region]] = relationship(
        back_populates="video", cascade="all, delete-orphan", order_by="Region.created_at"
    )
    analyses: Mapped[list[Analysis]] = relationship(
        back_populates="video", cascade="all, delete-orphan", order_by="Analysis.created_at.desc()"
    )


class Region(Base):
    """A named polygon ROI or counting line, in normalized [0,1] coordinates."""

    __tablename__ = "regions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16))  # polygon | line
    points: Mapped[list[list[float]]] = mapped_column(JSON)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    label_forward: Mapped[str] = mapped_column(String(64), default="A→B")
    label_backward: Mapped[str] = mapped_column(String(64), default="B→A")
    # Polygons only: count | in | out | both — roads used for movement counting
    role: Mapped[str | None] = mapped_column(String(8), nullable=True, default="count")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    video: Mapped[Video] = relationship(back_populates="regions")


class Batch(Base):
    """Many videos analysed one after another with the same settings; each video
    keeps its own areas/lines (or the whole frame when it has none) and report."""

    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    settings: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    analyses: Mapped[list[Analysis]] = relationship(back_populates="batch", order_by="Analysis.batch_position")


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("batches.id", ondelete="SET NULL"), nullable=True,
                                                 index=True)
    batch_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Snapshot of settings + regions at submission time, so results stay
    # reproducible even if the video's ROIs are edited afterwards.
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    live_counts: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    # {zone/line id: {total, by_type, by_direction}} including still-active tracks
    live_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    annotated_video_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    frames_processed: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    video: Mapped[Video] = relationship(back_populates="analyses")
    batch: Mapped[Batch | None] = relationship(back_populates="analyses")
    zone_counts: Mapped[list[ZoneCountRecord]] = relationship(
        cascade="all, delete-orphan", order_by="ZoneCountRecord.first_time"
    )
    line_crossings: Mapped[list[LineCrossingRecord]] = relationship(
        cascade="all, delete-orphan", order_by="LineCrossingRecord.time"
    )
    movements: Mapped[list[MovementRecord]] = relationship(
        cascade="all, delete-orphan", order_by="MovementRecord.start_time"
    )


class ZoneCountRecord(Base):
    """One unique vehicle counted in one area (whole frame or ROI)."""

    __tablename__ = "zone_counts"
    __table_args__ = (Index("ix_zone_counts_analysis_zone", "analysis_id", "zone_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"))
    zone_id: Mapped[str] = mapped_column(String(64))
    zone_name: Mapped[str] = mapped_column(String(200))
    track_id: Mapped[int] = mapped_column(Integer)
    vehicle_type: Mapped[str] = mapped_column(String(32))
    direction: Mapped[str] = mapped_column(String(32))
    first_frame: Mapped[int] = mapped_column(Integer)
    last_frame: Mapped[int] = mapped_column(Integer)
    first_time: Mapped[float] = mapped_column(Float)
    last_time: Mapped[float] = mapped_column(Float)
    frames_in_zone: Mapped[int] = mapped_column(Integer)
    mean_confidence: Mapped[float] = mapped_column(Float)


class LineCrossingRecord(Base):
    __tablename__ = "line_crossings"
    __table_args__ = (Index("ix_line_crossings_analysis_line", "analysis_id", "line_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"))
    line_id: Mapped[str] = mapped_column(String(64))
    line_name: Mapped[str] = mapped_column(String(200))
    track_id: Mapped[int] = mapped_column(Integer)
    vehicle_type: Mapped[str] = mapped_column(String(32))
    direction: Mapped[str] = mapped_column(String(64))
    frame: Mapped[int] = mapped_column(Integer)
    time: Mapped[float] = mapped_column(Float)


class MovementRecord(Base):
    """One vehicle that entered via one road (area) and left via another."""

    __tablename__ = "movements"
    __table_args__ = (Index("ix_movements_analysis", "analysis_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"))
    from_id: Mapped[str] = mapped_column(String(64))
    from_name: Mapped[str] = mapped_column(String(200))
    to_id: Mapped[str] = mapped_column(String(64))
    to_name: Mapped[str] = mapped_column(String(200))
    track_id: Mapped[int] = mapped_column(Integer)
    vehicle_type: Mapped[str] = mapped_column(String(32))
    start_frame: Mapped[int] = mapped_column(Integer)
    end_frame: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[float] = mapped_column(Float)
    end_time: Mapped[float] = mapped_column(Float)


ZONE_FIELDS = [
    "zone_id", "zone_name", "track_id", "vehicle_type", "direction", "first_frame",
    "last_frame", "first_time", "last_time", "frames_in_zone", "mean_confidence",
]
LINE_FIELDS = ["line_id", "line_name", "track_id", "vehicle_type", "direction", "frame", "time"]


def zone_dict(r: ZoneCountRecord) -> dict[str, Any]:
    return {f: getattr(r, f) for f in ZONE_FIELDS}


def line_dict(r: LineCrossingRecord) -> dict[str, Any]:
    return {f: getattr(r, f) for f in LINE_FIELDS}


MOVEMENT_FIELDS = ["from_id", "from_name", "to_id", "to_name", "track_id", "vehicle_type",
                   "start_frame", "end_frame", "start_time", "end_time"]


def movement_dict(r: MovementRecord) -> dict[str, Any]:
    return {f: getattr(r, f) for f in MOVEMENT_FIELDS}
