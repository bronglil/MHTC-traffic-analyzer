# Traffic Vision

**Traffic Vision** is a video-based vehicle detection, tracking, counting and
traffic-analysis platform. You upload a traffic video, draw areas and counting
lines, choose vehicle types, and get unique-vehicle counts by **area**, **vehicle
type**, **direction** and **time period**. Results export as CSV, XLSX or JSON,
and you can also generate an annotated video.

## Features

- Upload, play back and scrub traffic videos. Codecs the browser can't play are
  shown as frames decoded on the server.
- **Whole Frame** analysis, used automatically when no area is drawn, plus any
  number of **named polygon ROIs** analysed at the same time.
- **Counting lines / gates** with named directions (e.g. "northbound" /
  "southbound").
- Vehicle types: **Car, LGV1 (small van), LGV2 (large van), Truck/HGV,
  Bus/Coach, Motorcycle, Bicycle**. See
  [docs/vehicle-classification.md](docs/vehicle-classification.md).
- Detection with **YOLO** (any Ultralytics model, including custom-trained
  ones), or a **motion detector** for fixed overhead cameras.
- Tracking with **ByteTrack** or **BoT-SORT**. Persistent track IDs mean each
  vehicle is counted **once per area and once per line**.
- **Per-track classification** stage: size rules or a custom crop classifier
  split vans into LGV1/LGV2 and correct mislabelled large vans.
- **Direction of travel** (8-way compass in image space) per area, and
  crossing direction per line.
- **Live progress** over WebSocket, with live provisional counts.
- **Pipeline-stage view**: six panels side by side, updated live while
  processing, showing what each step sees (frame → detection → tracking →
  classification → ROI → counting). The same view can be exported as a 3×2
  "pipeline" video.
- Results dashboard with exports: **CSV**, a zip of all CSV tables, **XLSX**
  (one sheet per table) and **JSON**.
- Optional **annotated video**: boxes, class, track ID, ROIs, lines, direction
  and running counts.
- **Results in tabs** (Overview, By vehicle type, Directions, Over time, Counted vehicles, Counting
  lines, Movements, Annotated video), with area and vehicle-type filters that apply to every tab.
- **Batches**: upload many videos at once (or import them from a folder), draw each one's roads (or
  copy them from another video), then run them all one after another, each with its own report.
- **Processing speed** presets (Accurate / Balanced / Fast / Fastest) for hours-long footage.

## Counting specific roads

If the camera shows several roads but you only want some of them:

1. Choose **Draw road (rectangle)** and drag a box over each road you want to
   count; the box shows in translucent red while you drag (at least 20 px). Use **Draw area (polygon)**
   for curved or angled roads and **Draw counting line** (click the start, then the end) for a gate.
   After each shape the editor returns to **Select / edit**: click a shape to select it, drag it or its
   corner points to adjust it, and press Delete to remove it.
