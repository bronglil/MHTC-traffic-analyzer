import type { Dispatch, ReactNode, SetStateAction } from "react";
import { formatDuration, type AnalysisSettings, type Meta, type Speed } from "../lib/api";
import { VEHICLE_HINTS, VEHICLE_LABELS, VEHICLE_TYPES } from "../lib/vehicles";

export const DEFAULT_SETTINGS: AnalysisSettings = {
  vehicle_types: [...VEHICLE_TYPES],
  include_whole_frame: true,
  detector: "yolo",
  tracker: "bytetrack",
  classification: "size",
  confidence: 0.3,
  frame_stride: 1,
  min_seconds_in_zone: 0.3,
  anchor: "bottom_center",
  time_bin_seconds: 60,
  generate_annotated_video: false,
  annotated_video_layout: "overlay",
  count_stationary: false,
  count_rule: "crossing",
  sliced_detection: false,
  low_light: "off",
  footage: "normal",
  start_seconds: 0,
  end_seconds: null,
  image_size: 640,
  speed: "balanced",
};

/** Processing speed presets (backend: app/pipeline/speed.py). Speed-ups are typical, measured on CPU. */
export const SPEED_OPTIONS: { value: Speed; label: string; hint: string }[] = [
  { value: "accurate", label: "Accurate", hint: "every frame · slowest" },
  { value: "balanced", label: "Balanced", hint: "~15 frames per second of video · about 2× faster" },
  { value: "fast", label: "Fast", hint: "~10 frames/s, no tile scan · about 3–5× faster" },
  { value: "fastest", label: "Fastest", hint: "~6 frames/s at 640 px · about 5–10× faster" },
];

export const SPEED_LABELS: Record<Speed, string> = Object.fromEntries(SPEED_OPTIONS.map((o) => [o.value, o.label])) as Record<Speed, string>;

/** A time period that gives a readable number of bars for the video length. */
export function defaultTimeBin(duration: number): number {
  if (duration <= 120) return 10;
  if (duration <= 900) return 60;
  if (duration <= 3 * 3600) return 900;
  return 3600;
}

/**
 * Analysis settings shared by a single video and a batch of videos. Without a `video`
 * (batch) resolution and tile scanning default to "auto" per video.
 */
