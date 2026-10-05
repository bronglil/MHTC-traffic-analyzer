import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { SimpleBars, StackedBars, TimeColumns, presentTypes } from "../components/Charts";
import CountsDrawer from "../components/CountsDrawer";
import PipelineStages from "../components/PipelineStages";
import StatusBadge from "../components/StatusBadge";
import { countEntries } from "../lib/counts";
import { api, formatDuration, type Analysis, type Summary, type TimeRow } from "../lib/api";
import { DIRECTION_ORDER, VEHICLE_LABELS, VEHICLE_TYPES, directionLabel, vehicleColor } from "../lib/vehicles";

const ACTIVE = new Set(["queued", "running"]);

export default function AnalysisPage() {
  const { analysisId = "" } = useParams();
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    const load = () =>
      api.getAnalysis(analysisId).then((a) => {
        if (closed) return;
        setAnalysis(a);
        if (ACTIVE.has(a.status) && !ws) connect();
      }).catch((e) => setError(e.message));

    const connect = () => {
      ws = api.progressSocket(analysisId);
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.error) return;
        setAnalysis((a) => (a ? { ...a, ...msg } : a));
        if (!ACTIVE.has(msg.status)) load(); // fetch final summary
      };
      ws.onclose = () => {
        ws = null;
        // Reconnect / refresh if the socket dropped mid-run.
        if (!closed) setTimeout(() => !closed && load(), 2000);
      };
    };

    load();
    return () => {
      closed = true;
      ws?.close();
    };
  }, [analysisId]);

  if (!analysis) return <p className="text-sm text-ink-3">{error ?? "Loading…"}</p>;


  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link to={`/videos/${analysis.video_id}`} className="text-sm text-ink-3 hover:underline">← Back to video</Link>
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            Analysis results <StatusBadge status={analysis.status} progress={analysis.progress} />
          </h1>
          <p className="text-xs text-ink-3">
            {analysis.config.vehicle_types.map((t) => VEHICLE_LABELS[t] ?? t).join(", ")} · {analysis.config.detector ?? "yolo"}{" "}
            detector · {analysis.config.tracker} tracker
            {analysis.config.count_rule ? ` · counting vehicles that ${{ crossing: "cross", entering: "enter", present: "are seen in" }[analysis.config.count_rule]} each area` : ""}
            {(analysis.config.start_seconds || analysis.config.end_seconds) ? ` · ${formatDuration(analysis.config.start_seconds ?? 0)}–${analysis.config.end_seconds ? formatDuration(analysis.config.end_seconds) : "end"}` : ""} · {analysis.config.classification ?? "size"} classification · started{" "}
            {new Date(analysis.created_at).toLocaleString()}
          </p>
        </div>
        {analysis.status === "completed" && <ExportButtons analysis={analysis} />}
      </div>

      {ACTIVE.has(analysis.status) && <Progress analysis={analysis} />}
      <PipelineStages analysisId={analysis.id} live={ACTIVE.has(analysis.status)} legend={countEntries(analysis)} />
      <CountsDrawer analysis={analysis} />
      {analysis.status === "failed" && (
        <div className="card border-red-300 p-4 text-sm">
          <p className="font-medium text-red-700">Analysis failed</p>
          <pre className="mt-2 whitespace-pre-wrap text-xs text-ink-2">{analysis.message}</pre>
        </div>
      )}
      {analysis.status === "cancelled" && <p className="text-sm text-ink-2">This analysis was cancelled.</p>}
      {analysis.status === "completed" && analysis.summary && <Dashboard analysis={analysis} summary={analysis.summary} />}
    </div>
  );
}

