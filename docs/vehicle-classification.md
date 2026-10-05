# Identifying vehicle types (including LGV1 / LGV2)

Traffic Vision separates **finding** a vehicle from **deciding what it is**:

```
Frame → Detection → Tracking → Classification → ROI analysis → Counting
          (where?)   (same one?)  (what type?)
```

Classification runs **per track**: evidence from every frame of a vehicle is
combined (a majority vote weighted by confidence, plus per-track medians of the
classifier stage). A single bad frame therefore can't flip a van into a car.
Every record for a vehicle (each area and each counting line) shares one final
type.

## Vehicle classes

| Key | Label | Typical examples |
|---|---|---|
| `car` | Car | cars, taxis, SUVs, car-based pick-ups |
| `lgv1` | LGV1 – small van | car-derived vans: Ford Transit Connect / Courier, VW Caddy, Citroën Berlingo, Vauxhall Combo |
| `lgv2` | LGV2 – large van (≤ 3.5 t) | Ford Transit, Mercedes Sprinter, VW Crafter, Renault Master, Luton / dropside vans |
| `truck` | Truck / HGV (> 3.5 t) | rigid and articulated goods vehicles (OGV1 / OGV2) |
| `bus` | Bus / Coach | buses, coaches, minibuses |
| `motorcycle` | Motorcycle | motorcycles, scooters |
| `bicycle` | Bicycle | pedal cycles |

If your survey specification defines LGV1/LGV2 differently (for example by
gross weight or wheelbase), only the training labels change. The software
doesn't hard-code a definition. Splitting `truck` into OGV1/OGV2 works the same
way: add the classes to `app/vehicles.py` and the training data.

## Why stock models can't do this

Off-the-shelf YOLO weights are trained on COCO, which has only `car`, `truck`,
`bus`, `motorcycle` and `bicycle`. It has **no van class at all**: small vans
come out as `car` and large vans as `car` or `truck`. COCO is also made of
street-level photos, so it fails on overhead cameras. On
`backend/tests/data/videos/overhead_road.mp4`, every COCO model from nano to
x-large labelled the cars "airplane", "tv" or "suitcase". The aerial DOTA
(OBB) models didn't recognise them either. The test suite keeps this as a
documented `xfail`.

## Options, best first

### 1. Custom detector trained on your footage (recommended)

Train YOLO directly on boxes labelled `car / lgv1 / lgv2 / truck / bus /
motorcycle / bicycle` from your own camera positions. The detector then emits
the final classes and no refinement is needed (choose **Vehicle
classification → Detector classes only**). This gives the best results,
because the model learns your camera heights, angles, lighting and UK vehicle
fleet.

1. Pick footage from every typical site and camera angle, including day, night,
   rain, low sun and congestion.
2. Label boxes with CVAT, Label Studio or Roboflow, exported in YOLO format.
   As a rough guide, aim for **at least 300–500 instances per class** to start
   and 1,500+ for production. Pay particular attention to LGV1 vs car, which
   look very similar.
3. Train, starting from COCO weights:
   ```bash
   yolo detect train data=mhtc-vehicles.yaml model=yolo11s.pt imgsz=960 epochs=100
   ```
4. Copy `runs/detect/train/weights/best.pt` to the server's models directory
   (`$TV_DATA_DIR/models/`) and enter its file name under **Detector model**.
   Alternatively, set `TV_MODEL_PATH` to make it the default.

### 2. Stock detector + custom crop classifier

Keep a general detector for *finding* vehicles and add a small classification
model that looks at each vehicle's crop. Labelling crops (sorting images into
folders) is much faster than drawing boxes.

```bash
# 1. Export the best crops of every tracked vehicle from your videos
cd backend
python -m app.tools.export_crops survey_site1.mp4 survey_site2.mp4 --out dataset

# 2. Sort dataset/_unsorted/<suggested>/*.jpg into dataset/train/<class>/ and
#    dataset/val/<class>/ (about 80/20), fixing wrong suggestions as you go.

# 3. Train
yolo classify train data=dataset model=yolo11s-cls.pt imgsz=224 epochs=50
```

Copy `best.pt` into the models directory, then choose **Vehicle
classification → Custom classification model** and enter its file name, or set
`TV_CLASSIFIER_MODEL`. The classifier only re-labels car/van/truck tracks. It
samples up to 15 crops per vehicle and sums the probabilities across them.

### 3. Size rules, no extra model (default)

`SizeHeuristicRefiner` learns, from confidently detected cars, how big a car
appears at each image row (perspective). It then compares every car, van and
truck track with that:

| Detector says | Size vs a car at that position | Result |
|---|---|---|
| van | ≤ 1.25× | LGV1 |
| van | > 1.25× | LGV2 |
| truck | ≤ 1.6× | LGV2 (large vans are often called "truck") |
| truck | > 1.6× | Truck / HGV |
| car | 1.4–1.6× | LGV2 |
| car | otherwise | Car |

This is an **approximation**. It catches large vans that COCO mislabels, but it
can't tell a car-derived LGV1 from a car of the same size. LGV1 counts need
option 1 or 2. You can tune the thresholds per site (they're the constructor
arguments of `SizeHeuristicRefiner`).

### Fixed overhead cameras: the motion detector

For fixed overhead cameras without a suitable model, **Detector → Motion**
uses background subtraction to find moving vehicles from any angle. It counts
and gives directions accurately (exact on the overhead test clip), but it
doesn't classify, so every vehicle is reported as `car` unless a crop
classifier is configured. Set **Camera view → Overhead** so the box centre is
used as the ground point.

## Night footage

Detectors trained mostly on daylight photos see a night frame as a few bright headlights and street
lamps. In our tests, in order of effect:

1. **Sliced detection** (*Detect small / distant vehicles*) gives the biggest gain, because night vehicles
   are mostly small and distant: +64% vehicles found on the night bridge clip.
2. **Higher detection resolution** (1280 px) helps for the same reason.
3. **CLAHE low-light enhancement** helps on dark, unlit roads, but was neutral on a street-lit bridge. It's
   available as an option and off by default.
4. **Fine-tuning on night images** is what fixes oncoming cars blinded by their own headlights. Add night
   clips from your sites (and, e.g., the night split of the BDD100K driving dataset) to the training
   data described above.

## Proving accuracy: ground-truth clips

`backend/tests/data/videos/` holds short clips with **hand-counted** ground
truth. `tests/test_real_videos.py` runs every listed configuration on every
clip and fails if counts per area, line, direction or type drift from the
truth. To validate a new model, or LGV1/LGV2 accuracy on your own sites:

1. Add a 30–120 s clip, e.g. `site_a.mp4`, with a mix of cars, LGV1, LGV2 and
   HGVs.
2. Add `site_a.json` (copy `overhead_road.json`) listing each vehicle you
   counted, the regions, the expected totals and types, and the configuration
   to test (e.g. `"model": "mhtc-vehicles.pt"`, `"type_tolerance": 1`).
3. Run `pytest tests/test_real_videos.py`.

The pipeline-stage view (in the UI while an analysis runs, or the "All pipeline
stages" annotated video) shows where an error comes from. A missing box is a
**detection** problem. Two IDs for one vehicle is **tracking**. A wrong label
that the detection panel got right is **classification**. A vehicle counted
in the wrong lane is an **ROI** or anchor-point problem.
