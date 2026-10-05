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
  type VideoListItem,
} from "../lib/api";
import CountsDrawer from "../components/CountsDrawer";
import NameRegionDialog, { type RegionDetails } from "../components/NameRegionDialog";
import SettingsForm, { DEFAULT_SETTINGS, defaultTimeBin, settingsInvalid } from "../components/SettingsForm";
import { REGION_COLORS, regionColor } from "../lib/vehicles";

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
  const [allVideos, setAllVideos] = useState<VideoListItem[]>([]);

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
        sliced_detection: v.width >= 1800, // HD/4K: distant vehicles are small

      }));
    }).catch(fail);
    api.meta().then(setMeta).catch(() => undefined);
    api.listVideos().then(setAllVideos).catch(() => undefined);
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
        <VideoStepper videoId={video.id} videos={allVideos} />
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
          </div>
          <p className="text-xs text-ink-3" role="status">
            {mode === "rect" && "Press and drag over the road you want to count (at least 20 px), then name it. Esc to cancel."}
            {mode === "polygon" && "Click to add points · click the first point, double-click or press Enter to finish · Esc to cancel"}
            {mode === "line" && "Click the start point, then the end point · Esc to cancel"}
            {mode === "select" && "Click a shape to select · drag it or its points to edit · Delete to remove"}
          </p>
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
            <CopyAreas
              videoId={video.id}
              videos={allVideos}
              hasOwn={regions.length > 0}
              onCopied={(rs) => {
                setRegions(rs);
                setSelectedId(null);
                if (rs.some((r) => r.kind === "polygon")) setSettings((st) => ({ ...st, include_whole_frame: false }));
                api.listVideos().then(setAllVideos).catch(() => undefined);
              }}
              onError={fail}
            />
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
            <SettingsForm settings={settings} setSettings={setSettings} meta={meta} video={video} />
            <button className="btn btn-primary w-full py-2" disabled={submitting || !!settingsInvalid(settings)} onClick={run}>
              {submitting ? "Submitting…" : "Run analysis"}
            </button>
            {settings.vehicle_types.length === 0 && <p className="text-xs text-red-600">Select at least one vehicle type.</p>}
            <p className="text-xs text-ink-3">
              Many videos? Draw each video’s areas, then select them on the{" "}
              <Link to="/" className="underline">videos page</Link> and run them together as a batch.
            </p>
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

function ModeButton({ active, onClick, children, title }: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <button className={`btn ${active ? "btn-primary" : ""}`} onClick={onClick} aria-pressed={active} title={title}>
      {children}
    </button>
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

/** Step through the uploaded videos to draw each one's areas before running them as a batch. */
function VideoStepper({ videoId, videos }: { videoId: string; videos: VideoListItem[] }) {
  const ordered = [...videos].reverse(); // upload order
  const i = ordered.findIndex((v) => v.id === videoId);
  if (i < 0 || ordered.length < 2) return null;
  const prev = ordered[i - 1];
  const next = ordered[i + 1];
  const todo = ordered.filter((v) => v.area_count + v.line_count === 0 && v.id !== videoId).length;
  return (
    <nav className="flex items-center gap-2 text-sm" aria-label="Videos">
      {prev ? <Link className="btn px-2 py-1" to={`/videos/${prev.id}`} title={prev.original_name}>← Previous</Link>
        : <span className="btn px-2 py-1 opacity-40">← Previous</span>}
      <span className="text-ink-3 tabular-nums">Video {i + 1} of {ordered.length}</span>
      {next ? <Link className="btn px-2 py-1" to={`/videos/${next.id}`} title={next.original_name}>Next →</Link>
        : <span className="btn px-2 py-1 opacity-40">Next →</span>}
      {todo > 0 && <span className="text-xs text-ink-3">{todo} other{todo === 1 ? "" : "s"} without areas (whole frame)</span>}
    </nav>
  );
}

/** Reuse the areas drawn on another video of the same camera view. */
function CopyAreas({ videoId, videos, hasOwn, onCopied, onError }: {
  videoId: string;
  videos: VideoListItem[];
  hasOwn: boolean;
  onCopied: (regions: Region[]) => void;
  onError: (e: unknown) => void;
}) {
  const sources = videos.filter((v) => v.id !== videoId && v.area_count + v.line_count > 0);
  const [from, setFrom] = useState("");
  if (sources.length === 0) return null;
  const copy = async () => {
    if (!from) return;
    if (hasOwn && !confirm("Replace this video's areas and lines with the copied ones?")) return;
    try {
      onCopied(await api.copyRegions(videoId, from, true));
      setFrom("");
    } catch (e) {
      onError(e);
    }
  };
  return (
    <div className="mt-3 flex items-center gap-2 border-t border-line pt-3">
      <select className="input min-w-0 flex-1 py-1 text-xs" value={from} onChange={(e) => setFrom(e.target.value)}
        aria-label="Copy areas from video">
        <option value="">Copy areas from another video…</option>
        {sources.map((v) => (
          <option key={v.id} value={v.id}>{v.original_name} ({v.region_names.join(", ")})</option>
        ))}
      </select>
      <button className="btn px-2 py-1 text-xs" disabled={!from} onClick={copy}>Copy</button>
    </div>
  );
}