/** One tile per selected road/area/line, in its own colour, with the per-type split. */
function CountTiles({ analysis }: { analysis: Analysis }) {
  return (
    <div className="flex flex-wrap gap-3">
      {countEntries(analysis).map((e) => (
        <div key={e.id} className="card min-w-[10rem] flex-1 px-3 py-2" style={{ borderLeft: `5px solid ${e.color}` }}>
          <div className="truncate text-xs text-ink-3" title={e.name}>
            {e.name}
            {e.kind === "line" && " (line)"}
          </div>
          <div className="text-2xl font-semibold tabular-nums">{e.total}</div>
          <div className="mt-0.5 flex flex-wrap gap-x-2 text-[11px] text-ink-2">
            {VEHICLE_TYPES.filter((t) => e.by_type[t]).map((t) => (
              <span key={t} className="inline-flex items-center gap-1">
                <span className="h-1.5 w-1.5 rounded-sm" style={{ background: vehicleColor(t) }} />
                {VEHICLE_LABELS[t]} {e.by_type[t]}
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function Progress({ analysis }: { analysis: Analysis }) {
  const [cancelling, setCancelling] = useState(false);
  const pct = Math.round(analysis.progress * 100);
  return (
    <div className="card space-y-4 p-4">
      <div>
        <div className="mb-1 flex justify-between text-sm">
          <span className="text-ink-2">{analysis.status === "queued" ? "Waiting for a worker…" : analysis.message}</span>
          <span className="font-medium tabular-nums">{pct}%</span>
        </div>
        <div className="h-2.5 overflow-hidden rounded bg-surface" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
          <div className="h-full rounded bg-accent transition-all duration-500" style={{ width: `${pct}%` }} />
        </div>
      </div>
      <div>
        <p className="label mb-2">Real-time counts (provisional — includes vehicles still in view)</p>
        <CountTiles analysis={analysis} />
      </div>
      <button
        className="btn btn-danger"
        disabled={cancelling}
        onClick={async () => {
          setCancelling(true);
          await api.cancelAnalysis(analysis.id).catch(() => undefined);
        }}
      >
        {cancelling ? "Cancelling…" : "Cancel analysis"}
      </button>
    </div>
  );
}

function ExportButtons({ analysis }: { analysis: Analysis }) {
  const formats = [
    ["csv", "CSV"],
    ["xlsx", "Excel (XLSX)"],
    ["json", "JSON"],
    ["csv_bundle", "All tables (CSV zip)"],
  ] as const;
  return (
    <div className="flex flex-wrap gap-2">
      {formats.map(([f, label]) => (
        <a key={f} className="btn" href={api.exportUrl(analysis.id, f)} download>
          ⭳ {label}
        </a>
      ))}
      {analysis.has_annotated_video && (
        <a className="btn" href={api.annotatedVideoUrl(analysis.id, true)} download>
          ⭳ Annotated video
        </a>
      )}
    </div>
  );
}

function Tile({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="card min-w-[9rem] flex-1 p-4">
      <div className="truncate text-xs text-ink-3" title={label}>{label}</div>
      <div className="mt-1 text-3xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-ink-3">{sub}</div>}
    </div>
  );
}

function Dashboard({ analysis, summary }: { analysis: Analysis; summary: Summary }) {
  const areaNames = summary.areas.map((a) => a.name);
  const sources = [
    ...summary.areas.map((a) => ({ key: `area:${a.name}`, label: a.name })),
    ...summary.lines.map((l) => ({ key: `line:${l.name}`, label: `${l.name} (line)` })),
  ];
  const [dirArea, setDirArea] = useState(areaNames[0] ?? "");
  const [timeSource, setTimeSource] = useState(sources[0]?.key ?? "");

  const noResults = summary.areas.length === 0 && summary.lines.length === 0;

  const timeRows = useMemo(() => fillTimeRows(summary, timeSource), [summary, timeSource]);
  const dirItems = useMemo(() => {
    const area = summary.areas.find((a) => a.name === dirArea);
    if (!area) return [];
    return DIRECTION_ORDER.filter((d) => area.by_direction[d]).map((d) => ({ label: directionLabel(d), value: area.by_direction[d] }));
  }, [summary, dirArea]);

  const types = presentTypes([...summary.areas, ...summary.lines]);

  return (
    <div className="space-y-5">
      <CountTiles analysis={analysis} />
      <div className="flex flex-wrap gap-3">
        <Tile label="Video processed" value={formatDuration(summary.video_duration_seconds)}
          sub={`${summary.frames_processed} frames in ${formatDuration(summary.processing_seconds)}`} />
      </div>

      {noResults && (
        <div className="card p-4 text-sm text-ink-2">
          No vehicles of the selected types were counted. Try lowering the detection confidence, reducing “min frames in
          area”, or checking that the areas cover the road.
        </div>
      )}

      {analysis.has_annotated_video && (
        <section className="card p-4">
          <h2 className="mb-3 font-semibold">Annotated video</h2>
          <video src={api.annotatedVideoUrl(analysis.id)} controls className="max-h-[480px] w-full rounded-lg bg-black" />
        </section>
      )}

      {!noResults && (
        <div className="grid gap-5 lg:grid-cols-2">
          <section className="card p-4">
            <h2 className="mb-3 font-semibold">Vehicles by area &amp; type</h2>
            <StackedBars rows={summary.areas} />
          </section>

          <section className="card p-4">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="font-semibold">Direction of travel</h2>
              <select className="input w-auto" value={dirArea} onChange={(e) => setDirArea(e.target.value)}>
                {areaNames.map((n) => <option key={n}>{n}</option>)}
              </select>
            </div>
            <SimpleBars items={dirItems} />
            <p className="mt-2 text-xs text-ink-3">Compass directions are relative to the image (N = towards the top of the frame).</p>
          </section>

          {summary.lines.length > 0 && (
            <section className="card p-4">
              <h2 className="mb-3 font-semibold">Counting lines</h2>
              <StackedBars rows={summary.lines.flatMap((l) =>
                Object.entries(l.by_direction_type ?? {}).map(([d, byType]) => ({ name: `${l.name} · ${d}`, by_type: byType })),
              )} />
            </section>
          )}

          <section className="card p-4 lg:col-span-2">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="font-semibold">Vehicles over time <span className="font-normal text-ink-3">· per {formatBin(summary.time_bin_seconds)}</span></h2>
              <select className="input w-auto" value={timeSource} onChange={(e) => setTimeSource(e.target.value)}>
                {sources.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
              </select>
            </div>
            <TimeColumns rows={timeRows} />
          </section>
        </div>
      )}

      {!noResults && (
        <section className="card overflow-x-auto p-4">
          <h2 className="mb-3 font-semibold">Summary table</h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-ink-3">
                <th className="py-1.5 pr-3 font-medium">Area / line</th>
                {types.map((t) => (
                  <th key={t} className="px-2 py-1.5 text-right font-medium">
                    <span className="inline-flex items-center gap-1">
                      <span className="inline-block h-2 w-2 rounded-sm" style={{ background: vehicleColor(t) }} />
                      {VEHICLE_LABELS[t] ?? t}
                    </span>
                  </th>
                ))}
                <th className="py-1.5 pl-2 text-right font-medium">Total</th>
              </tr>
            </thead>
            <tbody>
              {[...summary.areas, ...summary.lines.map((l) => ({ ...l, name: `${l.name} (line)` }))].map((row) => (
                <tr key={row.name} className="border-b border-line last:border-0">
                  <td className="py-1.5 pr-3">{row.name}</td>
                  {types.map((t) => (
                    <td key={t} className="px-2 py-1.5 text-right tabular-nums">{row.by_type[t] ?? 0}</td>
                  ))}
                  <td className="py-1.5 pl-2 text-right font-medium tabular-nums">{row.total}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <VehicleTable analysisId={analysis.id} />
    </div>
  );
}

function formatBin(s: number) {
  if (s % 3600 === 0) return s === 3600 ? "hour" : `${s / 3600} hours`;
  if (s % 60 === 0) return s === 60 ? "minute" : `${s / 60} minutes`;
  return `${s} seconds`;
}

/** Time rows for one area/line with empty periods filled in, so gaps read as zero. */
function fillTimeRows(summary: Summary, key: string): TimeRow[] {
  const [source, ...rest] = key.split(":");
  const name = rest.join(":");
  const rows = summary.by_time.filter((r) => r.source === source && r.name === name);
  const bin = summary.time_bin_seconds;
  const last = Math.max(
    Math.floor(Math.max(0, summary.video_duration_seconds - 1e-6) / bin) * bin,
    ...rows.map((r) => r.period_start),
  );
  const byStart = new Map(rows.map((r) => [r.period_start, r]));
  const fmt = (s: number) => {
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    return [h, m, sec].map((v) => String(v).padStart(2, "0")).join(":");
  };
  const out: TimeRow[] = [];
  for (let s = 0; s <= last; s += bin) {
    out.push(byStart.get(s) ?? { source: source as TimeRow["source"], name, period_start: s, period: `${fmt(s)}–${fmt(s + bin)}`, total: 0, by_type: {} });
  }
  return out;
}

interface VehicleRow {
  zone_name: string;
  track_id: number;
  vehicle_type: string;
  direction: string;
  first_time: number;
  last_time: number;
  mean_confidence: number;
}

function VehicleTable({ analysisId }: { analysisId: string }) {
  const [rows, setRows] = useState<VehicleRow[] | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const size = 50;
  useEffect(() => {
    fetch(`/api/analyses/${analysisId}/vehicles?limit=${size}&offset=${page * size}`)
      .then((r) => r.json())
      .then((d) => {
        setRows(d.items);
        setTotal(d.total);
      });
  }, [analysisId, page]);
  if (!rows || total === 0) return null;
  return (
    <section className="card overflow-x-auto p-4">
      <h2 className="mb-3 font-semibold">Counted vehicles <span className="font-normal text-ink-3">· {total} area events</span></h2>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs text-ink-3">
            {["Area", "Track", "Type", "Direction", "First seen", "Last seen", "Confidence"].map((h) => (
              <th key={h} className="py-1.5 pr-3 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.zone_name}-${r.track_id}`} className="border-b border-line last:border-0">
              <td className="py-1 pr-3">{r.zone_name}</td>
              <td className="py-1 pr-3 tabular-nums">#{r.track_id}</td>
              <td className="py-1 pr-3">
                <span className="inline-flex items-center gap-1.5">
                  <span className="inline-block h-2 w-2 rounded-sm" style={{ background: vehicleColor(r.vehicle_type) }} />
                  {VEHICLE_LABELS[r.vehicle_type] ?? r.vehicle_type}
                </span>
              </td>
              <td className="py-1 pr-3">{directionLabel(r.direction)}</td>
              <td className="py-1 pr-3 tabular-nums">{formatDuration(r.first_time)}</td>
              <td className="py-1 pr-3 tabular-nums">{formatDuration(r.last_time)}</td>
              <td className="py-1 pr-3 tabular-nums">{r.mean_confidence.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {total > size && (
        <div className="mt-3 flex items-center gap-2 text-sm">
          <button className="btn" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
          <span className="text-ink-3">Page {page + 1} of {Math.ceil(total / size)}</span>
          <button className="btn" disabled={(page + 1) * size >= total} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}
    </section>
  );
}
