from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TV_", env_file=".env", extra="ignore")

    # PostgreSQL in deployment, e.g. postgresql+psycopg://user:pass@db:5432/traffic_vision.
    # SQLite is accepted for local development and tests.
    database_url: str = "sqlite:///./data/traffic_vision.db"
    data_dir: Path = Path("./data")
    max_upload_mb: int = 16384
    # Folder of videos that can be registered without uploading them through the
    # browser (e.g. hours-long survey footage); mounted read-only in Docker.
    import_dir: Path | None = None
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Detection / tracking defaults (overridable per analysis)
    model_path: str = "yolo11n.pt"
    device: str | None = None  # "cpu", "cuda:0", "mps"; None = auto
    default_tracker: str = "bytetrack"
    # Optional YOLO classification model (classes e.g. car/lgv1/lgv2/truck/bus...)
    classifier_model: str | None = None

    # Run a worker thread inside the API process. Disable when running
    # dedicated `python -m app.workers.worker` processes.
    embedded_worker: bool = True
    worker_poll_seconds: float = 1.0

    @property
    def models_dir(self) -> Path:
        """Custom weights (detector / classifier) are looked up here by file name."""
        return self.data_dir / "models"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "outputs"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    s.output_dir.mkdir(parents=True, exist_ok=True)
    s.models_dir.mkdir(parents=True, exist_ok=True)
    return s