2. A popup asks for a **name** for each one (e.g. "A40 inbound", "High
   Street"). Names must be unique per video.
3. Each road gets its own **colour**, used in the editor, the live view, the
   annotated video, the counts tiles and the counts drawer.
4. Once you draw a road, **Whole Frame** is switched off, so only your selected
   roads are counted. Tick it again to also get a total for the whole picture.
   Use the checkbox next to a road to leave it out of a run without deleting
   it.

**Choose what counts** with *Count a vehicle when it…*:

| Option | Counted | Not counted |
|---|---|---|
| **crosses the area** (default) | comes in from outside the box **and** leaves it again (see below) | stops, parks or queues inside; dips in and backs out the same side; never enters |
| **enters the area** | comes in from outside, even if it then stays | already inside; never enters |
| **is seen in the area** | is inside the box: passing through, or for at least *Min seconds in area* | never inside; parked (unless ticked) |

If a box touches the edge of the picture, the edge counts as "outside": a vehicle driving into or out of
view through the box is entering or leaving it. Whole Frame always uses *is seen*.

A tracked vehicle isn't always seen on both sides of an area: it can fade out in the distance inside an
outline that runs to the horizon, it can already be in the box when the analysed period starts, or at
night its track can start late. **Crossing** therefore also counts a vehicle whose path covers at least
**60 %** of the area along its direction of travel (60 % so one vehicle split into two tracks can't count
twice). A vehicle already inside when the period starts counts if it then completes its crossing, like
a manual survey count, so consecutive periods add up.

Each vehicle counts at most once per area, split by vehicle type and direction. The details:

- **Passing through counts, however fast.** A vehicle whose path goes from outside the box, into
  it and out again is counted, even if it was inside for a single frame or jumped across the box
  between two frames. A vehicle that never enters the box is not counted.
- **Hidden for a moment is still one vehicle.** If a vehicle disappears behind a sign, lamp post or
  another vehicle and comes back with a new tracker ID within 2 s, near where it was heading, it is
  re-linked to its earlier track and counted once.
- **Parked or static things are not traffic.** Tracks that never move (parked cars, a bollard
  misread as a car) are ignored unless **Count parked / stationary vehicles** is ticked.
- **Analyse part of a video.** Set **From / To (seconds)**, e.g. 0 to 20. Times in the results stay
  on the video's own clock. The same vehicle can appear in two roads (for
example, if it turns from one into the other), and it counts once in each.
While an analysis runs, the **Counts** tab on the right edge of the screen
opens a drawer with live per-road counts by vehicle type, and it shows the
final counts afterwards.

*(Optional, API only)* Areas also take a `role` of `in`, `out` or `both`. With
roles set, origin → destination **movements** (turning counts) are reported
too.

## Many videos: batches

1. **Upload**: drop or choose many videos at once on the **Videos** page. They upload one after another.
   For very large files, use the import folder instead (below).
2. **Draw**: open each video and draw its roads. **Next →** / **← Previous** step through the videos.
   Videos from the same camera position can reuse another video's roads with **Copy areas from another
   video…** (positions are stored relative to the picture, so they fit any resolution). A video with no
   roads drawn counts its **whole frame**.
3. **Run**: tick the videos (or **Select all**), click **▶ Run N selected**, choose the settings once
   and click **Run batch**. Videos are processed one by one in upload order.
4. **Results**: the batch page shows each video's status, time taken and counts per road and type,
   filtered by status (running, waiting, completed, failed). **Report** opens a video's full results.
   **All videos (XLSX/CSV)** downloads one table with a row per video and road. **Every report (ZIP)**
   holds that table plus each video's own Excel report. **Run failed / cancelled again** re-queues only
   those videos.

### Very long videos: the import folder

Uploading hours of footage through the browser is slow. Copy the files into the `videos` folder next to
`docker-compose.yml` instead (sub-folders are fine), then click **Import N new** on the Videos page. The
files are read in place (mounted read-only) and are not copied. Deleting such a video in the app leaves
the file alone.

## Processing speed

Almost all the time goes into the detector, once per analysed frame. Pick a preset per run or batch:

| Speed | Frames analysed | Other changes | Typical speed-up* |
|---|---|---|---|
| **Accurate** | every frame | none | 1× |
| **Balanced** (default) | ~15 per second of video | none | ~2× |
| **Fast** | ~10 per second | no tile scan, ≤ 960 px | ~2.5× (SD) to ~6× (HD with tile scan) |
| **Fastest** | ~6 per second | no tile scan, 640 px, time-lapse tracker | ~3× (SD) to ~10× (HD) |

\*Measured on CPU. Counts stay correct when frames are skipped. A vehicle that jumps right across an
area between two analysed frames still counts as passing through it. The trackers get the effective
frame rate and use **buffered-IoU matching** (Yang et al., 2023): boxes are enlarged for matching only,
in proportion to the frames skipped, so fast vehicles still overlap from one analysed frame to the next.
A track that is confirmed a few frames after a vehicle enters the picture is still recognised as coming
into view. Below ~8 analysed frames per second the time-lapse tracker (position + colour) takes over.
The ground-truth clips are tested at all four presets and give exact counts.

