"""Generate ``videos/synthetic_junction.mp4``: a 4-arm crossroads seen from above.

Five vehicles drive through one after another, each from one road to another,
so every per-road count and every movement (origin -> destination) is known
exactly. Used to test multi-road selection, road naming and movement counting.

    python tests/data/make_synthetic_junction.py
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

W, H, FPS = 640, 360, 25
CX, CY = 320, 180
# Road arms (the junction box in the middle belongs to no road).
ARMS = {
    "North": [(270, 0), (370, 0), (370, 130), (270, 130)],
    "South": [(270, 230), (370, 230), (370, 360), (270, 360)],
    "West": [(0, 130), (220, 130), (220, 230), (0, 230)],
    "East": [(420, 130), (640, 130), (640, 230), (420, 230)],
}
# Start/finish points lie beyond the picture, so vehicles drive into and out of view like real traffic.
ENDS = {"North": (CX, -30), "South": (CX, H + 30), "West": (-40, CY), "East": (W + 40, CY)}
# (type, colour BGR, size w x h, from, to)
VEHICLES = [
    ("car", (0, 200, 0), (30, 30), "North", "South"),
    ("bus", (200, 60, 0), (54, 34), "West", "East"),
    ("car", (0, 200, 0), (30, 30), "South", "East"),
    ("car", (0, 200, 0), (30, 30), "East", "North"),
    ("car", (0, 200, 0), (30, 30), "West", "South"),
]
SPEED = 7.0  # pixels per frame, constant (no jump in speed at the turn)
GAP = 6


def path(a: str, b: str) -> list[tuple[float, float]]:
    """From the outer end of road a, through the junction centre, to the end of road b."""
    p0, p1, p2 = np.array(ENDS[a], float), np.array((CX, CY), float), np.array(ENDS[b], float)
    pts = []
    for s, e, last in ((p0, p1, False), (p1, p2, True)):
        n = max(1, int(np.linalg.norm(e - s) / SPEED))
        pts += [s + (e - s) * i / n for i in range(n + (1 if last else 0))]
    return [tuple(p) for p in pts]


def background() -> np.ndarray:
    img = np.full((H, W, 3), (70, 110, 70), np.uint8)  # verge
    cv2.rectangle(img, (270, 0), (370, H), (90, 90, 90), -1)
    cv2.rectangle(img, (0, 130), (W, 230), (90, 90, 90), -1)
    for x in range(0, W, 40):
        if not 260 < x < 380:
            cv2.line(img, (x, CY), (x + 20, CY), (230, 230, 230), 2)
    for y in range(0, H, 40):
        if not 120 < y < 240:
            cv2.line(img, (CX, y), (CX, y + 20), (230, 230, 230), 2)
    return img


def main(out: Path = Path(__file__).parent / "videos" / "synthetic_junction.mp4") -> Path:
    bg = background()
    tmp = out.with_suffix(".tmp.mp4")
    writer = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for _ in range(10):  # empty road first, so a background model can learn it
        writer.write(bg)
    for _vtype, colour, (w, h), a, b in VEHICLES:
        for x, y in path(a, b):
            img = bg.copy()
            cv2.rectangle(img, (int(x - w / 2), int(y - h / 2)), (int(x + w / 2), int(y + h / 2)), colour, -1)
            writer.write(img)
        for _ in range(GAP):
            writer.write(bg)
    writer.release()
    import shutil
    import subprocess

    if shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-c:v", "libx264", "-crf", "18",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], check=True)
        tmp.unlink()
    else:
        tmp.replace(out)
    return out


if __name__ == "__main__":
    print(main())
