import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import RegionEditor, { type EditorMode } from "../components/RegionEditor";
import VideoCanvas from "../components/VideoCanvas";
import StatusBadge from "../components/StatusBadge";
import {
  api,
  formatDuration,
  type Analysis,
  type AnalysisSettings,
  type Meta,
  type Point,
  type Region,
  type RegionKind,
  type VideoDetail,
} from "../lib/api";
import CountsDrawer from "../components/CountsDrawer";
import NameRegionDialog, { type RegionDetails } from "../components/NameRegionDialog";
import { REGION_COLORS, VEHICLE_HINTS, VEHICLE_LABELS, VEHICLE_TYPES, regionColor } from "../lib/vehicles";

const DEFAULT_SETTINGS: AnalysisSettings = {
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
  footage: "normal",
  start_seconds: 0,
  end_seconds: null,
  image_size: 640,
};

/** A time period that gives a readable number of bars for the video length. */
function defaultTimeBin(duration: number): number {
  if (duration <= 120) return 10;
  if (duration <= 900) return 60;
  if (duration <= 3 * 3600) return 900;
  return 3600;
}

export default function WorkspacePage() {
  const { videoId = "" } = useParams();
  const navigate = useNavigate();
  const [video, setVideo] = useState<VideoDetail | null>(null);
  const [regions, setRegions] = useState<Region[]>([]);
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [mode, setMode] = useState<EditorMode>("select");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [settings, setSettings] = useState<AnalysisSettings>(DEFAULT_SETTINGS);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const fail = (e: unknown) => setError((e as Error).message);

  const loadAnalyses = useCallback(() => {
    api.listAnalyses(videoId).then(setAnalyses).catch(fail);
  }, [videoId]);

  useEffect(() => {
    api.getVideo(videoId).then((v) => {
      setVideo(v);
      setRegions(v.regions);
      setSettings((s) => ({
        ...s,
        time_bin_seconds: defaultTimeBin(v.duration_seconds),
        // Small/distant vehicles vanish when a 4K frame is shrunk to 640 px.
        image_size: v.width >= 3000 ? 1280 : v.width >= 1800 ? 960 : 640,
      }));
    }).catch(fail);
    api.meta().then(setMeta).catch(() => undefined);
    loadAnalyses();
  }, [videoId, loadAnalyses]);

  // The counts drawer shows the most recent analysis of this video (full details incl. summary).
  const [latest, setLatest] = useState<Analysis | null>(null);
  const latestKey = analyses[0] ? `${analyses[0].id}:${analyses[0].status}:${analyses[0].progress}` : "";
  useEffect(() => {
    if (!analyses[0]) return setLatest(null);
    api.getAnalysis(analyses[0].id).then(setLatest).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latestKey]);

  // Keep the analyses list fresh while any job is active.
  useEffect(() => {
    if (!analyses.some((a) => a.status === "queued" || a.status === "running")) return;
    const t = setInterval(loadAnalyses, 2000);
    return () => clearInterval(t);
  }, [analyses, loadAnalyses]);

  // A shape that has been drawn and is waiting for its name (popup open).
  const [pending, setPending] = useState<{ kind: RegionKind; points: Point[] } | null>(null);
  const nextColor = REGION_COLORS.find((c) => !regions.some((r) => r.color?.toLowerCase() === c)) ??
    REGION_COLORS[regions.length % REGION_COLORS.length];

  const saveRegion = async (details: RegionDetails) => {
    if (!pending) return;
    const { kind, points } = pending;
    setPending(null);
    const firstArea = kind === "polygon" && !regions.some((r) => r.kind === "polygon");
    try {
      const r = await api.createRegion(videoId, { kind, points, color: nextColor, ...details });
      setRegions((rs) => [...rs, r]);
      setSelectedId(r.id);
      // Once you pick specific roads, count only those (Whole Frame can be re-ticked).
      if (firstArea) setSettings((s) => ({ ...s, include_whole_frame: false }));
    } catch (e) {
      fail(e);
    }
  };

  const patchRegion = async (id: string, patch: Partial<Region>) => {
    setRegions((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)));
    try {
      const updated = await api.updateRegion(videoId, id, patch);
      setRegions((rs) => rs.map((r) => (r.id === id ? updated : r)));
    } catch (e) {
      fail(e);
      api.getVideo(videoId).then((v) => setRegions(v.regions));
    }
  };

  const deleteRegion = async (id: string) => {
    try {
      await api.deleteRegion(videoId, id);
      setRegions((rs) => rs.filter((r) => r.id !== id));
      if (selectedId === id) setSelectedId(null);
    } catch (e) {
      fail(e);
    }
  };

  // Delete key removes the selected region.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest("input, textarea, select, [role=dialog]") || pending) return;
      if ((e.key === "Delete" || e.key === "Backspace") && selectedId && mode === "select") deleteRegion(selectedId);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const run = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const a = await api.createAnalysis(videoId, {
        ...settings,
        region_ids: regions.filter((r) => !excluded.has(r.id)).map((r) => r.id),
      });
      navigate(`/analyses/${a.id}`);
    } catch (e) {
      fail(e);
    } finally {
      setSubmitting(false);
    }
  };

  if (!video) return <p className="text-sm text-ink-3">{error ?? "Loading…"}</p>;

  const polygons = regions.filter((r) => r.kind === "polygon" && !excluded.has(r.id));
  const wholeFrameForced = polygons.length === 0;
  const set = <K extends keyof AnalysisSettings>(k: K, v: AnalysisSettings[K]) => setSettings((s) => ({ ...s, [k]: v }));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <Link to="/" className="text-sm text-ink-3 hover:underline">← Videos</Link>
          <h1 className="text-lg font-semibold">{video.original_name}</h1>
          <p className="text-xs text-ink-3">
            {video.width}×{video.height} · {video.fps.toFixed(2)} fps · {video.frame_count} frames ·{" "}
            {formatDuration(video.duration_seconds)}
          </p>
        </div>
      </div>

      {error && (
        <div className="flex items-start justify-between rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="ml-4">✕</button>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <ModeButton active={mode === "rect"} onClick={() => { setMode("rect"); setSelectedId(null); }}>
              ▭ Draw road (rectangle)
            </ModeButton>
            <ModeButton active={mode === "select"} onClick={() => setMode("select")}>Select / edit</ModeButton>
            <ModeButton active={mode === "polygon"} onClick={() => { setMode("polygon"); setSelectedId(null); }}>
              ⬠ Draw area (polygon)
            </ModeButton>
            <ModeButton active={mode === "line"} onClick={() => { setMode("line"); setSelectedId(null); }}>
              ╱ Draw counting line
            </ModeButton>
            <span className="text-xs text-ink-3">
              {mode === "rect" && "Press and drag over a road you want to count, then name it"}
              {mode === "polygon" && "Click to add points · click first point, double-click or Enter to finish · Esc to cancel"}
              {mode === "line" && "Click the start point, then the end point · Esc to cancel"}
              {mode === "select" && "Click a shape to select · drag it or its points to edit · Delete to remove"}
            </span>
          </div>
          <VideoCanvas
            src={api.videoUrl(video.id)}
            aspect={video.width / Math.max(1, video.height)}
            frameUrl={(t) => api.frameUrl(video.id, t)}
            knownDuration={video.duration_seconds}
            fps={video.fps || 25}
            overlay={({ width, height }) => (
              <RegionEditor
                width={width}
                height={height}
                regions={regions}
                mode={mode}
                selectedId={selectedId}
                onSelect={setSelectedId}
                onCreate={(kind, points) => {
                  setPending({ kind, points });
                  setMode("select");
                }}
                onChangePoints={(id, points) => patchRegion(id, { points })}
                onCancelDraw={() => setMode("select")}
              />
            )}
          />
        </div>

        <aside className="space-y-4">
          <section className="card p-4">
            <h2 className="mb-2 font-semibold">Areas &amp; lines</h2>
            <label className={`mb-2 flex items-center gap-2 rounded-lg border border-line px-2.5 py-2 text-sm ${wholeFrameForced ? "opacity-80" : ""}`}>
              <input
                type="checkbox"
                checked={settings.include_whole_frame || wholeFrameForced}
                disabled={wholeFrameForced}
                onChange={(e) => set("include_whole_frame", e.target.checked)}
              />
              <span className="font-medium">Whole Frame</span>
              {wholeFrameForced && <span className="ml-auto text-xs text-ink-3">used when no area is drawn</span>}
            </label>
            {regions.length === 0 && (
              <p className="text-xs text-ink-3">Draw areas (polygons) or counting lines on the video to analyse them separately.</p>
            )}
            <ul className="space-y-2">
              {regions.map((r, i) => (
                <RegionRow
                  key={r.id}
                  region={r}
                  color={r.color || regionColor(i)}
                  selected={r.id === selectedId}
                  included={!excluded.has(r.id)}
                  onToggleIncluded={(inc) =>
                    setExcluded((s) => {
                      const n = new Set(s);
                      if (inc) n.delete(r.id);
                      else n.add(r.id);
                      return n;
                    })
                  }
                  onSelect={() => { setMode("select"); setSelectedId(r.id); }}
                  onPatch={(p) => patchRegion(r.id, p)}
                  onDelete={() => deleteRegion(r.id)}
                />
              ))}
            </ul>
          </section>

          <section className="card space-y-3 p-4">
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
              <span className="label">Part of video to analyse (seconds)</span>
              <div className="mt-1 flex items-center gap-2 text-sm">
                <input type="number" min={0} step={0.5} className="input w-24" aria-label="From (seconds)"
                  value={settings.start_seconds ?? 0}
                  onChange={(e) => set("start_seconds", Math.max(0, Number(e.target.value) || 0))} />
                <span className="text-ink-3">to</span>
                <input type="number" min={0} step={0.5} className="input w-24" aria-label="To (seconds)"
                  placeholder={video.duration_seconds.toFixed(1)}
                  value={settings.end_seconds ?? ""}
                  onChange={(e) => set("end_seconds", e.target.value === "" ? null : Math.max(0, Number(e.target.value)))} />
                <span className="text-xs text-ink-3">of {formatDuration(video.duration_seconds)}</span>
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
                <Field label="Detection resolution">
                  <select className="input" value={settings.image_size ?? 640}
                    onChange={(e) => set("image_size", Number(e.target.value) as AnalysisSettings["image_size"])}>
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
                  <Field label="Frame stride">
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

            <button className="btn btn-primary w-full py-2" disabled={submitting || settings.vehicle_types.length === 0 ||
                (settings.end_seconds != null && settings.end_seconds <= (settings.start_seconds ?? 0))}
              onClick={run}>
              {submitting ? "Submitting…" : "Run analysis"}
            </button>
            {settings.vehicle_types.length === 0 && <p className="text-xs text-red-600">Select at least one vehicle type.</p>}
          </section>

          <section className="card p-4">
            <h2 className="mb-2 font-semibold">Analyses</h2>
            {analyses.length === 0 ? (
              <p className="text-xs text-ink-3">No analyses yet.</p>
            ) : (
              <ul className="divide-y divide-[var(--border)]">
                {analyses.map((a) => (
                  <li key={a.id}>
                    <Link to={`/analyses/${a.id}`} className="flex items-center justify-between gap-2 py-2 text-sm hover:underline">
                      <span>{new Date(a.created_at).toLocaleString()}</span>
                      <StatusBadge status={a.status} progress={a.progress} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </aside>
      </div>
      {latest && <CountsDrawer analysis={latest} />}
      {pending && (
        <NameRegionDialog
          kind={pending.kind}
          color={nextColor}
          defaultName={pending.kind === "polygon"
            ? `Road ${regions.filter((r) => r.kind === "polygon").length + 1}`
            : `Line ${regions.filter((r) => r.kind === "line").length + 1}`}
          existingNames={regions.map((r) => r.name)}
          onSave={saveRegion}
          onCancel={() => setPending(null)}
        />
      )}
    </div>
  );
}

function ModeButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button className={`btn ${active ? "btn-primary" : ""}`} onClick={onClick} aria-pressed={active}>
      {children}
    </button>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="label">{label}</span>
      {children}
    </label>
  );
}

function RegionRow({
  region, color, selected, included, onToggleIncluded, onSelect, onPatch, onDelete,
}: {
  region: Region;
  color: string;
  selected: boolean;
  included: boolean;
  onToggleIncluded: (v: boolean) => void;
  onSelect: () => void;
  onPatch: (p: Partial<Region>) => void;
  onDelete: () => void;
}) {
  const [name, setName] = useState(region.name);
  const [fwd, setFwd] = useState(region.label_forward);
  const [bwd, setBwd] = useState(region.label_backward);
  useEffect(() => setName(region.name), [region.name]);
  useEffect(() => setFwd(region.label_forward), [region.label_forward]);
  useEffect(() => setBwd(region.label_backward), [region.label_backward]);

  const commit = (key: "name" | "label_forward" | "label_backward", value: string, original: string) => {
    const v = value.trim();
    if (v && v !== original) onPatch({ [key]: v });
  };

  return (
    <li className={`rounded-lg border px-2.5 py-2 ${selected ? "border-accent" : "border-line"}`} onClick={onSelect}>
      <div className="flex items-center gap-2">
        <input type="checkbox" checked={included} onChange={(e) => onToggleIncluded(e.target.checked)}
          onClick={(e) => e.stopPropagation()} title="Include in analysis" />
        <span className="h-3 w-3 shrink-0 rounded-sm" style={{ background: color }} />
        <input
          className="min-w-0 flex-1 rounded border border-transparent bg-transparent px-1 text-sm font-medium hover:border-line focus:border-accent focus:outline-none"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => commit("name", name, region.name)}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          aria-label="Region name"
        />
        <span className="text-[11px] text-ink-3">{region.kind === "polygon" ? "area" : "line"}</span>
        <button className="text-ink-3 hover:text-red-600" title="Delete" onClick={(e) => { e.stopPropagation(); onDelete(); }}>
          ✕
        </button>
      </div>
      {region.kind === "line" && selected && (
        <div className="mt-2 grid grid-cols-2 gap-2">
          <label className="space-y-0.5">
            <span className="label">Arrow direction</span>
            <input className="input py-1" value={fwd} onChange={(e) => setFwd(e.target.value)}
              onBlur={() => commit("label_forward", fwd, region.label_forward)} />
          </label>
          <label className="space-y-0.5">
            <span className="label">Opposite</span>
            <input className="input py-1" value={bwd} onChange={(e) => setBwd(e.target.value)}
              onBlur={() => commit("label_backward", bwd, region.label_backward)} />
          </label>
        </div>
      )}
    </li>
  );
}
