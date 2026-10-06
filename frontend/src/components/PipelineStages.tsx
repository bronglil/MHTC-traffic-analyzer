import { useEffect, useState } from "react";
import { api, formatDuration, type StageSnapshot } from "../lib/api";
import type { CountEntry } from "../lib/counts";

const DESCRIPTIONS: Record<string, string> = {
  frame: "Decoded video frame",
  detection: "Raw detector boxes with class & confidence",
  tracking: "Persistent IDs and motion trails",
  classification: "Per-track type after refinement (e.g. HGV>LGV2)",
  roi: "Which area the base is on. A black-and-white bar means the frame did not move there",
  counting: "Lines, direction of travel and running totals",
};

/**
 * Six synchronised panels, one per pipeline stage, refreshed about once a
 * second while the analysis runs (and left on the last snapshot afterwards).
 */
export default function PipelineStages({ analysisId, live, legend = [] }: {
  analysisId: string;
  live: boolean;
  legend?: CountEntry[];
}) {
  const [snap, setSnap] = useState<StageSnapshot | null>(null);
  const [zoom, setZoom] = useState<string | null>(null);
  const [showStages, setShowStages] = useState(true);

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
    <>
    {snap.live_url && (
      <section className="card p-4">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="font-semibold">
            Live view {live && <span className="ml-1 text-xs font-normal text-accent">● live</span>}
          </h2>
          <span className="text-xs text-ink-3">
            {snap.timestamp !== null && formatDuration(snap.timestamp ?? 0)} {live ? "" : "(last frame processed)"}
          </span>
        </div>
        <div className="grid gap-4 lg:grid-cols-[1fr_15rem]">
          <img src={snap.live_url} alt="Annotated live frame with selected areas" className="w-full rounded-lg bg-black" />
          <ul className="space-y-1.5 text-sm" aria-label="Selected areas">
            {legend.map((e) => (
              <li key={e.id} className="flex items-center gap-2">
                <span className="h-3 w-3 shrink-0 rounded-sm" style={{ background: e.color }} />
                <span className="flex-1 truncate" title={e.name}>{e.name}</span>
                <span className="font-semibold tabular-nums">{e.total}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>
    )}
    <section className="card p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-semibold">
          <button className="hover:underline" onClick={() => setShowStages((v) => !v)} aria-expanded={showStages}>
            {showStages ? "▾" : "▸"} Pipeline stages
          </button>
          {live && <span className="ml-1 text-xs font-normal text-accent">● live</span>}
        </h2>
        {snap.frame_index !== null && (
          <span className="text-xs text-ink-3">
            frame {snap.frame_index} · {formatDuration(snap.timestamp ?? 0)} {live ? "" : "(last snapshot)"}
          </span>
        )}
      </div>
      {showStages && <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
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
      </div>}
      {zoomed && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-6" onClick={() => setZoom(null)}>
          <figure className="max-h-full max-w-6xl">
            <img src={`${zoomed.url}?v=${zoomed.version}`} alt={zoomed.title} className="max-h-[85vh] rounded-lg" />
            <figcaption className="mt-2 text-center text-sm text-white">{zoomed.title} — click to close</figcaption>
          </figure>
        </div>
      )}
    </section>
    </>
  );
}