While running, the progress line shows the speed (e.g. `2.4× real time`) and the time left. To go
faster:

- **GPU**: with an NVIDIA card, start with
  `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build`. This needs the NVIDIA
  driver plus the NVIDIA Container Toolkit (Linux) or WSL 2 GPU support (Windows). It is typically 10–30×
  faster than CPU.
- **More workers**: `docker compose up -d --scale worker=2` processes two videos of a batch at once.
  Each worker uses all CPU cores, so more than two rarely helps without a GPU.

## Processing pipeline

```text
Video
  ↓  Frame extraction          app/pipeline/frames.py
  ↓  Vehicle detection         app/pipeline/detector.py      (YOLO | motion)
  ↓  Vehicle tracking          app/pipeline/tracker.py       (ByteTrack | BoT-SORT | IoU)
  ↓  Vehicle classification    app/pipeline/classifier.py    (size rules | crop classifier)
  ↓  ROI / whole-frame analysis app/analysis/analyzer.py
  ↓  Counting & direction      app/analysis/analyzer.py
  ↓  Results                   app/reporting/aggregate.py
  ↓  CSV / XLSX / JSON / video app/reporting/exporters.py, app/pipeline/annotate.py
```

Each stage only consumes the previous stage's output, so any stage can be
swapped out (a new detector, a GPU tracker, a different classifier) without
touching the others. The same vehicle across many frames is one **track**. A
track is counted once in each area it spends at least `min_seconds_in_zone`
in, and once on each line it crosses. One vehicle can therefore legitimately
appear in "Whole Frame", "Lane 1" and "Gate A", but never twice in the same
one.

## Architecture

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Tailwind CSS 4, HTML5 video, Konva (ROI editor), Vite |
| API | Python, FastAPI, WebSockets |
| Computer vision | OpenCV, Ultralytics YOLO, ByteTrack / BoT-SORT |
| Database | PostgreSQL (SQLite for local development and tests) |
| Processing | Background workers (embedded thread, or separate processes using `SKIP LOCKED` job claiming); CPU or GPU |

Jobs are rows in the `analyses` table. Workers claim queued jobs, write
progress and the latest stage snapshots, then store per-vehicle records
(`zone_counts`, `line_crossings`) and a summary. Each analysis keeps a snapshot
of its settings and ROIs, so editing ROIs later never changes past results.

## Quick start (Docker Desktop)

This runs everything on **your** computer. The containers appear in Docker Desktop.

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and start it. Wait until it
   says **Engine running**.
2. Open a terminal (Windows: PowerShell; macOS: Terminal) and run:

   ```bash
   git clone https://github.com/bronglil/mhtc-traffic-analyzer.git
   cd mhtc-traffic-analyzer
   git checkout feature/traffic-vision
   docker compose up --build -d
   ```

   The first build takes about 5–10 minutes (it downloads PyTorch and the YOLO weights). Later starts
   take seconds.
3. Open **http://localhost:8080**.

In Docker Desktop you'll see a project **mhtc-traffic-analyzer** with four containers: `db`
(PostgreSQL), `api`, `worker` (does the video processing) and `web` (the UI).

| Command (run in the project folder) | What it does |
|---|---|
| `docker compose up -d` | Start again later (no rebuild) |
| `git pull && docker compose up --build -d` | Update to the latest version |
| `docker compose logs -f worker` | Watch the analysis worker |
| `docker compose up -d --scale worker=2` | Process two videos of a batch at the same time |
| `docker compose down` | Stop (videos, results and the database are kept) |
| `docker compose down -v` | Stop and **delete** all data |

