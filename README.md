# MHTC-traffic-analyzer

# Traffic Vision

**Traffic Vision** is a video-based vehicle detection, tracking, counting, and traffic-analysis platform.

The system allows users to upload traffic videos, configure analysis areas, select vehicle types, detect and track vehicles, count unique vehicles, analyze movement direction, and export structured traffic results.

## Core Features

* Upload and analyze traffic videos.
* Automatically use the **entire video frame** when no custom area is selected.
* Draw and configure multiple polygon-based ROIs.
* Give each ROI a custom name.
* Analyze **Whole Frame + multiple custom areas simultaneously**.
* Select vehicle types using checkboxes:

  * Car
  * Van
  * Truck
  * Bus
  * Motorcycle
  * Bicycle
* Detect vehicles using YOLO.
* Track vehicles using ByteTrack or BoT-SORT.
* Prevent duplicate vehicle counting using persistent tracking IDs.
* Support optional counting lines/gates.
* Detect vehicle movement direction.
* Generate results by:

  * Area
  * Vehicle type
  * Direction
  * Time period
* Display processing progress and analysis results.
* Export results as:

  * CSV
  * XLSX
  * JSON
* Optionally generate annotated videos containing:

  * Bounding boxes
  * Vehicle class
  * Tracking IDs
  * ROI boundaries
  * Counting lines
  * Direction
  * Current counts

## Processing Pipeline

```text
Video
  ↓
Frame Extraction
  ↓
Vehicle Detection
  ↓
Vehicle Tracking
  ↓
ROI / Whole-Frame Analysis
  ↓
Counting & Direction Detection
  ↓
Results
  ↓
CSV / XLSX / JSON / Annotated Video
```

## Technology Stack

### Frontend

* React
* TypeScript
* Tailwind CSS
* HTML5 Video
* Canvas/Konva.js or Fabric.js

### Backend

* Python
* FastAPI
* OpenCV

### Computer Vision

* YOLO
* ByteTrack / BoT-SORT

### Database

* PostgreSQL

### Processing

* Background workers
* CPU/GPU support
* WebSocket-based progress updates

## Key Design Principle

The system separates:

**Detection → Tracking → ROI Analysis → Counting → Reporting**

This ensures that the same vehicle appearing across many video frames is treated as **one vehicle**, while the same vehicle can legitimately be counted separately when it participates in different configured areas or counting events.

## MVP

The first version should support:

1. Video upload.
2. Video playback.
3. Whole-frame analysis.
4. Multiple polygon ROIs.
5. ROI naming and editing.
6. Vehicle-type selection.
7. YOLO detection.
8. Vehicle tracking.
9. Unique vehicle counting.
10. Basi
