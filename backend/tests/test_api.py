import pytest
from fastapi.testclient import TestClient

from tests.conftest import FakeDetector


@pytest.fixture
def client(app_env, monkeypatch):
    from app.main import create_app
    from app.workers import worker

    monkeypatch.setattr(worker, "detector_factory", lambda *a, **k: FakeDetector())
    with TestClient(create_app()) as c:
        yield c


def _upload(client, video_file):
    with open(video_file, "rb") as f:
        r = client.post("/api/videos", files={"file": ("traffic.mp4", f, "video/mp4")})
    assert r.status_code == 201, r.text
    return r.json()


def test_upload_rejects_bad_files(client, tmp_path):
    r = client.post("/api/videos", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 415
    r = client.post("/api/videos", files={"file": ("broken.mp4", b"not a video", "video/mp4")})
    assert r.status_code == 422


def test_full_flow(client, video_file):
    from app.db import get_sessionmaker
    from app.workers import worker

    video = _upload(client, video_file)
    assert (video["width"], video["height"], video["frame_count"]) == (640, 360, 60)
    vid = video["id"]
    assert client.get(f"/api/videos/{vid}/file").status_code == 200
    assert client.get(f"/api/videos/{vid}/thumbnail").headers["content-type"] == "image/jpeg"

    # ROI create / rename / validate
    r = client.post(f"/api/videos/{vid}/regions", json={
        "name": "Left", "kind": "polygon", "points": [[0, 0], [0.5, 0], [0.5, 1], [0, 1]]})
    assert r.status_code == 201
    roi = r.json()
    assert roi["color"] == "#f59e0b"  # first palette colour, assigned by the server
    r = client.patch(f"/api/videos/{vid}/regions/{roi['id']}", json={"name": "Left lane"})
    assert r.json()["name"] == "Left lane"
    assert client.patch(f"/api/videos/{vid}/regions/{roi['id']}", json={"points": [[0, 0], [1, 1]]}).status_code == 422
    assert client.post(f"/api/videos/{vid}/regions", json={
        "name": "Bad", "kind": "line", "points": [[0, 0]]}).status_code == 422
    client.post(f"/api/videos/{vid}/regions", json={
        "name": "Gate", "kind": "line", "points": [[0.5, 0], [0.5, 1]],
        "label_forward": "westbound", "label_backward": "eastbound"})
    regions = client.get(f"/api/videos/{vid}").json()["regions"]
    assert len(regions) == 2 and regions[0]["color"] != regions[1]["color"]
    assert client.post(f"/api/videos/{vid}/regions", json={
        "name": "left lane", "kind": "polygon", "points": [[0, 0], [0.2, 0], [0.2, 0.2]]}).status_code == 409
    assert client.patch(f"/api/videos/{vid}/regions/{roi['id']}", json={"name": "GATE"}).status_code == 409
    assert client.patch(f"/api/videos/{vid}/regions/{roi['id']}", json={"color": "red;x"}).status_code == 422

    assert client.post(f"/api/videos/{vid}/analyses", json={"vehicle_types": ["plane"]}).status_code == 422
    r = client.post(f"/api/videos/{vid}/analyses", json={
        "vehicle_types": ["car", "bus"], "tracker": "iou", "generate_annotated_video": True})
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    assert r.json()["status"] == "queued"
    assert client.get(f"/api/analyses/{aid}/export?format=csv").status_code == 409

    # Run the queued job synchronously.
    with get_sessionmaker()() as db:
        job = worker.claim_next(db)
    assert job.id == aid
    worker.process(aid)

    with client.websocket_connect(f"/api/analyses/{aid}/ws") as ws:
        msg = ws.receive_json()
    assert msg["status"] == "completed"

    res = client.get(f"/api/analyses/{aid}").json()
    assert res["status"] == "completed", res["message"]
    assert res["has_annotated_video"]
    assert res["live_breakdown"]["whole_frame"]["by_type"] == {"car": 1, "bus": 1}
    stages = client.get(f"/api/analyses/{aid}/stages").json()
    assert stages["live_url"] and client.get(stages["live_url"]).status_code == 200
    areas = {a["name"]: a["total"] for a in res["summary"]["areas"]}
    assert areas == {"Whole Frame": 2, "Left lane": 1}
    assert res["summary"]["lines"][0]["by_direction"] == {"eastbound": 1}

    for fmt, ctype in [("csv", "text/csv"), ("xlsx", "spreadsheetml"), ("json", "application/json"),
                       ("csv_bundle", "zip")]:
        r = client.get(f"/api/analyses/{aid}/export?format={fmt}")
        assert r.status_code == 200 and ctype in r.headers["content-type"]
        assert "attachment" in r.headers["content-disposition"]
    assert client.get(f"/api/analyses/{aid}/annotated-video").status_code == 200
    assert len(client.get(f"/api/analyses/{aid}/vehicles").json()["items"]) == 3

    # ROI edits after the run do not change stored results
    client.delete(f"/api/videos/{vid}/regions/{roi['id']}")
    assert {a["name"] for a in client.get(f"/api/analyses/{aid}").json()["summary"]["areas"]} == {
        "Whole Frame", "Left lane"}

    assert client.delete(f"/api/videos/{vid}").status_code == 204
    assert client.get(f"/api/analyses/{aid}").status_code == 404


def test_cancel_queued(client, video_file):
    vid = _upload(client, video_file)["id"]
    aid = client.post(f"/api/videos/{vid}/analyses", json={}).json()["id"]
    assert client.post(f"/api/analyses/{aid}/cancel").json()["status"] == "cancelled"
    from app.db import get_sessionmaker
    from app.workers import worker

    with get_sessionmaker()() as db:
        assert worker.claim_next(db) is None


def test_adds_missing_nullable_columns(app_env):
    """A database created before a nullable column existed is upgraded in place."""
    from sqlalchemy import inspect, text

    from app.db import get_engine, init_db

    init_db()
    with get_engine().begin() as conn:
        conn.execute(text("ALTER TABLE analyses DROP COLUMN live_breakdown"))
    init_db()
    assert "live_breakdown" in {c["name"] for c in inspect(get_engine()).get_columns("analyses")}
