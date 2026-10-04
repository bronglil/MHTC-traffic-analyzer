import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, formatBytes, formatDuration, type Video } from "../lib/api";

export default function VideosPage() {
  const [videos, setVideos] = useState<Video[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [upload, setUpload] = useState<{ name: string; progress: number } | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const load = useCallback(() => {
    api.listVideos().then(setVideos).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const doUpload = async (file: File) => {
    setError(null);
    setUpload({ name: file.name, progress: 0 });
    try {
      const v = await api.uploadVideo(file, (p) => setUpload({ name: file.name, progress: p }));
      navigate(`/videos/${v.id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUpload(null);
    }
  };

  const remove = async (v: Video) => {
    if (!confirm(`Delete "${v.original_name}" and all of its analyses?`)) return;
    try {
      await api.deleteVideo(v.id);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="space-y-6">
      <div
        className={`card flex flex-col items-center justify-center gap-3 border-2 border-dashed px-6 py-10 text-center transition ${
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
          const f = e.dataTransfer.files[0];
          if (f) doUpload(f);
        }}
      >
        <h1 className="text-lg font-semibold">Upload a traffic video</h1>
        <p className="max-w-md text-sm text-ink-2">
          Drop a video here or choose a file (MP4, MOV, AVI, MKV, WebM). You can then draw areas and counting lines,
          pick vehicle types and run the analysis.
        </p>
        {upload ? (
          <div className="w-full max-w-sm">
            <div className="mb-1 flex justify-between text-xs text-ink-2">
              <span className="truncate">{upload.name}</span>
              <span>{Math.round(upload.progress * 100)}%</span>
            </div>
            <div className="h-2 rounded bg-surface">
              <div className="h-full rounded bg-accent transition-all" style={{ width: `${upload.progress * 100}%` }} />
            </div>
            {upload.progress >= 1 && <p className="mt-1 text-xs text-ink-3">Reading video metadata…</p>}
          </div>
        ) : (
          <button className="btn btn-primary" onClick={() => inputRef.current?.click()}>
            Choose video
          </button>
        )}
        <input
          ref={inputRef}
          type="file"
          accept="video/*,.mkv,.avi,.ts"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) doUpload(f);
            e.target.value = "";
          }}
        />
      </div>

      {error && <div className="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

      <section>
        <h2 className="mb-3 font-semibold">Videos</h2>
        {videos === null ? (
          <p className="text-sm text-ink-3">Loading…</p>
        ) : videos.length === 0 ? (
          <p className="text-sm text-ink-3">No videos yet.</p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {videos.map((v) => (
              <div key={v.id} className="card overflow-hidden">
                <Link to={`/videos/${v.id}`} className="block aspect-video bg-black">
                  <img src={api.thumbnailUrl(v.id)} alt="" className="h-full w-full object-contain" loading="lazy" />
                </Link>
                <div className="flex items-start justify-between gap-2 p-3">
                  <div className="min-w-0">
                    <Link to={`/videos/${v.id}`} className="block truncate font-medium hover:underline" title={v.original_name}>
                      {v.original_name}
                    </Link>
                    <p className="text-xs text-ink-3">
                      {v.width}×{v.height} · {v.fps.toFixed(1)} fps · {formatDuration(v.duration_seconds)} ·{" "}
                      {formatBytes(v.size_bytes)}
                    </p>
                  </div>
                  <button className="btn btn-danger px-2 py-1 text-xs" onClick={() => remove(v)}>
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
