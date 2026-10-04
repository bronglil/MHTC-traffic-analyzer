import { useEffect, useState } from "react";
import { api, formatDuration, type StageSnapshot } from "../lib/api";

const DESCRIPTIONS: Record<string, string> = {
  frame: "Decoded video frame",
  detection: "Raw detector boxes with class & confidence",
  tracking: "Persistent IDs and motion trails",
  classification: "Per-track type after refinement (e.g. HGV>LGV2)",
  roi: "Which area each vehicle's ground point is in",
  counting: "Lines, direction of travel and running totals",
};

/**
 * Six synchronised panels, one per pipeline stage, refreshed about once a
 * second while the analysis runs (and left on the last snapshot afterwards).
 */
export default function PipelineStages({ analysisId, live }: { analysisId: string; live: boolean }) {
  const [snap, setSnap] = useState<StageSnapshot | null>(null);
  const [zoom, setZoom] = useState<string | null>(null);

  useEffect(() => {
    let stop = false;
    const load = () => api.stages(analysisId).then((s) => !stop && setSnap(s)).catch(() => undefined);
    load();
    if (!live) return () => void (stop = true);
    const t = setInterval(load, 1000);
    return () => {
      stop = true;
      clearInterval(t);
    };
  }, [analysisId, live]);

  if (!snap || snap.stages.length === 0) {
    return live ? (
      <section className="card p-4 text-sm text-ink-3">Pipeline stages will appear here once processing starts…</section>
    ) : null;
  }
  const zoomed = snap.stages.find((s) => s.key === zoom);

  return (
    <section className="card p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-semibold">Pipeline stages {live && <span className="ml-1 text-xs font-normal text-accent">● live</span>}</h2>
        {snap.frame_index !== null && (
          <span className="text-xs text-ink-3">
            frame {snap.frame_index} · {formatDuration(snap.timestamp ?? 0)} {live ? "" : "(last snapshot)"}
          </span>
        )}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {snap.stages.map((s) => (
          <figure key={s.key} className="overflow-hidden rounded-lg border border-line">
            <button className="block w-full bg-black" onClick={() => setZoom(s.key)} title="Enlarge">
              <img src={`${s.url}?v=${s.version}`} alt={s.title} className="aspect-video w-full object-contain" />
            </button>
            <figcaption className="px-2.5 py-1.5">
              <div className="text-sm font-medium">{s.title}</div>
              <div className="text-xs text-ink-3">{DESCRIPTIONS[s.key]}</div>
            </figcaption>
          </figure>
        ))}
      </div>
      {zoomed && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-6" onClick={() => setZoom(null)}>
          <figure className="max-h-full max-w-6xl">
            <img src={`${zoomed.url}?v=${zoomed.version}`} alt={zoomed.title} className="max-h-[85vh] rounded-lg" />
            <figcaption className="mt-2 text-center text-sm text-white">{zoomed.title} — click to close</figcaption>
          </figure>
        </div>
      )}
    </section>
  );
}
