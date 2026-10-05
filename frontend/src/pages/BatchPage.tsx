import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { SPEED_LABELS } from "../components/SettingsForm";
import StatusBadge from "../components/StatusBadge";
import { api, formatDuration, type AnalysisStatus, type Batch, type BatchItem } from "../lib/api";
import { VEHICLE_LABELS, VEHICLE_TYPES, vehicleColor } from "../lib/vehicles";

const FILTERS: { key: "all" | AnalysisStatus; label: string }[] = [
  { key: "all", label: "All" },
  { key: "running", label: "Running" },
  { key: "queued", label: "Waiting" },
  { key: "completed", label: "Completed" },
  { key: "failed", label: "Failed" },
  { key: "cancelled", label: "Cancelled" },
];

export default function BatchPage() {
  const { batchId = "" } = useParams();
  const navigate = useNavigate();
  const [batch, setBatch] = useState<Batch | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | AnalysisStatus>("all");

  const load = useCallback(() => api.getBatch(batchId).then(setBatch).catch((e) => setError(e.message)), [batchId]);
  useEffect(() => {
    load();
  }, [load]);
  const active = batch && (batch.status === "running" || batch.status === "queued");
  useEffect(() => {
    if (!active) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [active, load]);

  if (!batch) return <p className="text-sm text-ink-3">{error ?? "Loading…"}</p>;
  const items = batch.items ?? [];
  const c = batch.status_counts;
  const shown = filter === "all" ? items : items.filter((i) => i.status === filter);
  const finished = c.completed + c.failed + c.cancelled;
  const act = (f: () => Promise<Batch>) => f().then(setBatch).catch((e) => setError(e.message));
  const types = VEHICLE_TYPES.filter((t) => items.some((i) => i.by_type[t]));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link to="/batches" className="text-sm text-ink-3 hover:underline">← Batches</Link>
          <h1 className="text-lg font-semibold">{batch.name}</h1>
          <p className="text-xs text-ink-3">
            {batch.videos} videos · {formatDuration(batch.total_video_seconds)} of video ·{" "}
            {SPEED_LABELS[batch.settings.speed ?? "accurate"] ?? batch.settings.speed} speed · counting vehicles that{" "}
            {{ crossing: "cross", entering: "enter", present: "are seen in" }[batch.settings.count_rule ?? "crossing"]} each area ·
            created {new Date(batch.created_at).toLocaleString()}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <a className="btn" href={api.batchExportUrl(batch.id, "xlsx")} download>⭳ All videos (XLSX)</a>
          <a className="btn" href={api.batchExportUrl(batch.id, "zip")} download title="Summary plus each video's own report">
            ⭳ Every report (ZIP)
          </a>
          <a className="btn" href={api.batchExportUrl(batch.id, "csv")} download>⭳ CSV</a>
        </div>
      </div>
      {error && <div className="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

      <section className="card space-y-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span>
            <span className="font-medium">{finished} of {batch.videos} videos done</span>
            {c.running > 0 && <span className="text-ink-3"> · {c.running} running</span>}
            {c.queued > 0 && <span className="text-ink-3"> · {c.queued} waiting</span>}
            {c.failed > 0 && <span className="text-red-600"> · {c.failed} failed</span>}
            {c.cancelled > 0 && <span className="text-ink-3"> · {c.cancelled} cancelled</span>}
          </span>
          <span className="font-medium tabular-nums">{Math.round(batch.progress * 100)}%</span>
        </div>
        <div className="h-2.5 overflow-hidden rounded bg-surface" role="progressbar" aria-label="Batch progress"
          aria-valuenow={Math.round(batch.progress * 100)} aria-valuemin={0} aria-valuemax={100}>
          <div className="h-full rounded bg-accent transition-all duration-500" style={{ width: `${batch.progress * 100}%` }} />
        </div>
        <div className="flex flex-wrap gap-2">
          {active && <button className="btn btn-danger" onClick={() => act(() => api.cancelBatch(batch.id))}>Cancel remaining</button>}
          {(c.failed > 0 || c.cancelled > 0) && (
            <button className="btn" onClick={() => act(() => api.retryBatch(batch.id))}>Run failed / cancelled again</button>
          )}
          {!active && (
            <button className="btn btn-danger ml-auto" onClick={async () => {
              if (!confirm("Delete this batch and its results? The videos are kept.")) return;
              await api.deleteBatch(batch.id).then(() => navigate("/batches")).catch((e) => setError(e.message));
            }}>Delete batch</button>
          )}
        </div>
      </section>

      <section className="card p-4">
        <div className="mb-3 flex flex-wrap gap-1" role="tablist" aria-label="Filter videos">
          {FILTERS.filter((f) => f.key === "all" || c[f.key as AnalysisStatus] > 0).map((f) => (
            <button key={f.key} role="tab" aria-selected={filter === f.key}
              className={`rounded-full px-3 py-1 text-sm ${filter === f.key ? "bg-accent text-white" : "bg-surface text-ink-2"}`}
              onClick={() => setFilter(f.key)}>
              {f.label} <span className="tabular-nums opacity-75">{f.key === "all" ? items.length : c[f.key as AnalysisStatus]}</span>
            </button>
          ))}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-ink-3">
                <th className="py-1.5 pr-2 font-medium">#</th>
                <th className="py-1.5 pr-2 font-medium">Video</th>
                <th className="py-1.5 pr-2 font-medium">Status</th>
                <th className="py-1.5 pr-2 font-medium">Counts per area / line</th>
                {types.map((t) => (
                  <th key={t} className="px-1.5 py-1.5 text-right font-medium">
                    <span className="inline-flex items-center gap-1">
                      <span className="inline-block h-2 w-2 rounded-sm" style={{ background: vehicleColor(t) }} />
                      {VEHICLE_LABELS[t]}
                    </span>
                  </th>
                ))}
                <th className="py-1.5 font-medium" />
              </tr>
            </thead>
            <tbody>
              {shown.map((i) => <Row key={i.analysis_id} item={i} types={types} />)}
            </tbody>
          </table>
          {shown.length === 0 && <p className="py-3 text-sm text-ink-3">No videos with this status.</p>}
        </div>
      </section>
    </div>
  );
}

function Row({ item: i, types }: { item: BatchItem; types: string[] }) {
  return (
    <tr className="border-b border-line align-top last:border-0">
      <td className="py-1.5 pr-2 tabular-nums text-ink-3">{i.position}</td>
      <td className="max-w-[16rem] py-1.5 pr-2">
        <Link to={`/videos/${i.video_id}`} className="block truncate hover:underline" title={i.video_name}>{i.video_name}</Link>
        <span className="text-xs text-ink-3">{formatDuration(i.duration_seconds)}
          {i.processing_seconds != null && ` · took ${formatDuration(i.processing_seconds)}`}</span>
      </td>
      <td className="py-1.5 pr-2">
        <StatusBadge status={i.status} progress={i.progress} />
        {(i.status === "running" || i.status === "failed") && i.message && (
          <span className="mt-0.5 block max-w-[16rem] truncate text-xs text-ink-3" title={i.message}>{i.message.split("\n")[0]}</span>
        )}
      </td>
      <td className="py-1.5 pr-2 text-xs">
        {i.status === "completed" ? (
          Object.entries(i.counts).map(([name, n]) => (
            <span key={name} className="mr-2 inline-block whitespace-nowrap">{name} <b className="tabular-nums">{n}</b></span>
          ))
        ) : (
          <span className="text-ink-3">{[...i.areas, ...i.lines.map((l) => `${l} (line)`)].join(", ")}</span>
        )}
      </td>
      {types.map((t) => (
        <td key={t} className="px-1.5 py-1.5 text-right tabular-nums">{i.status === "completed" ? i.by_type[t] ?? 0 : ""}</td>
      ))}
      <td className="py-1.5 text-right">
        <Link to={`/analyses/${i.analysis_id}`} className="text-xs underline">{i.status === "completed" ? "Report" : "Open"}</Link>
      </td>
    </tr>
  );
}
