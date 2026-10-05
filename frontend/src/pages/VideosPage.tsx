import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import StatusBadge from "../components/StatusBadge";
import { api, formatBytes, formatDuration, type ImportListing, type VideoListItem } from "../lib/api";

const VIDEO_EXT = /\.(mp4|mov|avi|mkv|webm|ogv|ogg|m4v|mpg|mpeg|ts|wmv|flv|3gp)$/i;

interface UploadItem {
  key: string;
  file: File;
  progress: number;
  state: "waiting" | "uploading" | "done" | "error";
  error?: string;
  openWhenDone?: boolean; // a single video: go straight to drawing its areas
}

export default function VideosPage() {
  const [videos, setVideos] = useState<VideoListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const load = useCallback(() => {
    api.listVideos().then(setVideos).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  // Uploads run one at a time, so a queue of 100 files does not saturate the connection.
  const busy = uploads.some((u) => u.state === "uploading");
  useEffect(() => {
    if (busy) return;
    const next = uploads.find((u) => u.state === "waiting");
    if (!next) return;
    const patch = (p: Partial<UploadItem>) => setUploads((us) => us.map((u) => (u.key === next.key ? { ...u, ...p } : u)));
    patch({ state: "uploading" });
    api.uploadVideo(next.file, (progress) => patch({ progress }))
      .then((v) => {
        patch({ state: "done", progress: 1 });
        if (next.openWhenDone) navigate(`/videos/${v.id}`);
        else load();
      })
      .catch((e) => patch({ state: "error", error: (e as Error).message }));
  }, [uploads, busy, load, navigate]);

  const addFiles = (files: FileList | File[]) => {
    const list = [...files].filter((f) => VIDEO_EXT.test(f.name));
    if (list.length === 0) return setError("No video files found (MP4, MOV, AVI, MKV, WebM…).");
    setError(null);
    setUploads((us) => {
      const kept = us.filter((u) => u.state !== "done");
      const single = list.length === 1 && kept.every((u) => u.state === "error");
      return [...kept, ...list.map((file, i) => ({
        key: `${Date.now()}-${i}-${file.name}`, file, progress: 0, state: "waiting" as const, openWhenDone: single,
      }))];
    });
  };

  const remove = async (v: VideoListItem) => {
    if (!confirm(`Delete "${v.original_name}" and all of its analyses?`)) return;
    try {
      await api.deleteVideo(v.id);
      setSelected((s) => {
        const n = new Set(s);
        n.delete(v.id);
        return n;
      });
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const shown = (videos ?? []).filter((v) => v.original_name.toLowerCase().includes(filter.toLowerCase()));
  const toggle = (id: string, on: boolean) =>
    setSelected((s) => {
      const n = new Set(s);
      if (on) n.add(id);
      else n.delete(id);
      return n;
    });
  // Keep the batch in upload order (the list shows newest first).
  const selectedInOrder = [...(videos ?? [])].reverse().filter((v) => selected.has(v.id)).map((v) => v.id);
  const pending = uploads.filter((u) => u.state === "waiting" || u.state === "uploading").length;

  return (
    <div className="space-y-6">
      <div
        className={`card flex flex-col items-center justify-center gap-3 border-2 border-dashed px-6 py-8 text-center transition ${
          dragOver ? "border-accent bg-surface" : ""
        }`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          addFiles(e.dataTransfer.files);
        }}
      >
        <h1 className="text-lg font-semibold">Upload traffic videos</h1>
        <p className="max-w-lg text-sm text-ink-2">
          Drop one or many videos here (MP4, MOV, AVI, MKV, WebM). Then draw the roads to count on each video — or
          leave a video without areas to count its whole frame — select them below and run them all as a batch.
        </p>
        <button className="btn btn-primary" onClick={() => inputRef.current?.click()}>Choose videos</button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept="video/*,.mkv,.avi,.ts"
          className="hidden"
          aria-label="Choose videos"
          onChange={(e) => {
            if (e.target.files?.length) addFiles(e.target.files);
            e.target.value = "";
          }}
        />
        {uploads.length > 0 && <UploadList uploads={uploads} onClear={() => setUploads((us) => us.filter((u) => u.state === "waiting" || u.state === "uploading"))} />}
      </div>

      <ImportFolder onImported={load} onError={setError} />

      {error && (
        <div className="flex justify-between rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="ml-4">✕</button>
        </div>
      )}

      <section>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="mr-auto font-semibold">
            Videos {videos && <span className="font-normal text-ink-3">· {videos.length}</span>}
          </h2>
          {videos && videos.length > 0 && (
            <>
              <input className="input w-48 py-1 text-sm" placeholder="Filter by name…" value={filter}
                onChange={(e) => setFilter(e.target.value)} aria-label="Filter videos" />
              <button className="btn px-2 py-1 text-sm" onClick={() => setSelected(new Set(shown.map((v) => v.id)))}>
                Select all{filter ? " shown" : ""}
              </button>
              {selected.size > 0 && (
                <button className="btn px-2 py-1 text-sm" onClick={() => setSelected(new Set())}>Clear</button>
              )}
              <button
                className="btn btn-primary px-3 py-1 text-sm"
                disabled={selected.size === 0 || pending > 0}
                title={pending > 0 ? "Wait for uploads to finish" : undefined}
                onClick={() => navigate(`/batches/new?videos=${selectedInOrder.join(",")}`)}
              >
                ▶ Run {selected.size || ""} selected
              </button>
            </>
          )}
        </div>
        {videos === null ? (
          <p className="text-sm text-ink-3">Loading…</p>
        ) : videos.length === 0 ? (
          <p className="text-sm text-ink-3">No videos yet.</p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {shown.map((v) => (
              <div key={v.id} className={`card overflow-hidden ${selected.has(v.id) ? "ring-2 ring-[var(--accent)]" : ""}`}>
                <div className="relative">
                  <Link to={`/videos/${v.id}`} className="block aspect-video bg-black">
                    <img src={api.thumbnailUrl(v.id)} alt="" className="h-full w-full object-contain" loading="lazy" />
                  </Link>
                  <label className="absolute left-2 top-2 flex items-center gap-1 rounded bg-black/60 px-1.5 py-1 text-xs text-white">
                    <input type="checkbox" checked={selected.has(v.id)} onChange={(e) => toggle(v.id, e.target.checked)}
                      aria-label={`Select ${v.original_name}`} />
                    Select
                  </label>
                </div>
                <div className="space-y-1.5 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <Link to={`/videos/${v.id}`} className="block min-w-0 truncate font-medium hover:underline" title={v.original_name}>
                      {v.original_name}
                    </Link>
                    <button className="btn btn-danger shrink-0 px-2 py-1 text-xs" onClick={() => remove(v)}>Delete</button>
                  </div>
                  <p className="text-xs text-ink-3">
                    {v.width}×{v.height} · {v.fps.toFixed(1)} fps · {formatDuration(v.duration_seconds)} ·{" "}
                    {formatBytes(v.size_bytes)}{v.imported ? " · import folder" : ""}
                  </p>
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    {v.area_count + v.line_count > 0 ? (
                      <span className="rounded bg-surface px-1.5 py-0.5 text-ink-2" title={v.region_names.join(", ")}>
                        {v.area_count > 0 && `${v.area_count} area${v.area_count === 1 ? "" : "s"}`}
                        {v.area_count > 0 && v.line_count > 0 && " · "}
                        {v.line_count > 0 && `${v.line_count} line${v.line_count === 1 ? "" : "s"}`}
                      </span>
                    ) : (
                      <span className="rounded bg-surface px-1.5 py-0.5 text-ink-3" title="No areas drawn: the whole frame is counted">
                        Whole frame
                      </span>
                    )}
                    <Link to={`/videos/${v.id}`} className="text-ink-3 underline">Draw areas</Link>
                    {v.latest_status && v.latest_analysis_id && (
                      <Link to={`/analyses/${v.latest_analysis_id}`} className="ml-auto"><StatusBadge status={v.latest_status} /></Link>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function UploadList({ uploads, onClear }: { uploads: UploadItem[]; onClear: () => void }) {
  const done = uploads.filter((u) => u.state === "done").length;
  return (
    <div className="w-full max-w-xl text-left">
      <div className="mb-1 flex justify-between text-xs text-ink-2">
        <span>Uploaded {done} of {uploads.length}</span>
        {uploads.some((u) => u.state === "done" || u.state === "error") && (
          <button className="underline" onClick={onClear}>Clear finished</button>
        )}
      </div>
      <ul className="max-h-48 space-y-1 overflow-y-auto" aria-label="Uploads">
        {uploads.map((u) => (
          <li key={u.key} className="text-xs">
            <div className="flex justify-between gap-2">
              <span className="truncate">{u.file.name}</span>
              <span className={u.state === "error" ? "text-red-600" : "text-ink-3"}>
                {u.state === "waiting" ? "waiting" : u.state === "error" ? u.error : u.state === "done" ? "✓"
                  : u.progress >= 1 ? "reading…" : `${Math.round(u.progress * 100)}%`}
              </span>
            </div>
            {u.state === "uploading" && (
              <div className="h-1 rounded bg-surface">
                <div className="h-full rounded bg-accent transition-all" style={{ width: `${u.progress * 100}%` }} />
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Register videos already in the server's import folder (no upload; for very large files). */
function ImportFolder({ onImported, onError }: { onImported: () => void; onError: (m: string) => void }) {
  const [listing, setListing] = useState<ImportListing | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(() => api.importListing().then(setListing).catch(() => setListing(null)), []);
  useEffect(() => {
    refresh();
  }, [refresh]);
  if (!listing?.enabled) return null;
  const fresh = listing.files.filter((f) => !f.imported);
  const importAll = async () => {
    setBusy(true);
    try {
      await api.importVideos(fresh.map((f) => f.path));
      onImported();
      refresh();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-auto font-semibold">
          Import folder <span className="font-normal text-ink-3">· {listing.files.length} videos, {fresh.length} new</span>
        </h2>
        <button className="btn px-2 py-1 text-sm" onClick={() => { refresh(); setOpen(!open); }}>{open ? "Hide" : "Show files"}</button>
        <button className="btn btn-primary px-2 py-1 text-sm" disabled={busy || fresh.length === 0} onClick={importAll}>
          {busy ? "Importing…" : `Import ${fresh.length} new`}
        </button>
      </div>
      <p className="mt-1 text-xs text-ink-3">
        Long recordings can be copied into the import folder (<code>./videos</code> next to docker-compose.yml) instead
        of being uploaded through the browser. They are read in place.
      </p>
      {open && (
        <ul className="mt-2 max-h-56 overflow-y-auto text-xs">
          {listing.files.map((f) => (
            <li key={f.path} className="flex justify-between gap-2 border-b border-line py-1 last:border-0">
              <span className="truncate">{f.path}</span>
              <span className="text-ink-3">{formatBytes(f.size_bytes)} {f.imported ? "· imported" : ""}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
