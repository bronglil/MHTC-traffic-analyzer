import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, formatDuration, type Batch } from "../lib/api";

export default function BatchesPage() {
  const [batches, setBatches] = useState<Batch[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const load = () => api.listBatches().then(setBatches).catch((e) => setError(e.message));
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);
  if (!batches) return <p className="text-sm text-ink-3">{error ?? "Loading…"}</p>;
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold">Batches</h1>
        <p className="text-sm text-ink-2">
          To start one, select videos on the <Link to="/" className="underline">videos page</Link> and choose “Run selected”.
        </p>
      </div>
      {batches.length === 0 ? (
        <p className="text-sm text-ink-3">No batches yet.</p>
      ) : (
        <ul className="space-y-2">
          {batches.map((b) => {
            const c = b.status_counts;
            return (
              <li key={b.id}>
                <Link to={`/batches/${b.id}`} className="card block p-3 hover:border-accent">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">{b.name}</span>
                    <span className="text-xs text-ink-3">{new Date(b.created_at).toLocaleString()}</span>
                  </div>
                  <div className="mt-1 text-xs text-ink-2">
                    {b.videos} videos · {formatDuration(b.total_video_seconds)} · {c.completed} done
                    {c.running ? ` · ${c.running} running` : ""}{c.queued ? ` · ${c.queued} waiting` : ""}
                    {c.failed ? ` · ${c.failed} failed` : ""}
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded bg-surface">
                    <div className="h-full rounded bg-accent" style={{ width: `${b.progress * 100}%` }} />
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