The default YOLO weights are baked into the image. Custom weights (e.g. an LGV1/LGV2 model) go in the
`data` volume under `/data/models/` and are selected in **Advanced settings**. Videos up to 4K work; the
detection resolution is chosen automatically from the video size.

## Examples

### 1. Count only some of the roads in view (dual carriageway)

`backend/tests/data/videos/dual_carriageway.mp4` shows three roads: the left carriageway (traffic
away from the camera), the right carriageway, and a slip road beyond the railing.

1. Upload the video.
2. **Draw road (rectangle)**: drag over the left carriageway, then name it *Left carriageway*.
3. **Draw area (polygon)**: click round the slip road, press Enter, then name it *Slip road*.
4. Leave the right carriageway undrawn. Click **Run analysis**.
5. Result: **Left carriageway 2 cars (N, away)**, **Slip road 1 car (SE, towards)**. The right
   carriageway and the traffic at the horizon are not counted.

### 2. A box near a sign, first 20 seconds only

1. Upload the video and drag a rectangle over the stretch of road next to the sign (name it, e.g.,
   *By blue sign*).
2. Under **Part of video to analyse**, set **From 0** and **To 20**.
3. Run. Every vehicle whose path goes **through** the box in those 20 seconds is counted once, however
   fast it was; vehicles that never enter it are not counted.

### 3. Junction: each arm counted separately

`backend/tests/data/videos/synthetic_junction.mp4` has four arms. Draw a rectangle over the North and
East arms only; the result is *North Road 2*, *East Road 3*, and the West/South arms are ignored.

### 4. Night, overhead and other footage

- **Night / low light:** keep **Detect small / distant vehicles** ticked (it's on automatically for
  HD/4K). It runs the detector on the full frame plus four overlapping tiles (sliced inference, *SAHI*,
  Akyon et al. 2022) and merges the results. On the Wikimedia *Traffic on bridge at night* clip it found
  **64% more vehicles** than the best full-frame setting, all real. **Low-light enhancement** (CLAHE
  contrast boost) is available for unlit roads, but it's off by default: on the street-lit bridge it
  didn't find more vehicles. A known limit of stock models at night is oncoming cars whose headlights
  glare straight into the camera; the reliable fix is fine-tuning on night footage (see
  [docs/vehicle-classification.md](docs/vehicle-classification.md)).
- **Overhead camera** (looking straight down): set **Camera view → Overhead**. Stock YOLO doesn't
  recognise cars from above; choose **Detector → Motion** for fixed cameras (exact on
  `overhead_road.mp4`) or train a model (see [docs/vehicle-classification.md](docs/vehicle-classification.md)).
- **Time-lapse / very low frame rate:** vehicles jump several car lengths between frames, so the normal
  trackers lose them. Set **Footage → Time-lapse**: it uses a tracker that matches vehicles by position
  and colour, and counts a vehicle seen in 2 frames inside the area. On the Wikimedia *City street time
  lapse* clip (4 s window, box over the junction) it counts 34–35 vehicles against a hand count of
  about 36; ByteTrack alone finds 4.
- **Formats:** MP4/MOV (H.264, H.265), WebM (VP8/VP9), Ogg (`.ogv`), MKV, AVI and more.

## Checking results yourself

Do this whenever you want to verify a count, e.g. with a new camera site:

1. **Run it in the UI** with your roads drawn, ticking **Generate annotated video**.
2. **Watch the annotated video** (download it from the results page). Every counted vehicle has a box
   with its ID, type and direction, and the running totals per road are shown top-left in each road's
   colour. Check that:
   - every vehicle that passes through a road gets a box and the road's total goes up once;
   - nothing that stays outside the road (or is parked) is added to it.
3. **Use the pipeline stages view** (on the results page, or choose **All pipeline stages (3×2)** for the
   video) to see why a vehicle was missed. Missing in *2. Detection* means the detector didn't see it (try
   a higher detection resolution or lower confidence). A new ID in *3. Tracking* means it was lost and
   found again. A wrong label in *4. Classification* is a classification problem. Outside the area in
   *5. ROI analysis* means the outline needs adjusting.
