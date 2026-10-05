"""Batches of videos, the import folder and copying areas between videos."""

import io
import shutil
import zipfile

import openpyxl
import pytest
from fastapi.testclient import TestClient

from tests.conftest import FakeDetector


@pytest.fixture
def import_dir(tmp_path, monkeypatch):
    d = tmp_path / "import"
    d.mkdir()
    monkeypatch.setenv("TV_IMPORT_DIR", str(d))
    return d


@pytest.fixture
def client(import_dir, app_env, monkeypatch):
    from app.main import create_app
    from app.workers import worker

    monkeypatch.setattr(worker, "detector_factory", lambda *a, **k: FakeDetector())
    with TestClient(create_app()) as c:
        yield c


def _upload(client, video_file, name):
    with open(video_file, "rb") as f:
        r = client.post("/api/videos", files={"file": (name, f, "video/mp4")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _run_queue():
    """Process queued analyses the way the worker does: oldest first, one at a time."""
    from app.db import get_sessionmaker
    from app.workers import worker

    order = []
    while True:
        with get_sessionmaker()() as db:
            job = worker.claim_next(db)
        if job is None:
            return order
        order.append(job.id)
        worker.process(job.id)


def test_batch_runs_every_video_in_order_with_its_own_areas(client, video_file):
    a = _upload(client, video_file, "site_a.mp4")
    b = _upload(client, video_file, "site_b.mp4")
    c = _upload(client, video_file, "site_c.mp4")
    # site_a: the car's road; site_b: the bus's road; site_c: nothing drawn -> whole frame
    client.post(f"/api/videos/{a}/regions", json={"name": "Top road", "kind": "polygon",
                                                  "points": [[0, 0.1], [0.7, 0.1], [0.7, 0.45], [0, 0.45]]})
    client.post(f"/api/videos/{b}/regions", json={"name": "Right road", "kind": "polygon",
                                                  "points": [[0.75, 0.5], [0.95, 0.5], [0.95, 1], [0.75, 1]]})
    listed = {v["id"]: v for v in client.get("/api/videos").json()}
    assert (listed[a]["area_count"], listed[c]["area_count"], listed[a]["region_names"]) == (1, 0, ["Top road"])

    r = client.post("/api/batches", json={"name": "Survey week 1", "video_ids": [b, a, c],
                                          "settings": {"count_rule": "present", "tracker": "iou", "speed": "fast"}})
    assert r.status_code == 201, r.text
    batch = r.json()
    assert [i["video_id"] for i in batch["items"]] == [b, a, c]
    assert batch["status"] == "queued" and batch["status_counts"]["queued"] == 3
    assert [i["areas"] for i in batch["items"]] == [["Right road"], ["Top road"], ["Whole Frame"]]

    order = _run_queue()
    assert order == [i["analysis_id"] for i in batch["items"]]  # one by one, in submitted order

    done = client.get(f"/api/batches/{batch['id']}").json()
    assert done["status"] == "completed" and done["progress"] == 1.0
    counts = [i["counts"] for i in done["items"]]
    assert counts == [{"Right road": 1}, {"Top road": 1}, {"Whole Frame": 2}]
    assert [i["by_type"] for i in done["items"]] == [{"bus": 1}, {"car": 1}, {"car": 1, "bus": 1}]
    # Each video has its own ordinary report.
    rep = client.get(f"/api/analyses/{done['items'][1]['analysis_id']}").json()
    assert rep["summary"]["processing"]["speed"] == "fast"
    assert client.get(f"/api/analyses/{done['items'][1]['analysis_id']}/export?format=xlsx").status_code == 200

    # One table for the whole batch...
    wb = openpyxl.load_workbook(io.BytesIO(client.get(f"/api/batches/{batch['id']}/export?format=xlsx").content))
    rows = list(wb["All videos"].iter_rows(values_only=True))
    assert rows[0][:6] == ("#", "video", "status", "area / line", "kind", "total")
    assert [(r[0], r[1], r[3], r[5]) for r in rows[1:]] == [
        (1, "site_b.mp4", "Right road", 1), (2, "site_a.mp4", "Top road", 1), (3, "site_c.mp4", "Whole Frame", 2)]
    # ...and a zip with every video's own report.
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/batches/{batch['id']}/export?format=zip").content))
    assert sorted(z.namelist()) == ["all_videos.csv", "all_videos.xlsx", "videos/001_site_b.xlsx",
                                    "videos/002_site_a.xlsx", "videos/003_site_c.xlsx"]
    assert client.get("/api/batches").json()[0]["videos"] == 3


def test_batch_cancel_retry_and_delete(client, video_file):
    ids = [_upload(client, video_file, f"v{i}.mp4") for i in range(3)]
    batch = client.post("/api/batches", json={"video_ids": ids, "settings": {"tracker": "iou"}}).json()
    assert batch["name"].startswith("Batch of 3 videos")
    assert client.delete(f"/api/batches/{batch['id']}").status_code == 409  # still queued

    from app.db import get_sessionmaker
    from app.workers import worker

    with get_sessionmaker()() as db:
        first = worker.claim_next(db)
    worker.process(first.id)
    r = client.post(f"/api/batches/{batch['id']}/cancel").json()
    assert r["status_counts"] == {"queued": 0, "running": 0, "completed": 1, "failed": 0, "cancelled": 2}
    assert r["status"] == "finished"

    r = client.post(f"/api/batches/{batch['id']}/retry").json()
    assert r["status_counts"]["queued"] == 2 and r["status_counts"]["completed"] == 1
    assert len(_run_queue()) == 2
    assert client.get(f"/api/batches/{batch['id']}").json()["status"] == "completed"

    assert client.delete(f"/api/batches/{batch['id']}").status_code == 204
    assert client.get(f"/api/batches/{batch['id']}").status_code == 404
    assert client.get(f"/api/videos/{ids[0]}/analyses").json() == []  # analyses removed, videos kept
    assert client.get(f"/api/videos/{ids[0]}").status_code == 200


def test_batch_validation(client, video_file):
    vid = _upload(client, video_file, "short.mp4")  # 3 s
    assert client.post("/api/batches", json={"video_ids": []}).status_code == 422
    assert client.post("/api/batches", json={"video_ids": ["nope"]}).status_code == 404
    r = client.post("/api/batches", json={"video_ids": [vid], "settings": {"start_seconds": 10}})
    assert r.status_code == 422 and "short.mp4" in r.text
    assert client.post("/api/batches", json={"video_ids": [vid], "settings": {"speed": "warp"}}).status_code == 422


def test_import_folder_registers_files_in_place(client, video_file, import_dir):
    (import_dir / "day1").mkdir()
    shutil.copy(video_file, import_dir / "day1" / "cam1.mp4")
    shutil.copy(video_file, import_dir / "cam2.MP4")
    (import_dir / "notes.txt").write_text("not a video")

    listing = client.get("/api/videos/import").json()
    assert listing["enabled"] is True
    assert [(f["path"], f["imported"]) for f in listing["files"]] == [("cam2.MP4", False), ("day1/cam1.mp4", False)]

    r = client.post("/api/videos/import", json={"paths": ["day1/cam1.mp4", "cam2.MP4"]})
    assert r.status_code == 201, r.text
    videos = r.json()
    assert [v["original_name"] for v in videos] == ["day1/cam1.mp4", "cam2.MP4"]
    assert videos[0]["imported"] is True and videos[0]["frame_count"] == 60
    # Importing again does not duplicate.
    again = client.post("/api/videos/import", json={"paths": ["cam2.MP4"]}).json()
    assert again[0]["id"] == videos[1]["id"]
    assert all(f["imported"] for f in client.get("/api/videos/import").json()["files"])

    for bad in ("../secret.mp4", "/etc/passwd", "notes.txt", "missing.mp4"):
        assert client.post("/api/videos/import", json={"paths": [bad]}).status_code in (415, 422), bad

    # Deleting an imported video leaves the original file alone.
    assert client.delete(f"/api/videos/{videos[0]['id']}").status_code == 204
    assert (import_dir / "day1" / "cam1.mp4").exists()


def test_import_folder_disabled(app_env, monkeypatch):
    from app.main import create_app

    monkeypatch.delenv("TV_IMPORT_DIR", raising=False)
    with TestClient(create_app()) as c:
        assert c.get("/api/videos/import").json() == {"enabled": False, "folder": None, "files": []}
        assert c.post("/api/videos/import", json={"paths": ["a.mp4"]}).status_code == 404


def test_copy_areas_from_another_video(client, video_file):
    src = _upload(client, video_file, "monday.mp4")
    dst = _upload(client, video_file, "tuesday.mp4")
    for name, kind, pts in [("North", "polygon", [[0, 0], [0.5, 0], [0.5, 0.5]]), ("Gate", "line", [[0, 1], [1, 1]])]:
        client.post(f"/api/videos/{src}/regions", json={"name": name, "kind": kind, "points": pts})
    client.post(f"/api/videos/{dst}/regions", json={"name": "Old", "kind": "polygon", "points": [[0, 0], [1, 0], [1, 1]]})

    r = client.post(f"/api/videos/{dst}/regions/copy", json={"from_video_id": src, "replace": False})
    assert [x["name"] for x in r.json()] == ["Old", "North", "Gate"]
    r = client.post(f"/api/videos/{dst}/regions/copy", json={"from_video_id": src, "replace": False})
    assert [x["name"] for x in r.json()][-2:] == ["North (2)", "Gate (2)"]  # names stay unique
    r = client.post(f"/api/videos/{dst}/regions/copy", json={"from_video_id": src})
    copied = r.json()
    assert [(x["name"], x["kind"]) for x in copied] == [("North", "polygon"), ("Gate", "line")]
    assert copied[0]["points"] == [[0, 0], [0.5, 0], [0.5, 0.5]]
    assert client.post(f"/api/videos/{dst}/regions/copy", json={"from_video_id": dst}).status_code == 422
