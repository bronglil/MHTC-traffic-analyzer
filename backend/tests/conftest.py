from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.pipeline.types import Detection

W, H, FPS, N_FRAMES = 640, 360, 20, 60

# BGR colour -> vehicle type used by the synthetic video and FakeDetector.
COLORS = {"car": (0, 255, 0), "bus": (255, 0, 0)}


def make_video(path: Path) -> Path:
    """Car drives left->right across the top band; bus drives top->bottom on the right."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for i in range(N_FRAMES):
        img = np.zeros((H, W, 3), np.uint8)
        cx = int(20 + i * (W - 100) / N_FRAMES)
        cv2.rectangle(img, (cx, 80), (cx + 60, 120), COLORS["car"], -1)
        by = int(10 + i * (H - 100) / N_FRAMES)
        cv2.rectangle(img, (500, by), (580, by + 70), COLORS["bus"], -1)
        writer.write(img)
    writer.release()
    return path


class FakeDetector:
    """Finds solid colour blobs; stands in for YOLO in tests."""

    def detect(self, image: np.ndarray) -> list[Detection]:
        out = []
        for vtype, bgr in COLORS.items():
            lo = np.clip(np.array(bgr) - 60, 0, 255)
            hi = np.clip(np.array(bgr) + 60, 0, 255)
            mask = cv2.inRange(image, lo, hi)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in contours:
                x, y, w, h = cv2.boundingRect(c)
                if w * h > 200:
                    out.append(Detection(x, y, x + w, y + h, 0.9, vtype))
        return out


@pytest.fixture
def video_file(tmp_path: Path) -> Path:
    return make_video(tmp_path / "synthetic.mp4")


@pytest.fixture
def app_env(tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("TV_DATA_DIR", str(data))
    monkeypatch.setenv("TV_DATABASE_URL", f"sqlite:///{data}/test.db")
    monkeypatch.setenv("TV_EMBEDDED_WORKER", "false")
    data.mkdir()
    from app import config, db

    config.get_settings.cache_clear()
    db.get_engine.cache_clear()
    db.get_sessionmaker.cache_clear()
    yield
    db.get_engine().dispose()
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()
    db.get_sessionmaker.cache_clear()
    os.environ.pop("TV_DATA_DIR", None)