4. **Compare with a hand count**: open the **Counted vehicles** table (or the CSV export), which lists
   every vehicle with the time it entered and left each road, and step through the video to those times.

### From the command line (no UI)

```bash
# Inside Docker (put your videos in a "videos" folder next to docker-compose.yml):
docker compose run --rm -v "$PWD/videos:/videos" api python -m app.tools.analyze /videos/clip.mp4 --grid /videos/grid.jpg --at 5
```

`grid.jpg` is a frame with pixel coordinates, used to read off the corners of your boxes. Then:

```bash
docker compose run --rm -v "$PWD/videos:/videos" api python -m app.tools.analyze /videos/clip.mp4 \
    --road "By blue sign=820,400,1300,700" --from 0 --to 20 \
    --annotate /videos/clip_counted.mp4 --json /videos/clip_counts.json
```

This prints a table like:

```
Road / area        Total  By type                         Directions
Left carriageway       2  Car 2                           N 2
Right carriageway      0  -                               -
Slip road              1  Car 1                           SE 1
```

Options: `--count crossing|entering|present` (default `crossing`), `--speed accurate|balanced|fast|fastest`,
`--timelapse`, `--sliced`,
`--low-light off|auto|on`,
`--polygon "Name=x,y;x,y;..."` for angled roads, `--line "Name=x1,y1,x2,y2"` for counting
lines, `--camera overhead`, `--detector motion`, `--tracker iou`, `--imgsz 1280`, and
`--layout pipeline` (all six stages side by side in the annotated video). Run with `--help` for
everything. Without Docker, run the same command from the `backend` folder as
`python -m app.tools.analyze ...`.

### Make a check permanent

To keep a hand-counted clip as an automatic test, put `myclip.mp4` and `myclip.json` (copy
`backend/tests/data/videos/dual_carriageway.json`, then edit the roads and the expected counts) in
`backend/tests/data/videos/`. `pytest tests/test_real_videos.py` then checks it on every run.

## Local development

```bash
# Backend (Python 3.11+)
cd backend
pip install -r requirements-dev.txt
uvicorn app.main:app --reload          # http://localhost:8000/docs; uses SQLite + an embedded worker

# Frontend
cd frontend
npm install
npm run dev                            # http://localhost:5173 (proxies /api to :8000)
```

Configuration is via `TV_*` environment variables (see `backend/app/config.py`):
`TV_DATABASE_URL`, `TV_DATA_DIR`, `TV_MODEL_PATH`, `TV_CLASSIFIER_MODEL`,
`TV_DEVICE` (`cpu`, `cuda:0`, `mps`), `TV_EMBEDDED_WORKER`.

## Tests

```bash
# Backend
cd backend
pytest                      # everything, including the real-video tests (downloads yolo11n.pt once)
pytest -m "not model"       # skip the tests that need YOLO weights

# Frontend
cd frontend
npm run typecheck           # app + test code
npm test                    # unit tests (Vitest)
npm run test:e2e            # browser tests (Playwright) against a real API + fresh database
                            # first time: npx playwright install chromium
```

GitHub Actions (`.github/workflows/ci.yml`) runs all of these on every push.

Backend:

- `tests/test_analyzer.py`: counting rules (once per zone, re-entry, flicker,
  majority-vote type, lines, direction).
- `tests/test_classifier.py`: class aliases, perspective-normalised LGV1/LGV2
  size rules, crop-classifier voting.
- `tests/test_pipeline.py`: the end-to-end pipeline on a synthetic video with
  all three trackers, stage previews, pipeline video and exports.
- `tests/test_api.py`: upload → ROIs (colours, unique names) → analysis →
  WebSocket → exports.