export default function SettingsForm({ settings, setSettings, meta, video }: {
  settings: AnalysisSettings;
  setSettings: Dispatch<SetStateAction<AnalysisSettings>>;
  meta: Meta | null;
  video?: { duration_seconds: number };
}) {
  const set = <K extends keyof AnalysisSettings>(k: K, v: AnalysisSettings[K]) => setSettings((s) => ({ ...s, [k]: v }));
  return (
    <div className="space-y-3">
      <fieldset>
        <legend className="label">Processing speed</legend>
        <div className="mt-1 grid grid-cols-2 gap-1.5" role="radiogroup" aria-label="Processing speed">
          {SPEED_OPTIONS.map((o) => (
            <label key={o.value} title={o.hint}
              className={`cursor-pointer rounded-lg border px-2 py-1.5 text-sm ${settings.speed === o.value ? "border-accent bg-surface" : "border-line"}`}>
              <input type="radio" name="speed" className="sr-only" checked={settings.speed === o.value}
                onChange={() => set("speed", o.value)} />
              <span className="font-medium">{o.label}</span>
              <span className="block text-[11px] leading-tight text-ink-3">{o.hint}</span>
            </label>
          ))}
        </div>
        {settings.footage === "timelapse" && settings.speed !== "accurate" && (
          <p className="mt-1 text-xs text-ink-3">Time-lapse footage is never skipped: every frame is analysed.</p>
        )}
      </fieldset>

      <h2 className="font-semibold">Vehicle types</h2>
      <div className="grid grid-cols-2 gap-1.5">
        {VEHICLE_TYPES.map((t) => (
          <label key={t} className="flex items-center gap-2 text-sm" title={VEHICLE_HINTS[t]}>
            <input
              type="checkbox"
              checked={settings.vehicle_types.includes(t)}
              onChange={(e) =>
                set("vehicle_types", e.target.checked
                  ? VEHICLE_TYPES.filter((x) => x === t || settings.vehicle_types.includes(x))
                  : settings.vehicle_types.filter((x) => x !== t))
              }
            />
            {VEHICLE_LABELS[t]}
          </label>
        ))}
      </div>
      <p className="text-xs text-ink-3">
        LGV1 = small car-derived vans · LGV2 = large vans up to 3.5 t. Standard detectors can’t see vans, so LGVs are
        estimated from vehicle size unless a custom LGV model is configured.
      </p>

      <fieldset>
        <legend className="label">Count a vehicle when it…</legend>
        <div className="mt-1 space-y-1.5 text-sm">
          {([
            ["crossing", "crosses the area", "comes in from outside and leaves again"],
            ["entering", "enters the area", "comes in from outside, even if it stays"],
            ["present", "is seen in the area", "anywhere inside it"],
          ] as const).map(([value, label, hint]) => (
            <label key={value} className="flex items-start gap-2">
              <input type="radio" name="count_rule" className="mt-1" checked={settings.count_rule === value}
                onChange={() => set("count_rule", value)} />
              <span>{label} <span className="block text-xs text-ink-3">{hint}</span></span>
            </label>
          ))}
        </div>
      </fieldset>

      <div>
        <span className="label">Part of {video ? "video" : "each video"} to analyse (seconds)</span>
        <div className="mt-1 flex items-center gap-2 text-sm">
          <input type="number" min={0} step={0.5} className="input w-24" aria-label="From (seconds)"
            value={settings.start_seconds ?? 0}
            onChange={(e) => set("start_seconds", Math.max(0, Number(e.target.value) || 0))} />
          <span className="text-ink-3">to</span>
          <input type="number" min={0} step={0.5} className="input w-24" aria-label="To (seconds)"
            placeholder={video ? video.duration_seconds.toFixed(1) : "end"}
            value={settings.end_seconds ?? ""}
            onChange={(e) => set("end_seconds", e.target.value === "" ? null : Math.max(0, Number(e.target.value)))} />
          {video && <span className="text-xs text-ink-3">of {formatDuration(video.duration_seconds)}</span>}
        </div>
        {settings.end_seconds != null && settings.end_seconds <= (settings.start_seconds ?? 0) && (
          <p className="mt-1 text-xs text-red-600">“To” must be after “From”.</p>
        )}
      </div>

      <Field label="Footage">
        <select className="input" value={settings.footage}
          onChange={(e) => set("footage", e.target.value as AnalysisSettings["footage"])}>
          <option value="normal">Normal speed</option>
          <option value="timelapse">Time-lapse / very low frame rate</option>
        </select>
      </Field>
      <Field label="Camera view">
        <select className="input" value={settings.anchor} onChange={(e) => set("anchor", e.target.value as AnalysisSettings["anchor"])}>
          <option value="bottom_center">Roadside / pole-mounted (oblique)</option>
          <option value="center">Overhead (looking straight down)</option>
        </select>
      </Field>

      <details className="group">
        <summary className="cursor-pointer text-sm font-medium text-ink-2">Advanced settings</summary>
        <div className="mt-3 space-y-3">
          <Field label="Detector">
            <select className="input" value={settings.detector} onChange={(e) => {
              const detector = e.target.value as AnalysisSettings["detector"];
              // Motion blobs carry no class, so size rules would only invent LGV/HGV splits.
              setSettings((s) => ({ ...s, detector, classification: detector === "motion" && s.classification === "size" ? "detector" : s.classification }));
            }}>
              <option value="yolo">YOLO neural network (classifies vehicles)</option>
              <option value="motion">Motion / background subtraction (fixed camera, counts only)</option>
            </select>
          </Field>
          <Field label="Vehicle classification">
            <select className="input" value={settings.classification}
              onChange={(e) => set("classification", e.target.value as AnalysisSettings["classification"])}>
              <option value="size">Detector + size rules (splits LGV1 / LGV2)</option>
              <option value="detector">Detector classes only</option>
              <option value="classifier">Custom classification model</option>
            </select>
          </Field>
          {settings.classification === "classifier" && (
            <Field label="Classifier model">
              <input className="input" placeholder="e.g. mhtc-vehicle-cls.pt" value={settings.classifier_model ?? ""}
                onChange={(e) => set("classifier_model", e.target.value || null)} />
            </Field>
          )}
          <Field label="Detect small / distant vehicles (tile scan)">
            <select className="input" value={settings.sliced_detection == null ? "auto" : settings.sliced_detection ? "on" : "off"}
              onChange={(e) => set("sliced_detection", e.target.value === "auto" ? null : e.target.value === "on")}>
              <option value="auto">Auto: on for HD / 4K video</option>
              <option value="on">On: also scan 4 overlapping tiles (~2.5× slower)</option>
              <option value="off">Off</option>
            </select>
          </Field>
          {settings.speed === "fast" || settings.speed === "fastest" ? (
            <p className="-mt-2 text-xs text-ink-3">The {settings.speed} speed turns tile scanning off.</p>
          ) : null}
          <Field label="Low-light enhancement">
            <select className="input" value={settings.low_light}
              onChange={(e) => set("low_light", e.target.value as AnalysisSettings["low_light"])}>
              <option value="off">Off (recommended for lit roads)</option>
              <option value="auto">Auto: boost contrast when frames are dark</option>
              <option value="on">Always on</option>
            </select>
          </Field>
          <Field label="Detection resolution">
            <select className="input" value={settings.image_size ?? "auto"}
              onChange={(e) => set("image_size", e.target.value === "auto" ? null : Number(e.target.value) as 640 | 960 | 1280 | 1920)}>
              <option value="auto">Auto: from the video size</option>
              <option value={640}>640 px — fastest (SD / near vehicles)</option>
              <option value={960}>960 px — HD video</option>
              <option value={1280}>1280 px — 4K / distant vehicles</option>
              <option value={1920}>1920 px — 4K, small vehicles (slow)</option>
            </select>
          </Field>
          <Field label="Tracker">
            <select className="input" value={settings.tracker} onChange={(e) => set("tracker", e.target.value)}>
              {(meta?.trackers ?? ["bytetrack", "botsort", "iou"]).map((t) => (
                <option key={t} value={t}>{{ bytetrack: "ByteTrack", botsort: "BoT-SORT", iou: "Simple IoU", timelapse: "Time-lapse (position + colour)" }[t] ?? t}</option>
              ))}
            </select>
          </Field>
          <Field label={`Detection confidence: ${settings.confidence.toFixed(2)}`}>
            <input type="range" min={0.05} max={0.9} step={0.05} value={settings.confidence} className="w-full"
              onChange={(e) => set("confidence", Number(e.target.value))} />
          </Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Frame stride (minimum)">
              <input type="number" min={1} max={30} className="input" value={settings.frame_stride}
                onChange={(e) => set("frame_stride", Math.max(1, Number(e.target.value) || 1))} />
            </Field>
            <Field label="Min seconds in area">
              <input type="number" min={0} max={60} step={0.1} className="input" value={settings.min_seconds_in_zone}
                onChange={(e) => set("min_seconds_in_zone", Math.max(0, Number(e.target.value) || 0))} />
            </Field>
          </div>
          <Field label="Time period">
            <select className="input" value={settings.time_bin_seconds}
              onChange={(e) => set("time_bin_seconds", Number(e.target.value))}>
              {[[10, "10 seconds"], [30, "30 seconds"], [60, "1 minute"], [300, "5 minutes"], [900, "15 minutes"], [3600, "1 hour"]].map(
                ([v, l]) => <option key={v} value={v}>{l}</option>,
              )}
            </select>
          </Field>
          <Field label="Detector model (optional)">
            <input className="input" placeholder={meta?.default_model ?? "yolo11n.pt"} value={settings.model_path ?? ""}
              onChange={(e) => set("model_path", e.target.value || null)} />
          </Field>
        </div>
      </details>

      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-1" checked={!!settings.count_stationary}
          onChange={(e) => set("count_stationary", e.target.checked)} />
        <span>
          Count parked / stationary vehicles
          <span className="block text-xs text-ink-3">Off: only vehicles that move through a road are counted</span>
        </span>
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={settings.generate_annotated_video}
          onChange={(e) => set("generate_annotated_video", e.target.checked)} />
        Generate annotated video
      </label>
      {settings.generate_annotated_video && (
        <div className="ml-6 flex gap-4 text-sm">
          {([["overlay", "Single view"], ["pipeline", "All pipeline stages (3×2)"]] as const).map(([v, l]) => (
            <label key={v} className="flex items-center gap-1.5">
              <input type="radio" name="layout" checked={settings.annotated_video_layout === v}
                onChange={() => set("annotated_video_layout", v)} />
              {l}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

export function settingsInvalid(s: AnalysisSettings): string | null {
  if (s.vehicle_types.length === 0) return "Select at least one vehicle type.";
  if (s.end_seconds != null && s.end_seconds <= (s.start_seconds ?? 0)) return "“To” must be after “From”.";
  return null;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="label">{label}</span>
      {children}
    </label>
  );
}