- `tests/test_multi_road.py`: a 4-road junction
  (`tests/data/videos/synthetic_junction.mp4`, regenerate with
  `tests/data/make_synthetic_junction.py`). Counting only 2 of the 4 roads,
  each road separately by name and vehicle type, and in/out movements.
- `tests/test_real_videos.py`: **real footage with hand-counted ground truth**
  (`tests/data/videos/`):
  - `overhead_road.mp4` (MIT): 5 cars over two lanes and a gate. The motion
    detector matches the ground truth exactly with every tracker. COCO YOLO is
    recorded as a known limitation for overhead views.
  - `oblique_car_park.mp4` (CC BY 4.0): 2 cars and 2 cyclists among
    pedestrians. YOLO11n + ByteTrack matches the counts, types and directions
    exactly.
  - `dual_carriageway.mp4` (MHTC-supplied): a pole-mounted camera over a dual carriageway with a
    slip road. Left carriageway 2 cars (away), slip road 1 car (towards), right carriageway 0. YOLO
    matches exactly with both trackers at strides 1 and 2. The browser test
    `frontend/e2e/real-video.spec.ts` checks the same result through the UI.

  Add your own survey clips (e.g. with LGV1/LGV2 ground truth) by dropping a
  video and a JSON file into that folder. See
  [docs/vehicle-classification.md](docs/vehicle-classification.md#proving-accuracy-ground-truth-clips).

Frontend:

- `src/lib/__tests__/counts.test.ts`: the per-road counts behind the tiles
  and drawer (live vs final, Whole Frame on/off), and the area colour palette
  kept in sync with the backend.
- `e2e/multi-road.spec.ts`: the full user journey in a real browser. It
  uploads the 4-road junction, drags rectangles over 2 roads, names them in
  the popup (duplicate names refused), runs the analysis, and checks the live
  view, the results table (North Road 2, East Road 3, no other roads), the
  counts drawer, the area colours, and the CSV/JSON/XLSX exports. It also
  covers polygon drawing with fast clicks and keyboard safety while the popup
  is open.

## API overview

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/videos` | Upload a video (multipart) |
| `GET` | `/api/videos`, `/api/videos/{id}` | List, or get a video with its regions |
| `GET` | `/api/videos/{id}/file`, `/frame?t=` | Stream the video; one decoded frame |
| `POST/PATCH/DELETE` | `/api/videos/{id}/regions[/{rid}]` | Create, rename, edit or delete ROIs and lines |
| `POST` | `/api/videos/{id}/analyses` | Start an analysis (vehicle types, detector, tracker, classification…) |
| `GET` | `/api/analyses/{id}` | Status and summary |
| `WS` | `/api/analyses/{id}/ws` | Live progress and counts |
| `GET` | `/api/analyses/{id}/stages` | Latest pipeline-stage images |
| `GET` | `/api/analyses/{id}/export?format=csv\|csv_bundle\|xlsx\|json` | Download results |
| `GET` | `/api/analyses/{id}/annotated-video` | Annotated or pipeline video |
| `POST` | `/api/analyses/{id}/cancel` | Cancel |
| `POST` | `/api/videos/{id}/regions/copy` | Copy another video's areas and lines |
| `GET/POST` | `/api/videos/import` | List / register files in the import folder (`TV_IMPORT_DIR`) |
| `POST` | `/api/batches` | Queue many videos with one set of settings (each keeps its own areas) |
| `GET` | `/api/batches`, `/api/batches/{id}` | Batch list; per-video status and counts |
| `POST` | `/api/batches/{id}/cancel`, `/retry` | Cancel remaining; re-queue failed / cancelled |
| `GET` | `/api/batches/{id}/export?format=xlsx\|csv\|zip` | One table for all videos; zip adds each video's report |

Interactive docs are at `/docs` when the API is running.

## Roadmap

The architecture is designed to extend to speed estimation (homography
calibration on the existing tracks), multiple cameras, OGV1/OGV2 and other
classification schemes, cloud or GPU worker pools, and scheduled automated
reporting.
