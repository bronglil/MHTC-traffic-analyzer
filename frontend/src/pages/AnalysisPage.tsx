import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { SimpleBars, StackedBars, TimeColumns, presentTypes } from "../components/Charts";
import CountsDrawer from "../components/CountsDrawer";
import PipelineStages from "../components/PipelineStages";
import { SPEED_LABELS } from "../components/SettingsForm";
import StatusBadge from "../components/StatusBadge";
import { countEntries } from "../lib/counts";
import { api, formatDuration, type Analysis, type Summary, type TimeRow } from "../lib/api";
import { DIRECTION_ORDER, VEHICLE_LABELS, VEHICLE_TYPES, directionLabel, regionColor, vehicleColor } from "../lib/vehicles";

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
          <div className="flex flex-wrap gap-3 text-sm text-ink-3">
            <Link to={`/videos/${analysis.video_id}`} className="hover:underline">← Back to video</Link>
            {analysis.batch_id && (
              <Link to={`/batches/${analysis.batch_id}`} className="hover:underline">
                ← Batch (video {analysis.batch_position})
              </Link>
            )}
          </div>
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

function roadColor(analysis: Analysis, name: string): string {
  const regions = analysis.config.regions ?? [];
  const i = regions.findIndex((r) => r.name === name);
  if (i < 0) return "#94a3b8";
  return regions[i].color || regionColor(i);
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

type TabKey = "overview" | "types" | "directions" | "time" | "vehicles" | "lines" | "movements" | "video";

/** Results in tabs, with area and vehicle-type filters that apply to every tab. */
function Dashboard({ analysis, summary }: { analysis: Analysis; summary: Summary }) {
  const [tab, setTab] = useState<TabKey>("overview");
  const [areaFilter, setAreaFilter] = useState<string>(""); // "" = all; else "area:<name>" / "line:<name>"
  const [typeFilter, setTypeFilter] = useState<Set<string>>(new Set());

  const noResults = summary.areas.length === 0 && summary.lines.length === 0;
  const allTypes = presentTypes([...summary.areas, ...summary.lines]);
  const keepType = (t: string) => typeFilter.size === 0 || typeFilter.has(t);
  const pick = (byType: Record<string, number>) =>
    Object.fromEntries(Object.entries(byType).filter(([t]) => keepType(t)));
  const sum = (byType: Record<string, number>) => Object.values(byType).reduce((a, b) => a + b, 0);
  const filtered = <T extends { name: string; by_type: Record<string, number> }>(rows: T[], source: "area" | "line") =>
    rows
      .filter((r) => !areaFilter || areaFilter === `${source}:${r.name}`)
      .map((r) => ({ ...r, by_type: pick(r.by_type), total: sum(pick(r.by_type)) }));
  const areas = filtered(summary.areas, "area");
  const lines = filtered(summary.lines, "line");
  const movements = summary.movements ?? [];

  const tabs: { key: TabKey; label: string; show: boolean }[] = [
    { key: "overview", label: "Overview", show: true },
    { key: "types", label: "By vehicle type", show: !noResults },
    { key: "directions", label: "Directions", show: summary.areas.length > 0 },
    { key: "time", label: "Over time", show: !noResults },
    { key: "vehicles", label: "Counted vehicles", show: !noResults },
    { key: "lines", label: "Counting lines", show: summary.lines.length > 0 },
    { key: "movements", label: "Movements", show: movements.length > 0 },
    { key: "video", label: "Annotated video", show: analysis.has_annotated_video },
  ];
  const sources = [
    ...summary.areas.map((a) => ({ key: `area:${a.name}`, label: a.name })),
    ...summary.lines.map((l) => ({ key: `line:${l.name}`, label: `${l.name} (line)` })),
  ];
  const p = summary.processing;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1 border-b border-line" role="tablist" aria-label="Results">
        {tabs.filter((t) => t.show).map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === t.key ? "border-accent font-medium text-ink" : "border-transparent text-ink-2 hover:text-ink"}`}>
            {t.label}
          </button>
        ))}
      </div>

      {!noResults && tab !== "video" && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm" aria-label="Filters">
          <label className="flex items-center gap-2">
            <span className="text-ink-3">Area / line</span>
            <select className="input w-auto py-1" value={areaFilter} onChange={(e) => setAreaFilter(e.target.value)}
              aria-label="Filter by area or line">
              <option value="">All</option>
              {sources.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
          </label>
          <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Filter by vehicle type">
            <span className="mr-1 text-ink-3">Vehicle types</span>
            {allTypes.map((t) => {
              const on = typeFilter.has(t);
              return (
                <button key={t} aria-pressed={on}
                  className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${on ? "border-accent bg-surface" : "border-line text-ink-2"}`}
                  onClick={() => setTypeFilter((s) => {
                    const n = new Set(s);
                    if (on) n.delete(t);
                    else n.add(t);
                    return n;
                  })}>
                  <span className="h-2 w-2 rounded-sm" style={{ background: vehicleColor(t) }} />
                  {VEHICLE_LABELS[t] ?? t}
                </button>
              );
            })}
            {typeFilter.size > 0 && <button className="text-xs underline" onClick={() => setTypeFilter(new Set())}>all types</button>}
          </div>
        </div>
      )}

      {tab === "overview" && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-3">
            {[...areas, ...lines.map((l) => ({ ...l, name: `${l.name} (line)` }))].map((e) => (
              <div key={e.name} className="card min-w-[10rem] flex-1 px-3 py-2"
                style={{ borderLeft: `5px solid ${countEntries(analysis).find((c) => c.name === e.name.replace(/ \(line\)$/, ""))?.color ?? "var(--border)"}` }}>
                <div className="truncate text-xs text-ink-3" title={e.name}>{e.name}</div>
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
            <Tile label="Video processed" value={formatDuration(summary.video_duration_seconds)}
              sub={`${summary.frames_processed} frames in ${formatDuration(summary.processing_seconds)}` +
                (summary.processing_seconds > 0 ? ` · ${(summary.video_duration_seconds / summary.processing_seconds).toFixed(1)}× real time` : "")} />
            {p && (
              <Tile label="Processing" value={SPEED_LABELS[p.speed] ?? p.speed}
                sub={`${p.analysed_fps} frames/s analysed · ${p.image_size} px${p.sliced_detection ? " · tiles" : ""} · ${p.tracker}`} />
            )}
          </div>
          {noResults ? (
            <div className="card p-4 text-sm text-ink-2">
              No vehicles of the selected types were counted. Try lowering the detection confidence, reducing “min frames in
              area”, or checking that the areas cover the road.
            </div>
          ) : (
            <SummaryTable rows={[...areas, ...lines.map((l) => ({ ...l, name: `${l.name} (line)` }))]} />
          )}
        </div>
      )}

      {tab === "types" && (
        <section className="card p-4">
          <h2 className="mb-3 font-semibold">Vehicles by area &amp; type</h2>
          <StackedBars rows={[...areas, ...lines.map((l) => ({ ...l, name: `${l.name} (line)` }))]} />
        </section>
      )}

      {tab === "directions" && (
        <div className="grid gap-4 lg:grid-cols-2">
          {areas.map((a) => {
            const src = summary.areas.find((x) => x.name === a.name)!;
            const byDir = typeFilter.size && src.by_direction_type
              ? Object.fromEntries(Object.entries(src.by_direction_type).map(([d, bt]) => [d, sum(pick(bt))]))
              : src.by_direction;
            const items = DIRECTION_ORDER.filter((d) => byDir[d]).map((d) => ({ label: directionLabel(d), value: byDir[d] }));
            return (
              <section key={a.name} className="card p-4">
                <h2 className="mb-3 font-semibold">{a.name} <span className="font-normal text-ink-3">· {sum(byDir)}</span></h2>
                {items.length ? <SimpleBars items={items} /> : <p className="text-sm text-ink-3">No vehicles.</p>}
                {typeFilter.size > 0 && !src.by_direction_type && (
                  <p className="mt-2 text-xs text-ink-3">This analysis predates per-type directions: showing all types.</p>
                )}
              </section>
            );
          })}
          <p className="text-xs text-ink-3 lg:col-span-2">Compass directions are relative to the image (N = towards the top of the frame).</p>
        </div>
      )}

      {tab === "time" && (
        <div className="space-y-4">
          {sources.filter((s) => !areaFilter || s.key === areaFilter).map((s) => (
            <section key={s.key} className="card p-4">
              <h2 className="mb-3 font-semibold">{s.label} <span className="font-normal text-ink-3">· per {formatBin(summary.time_bin_seconds)}</span></h2>
              <TimeColumns rows={fillTimeRows(summary, s.key).map((r) => ({ ...r, by_type: pick(r.by_type) }))} />
            </section>
          ))}
        </div>
      )}

      {tab === "vehicles" && (
        <VehicleTable analysisId={analysis.id}
          zoneId={areaFilter.startsWith("area:") ? summary.areas.find((a) => `area:${a.name}` === areaFilter)?.id : undefined}
          types={typeFilter} />
      )}

      {tab === "lines" && (
        <section className="card p-4">
          <h2 className="mb-3 font-semibold">Counting lines by direction</h2>
          <StackedBars rows={lines.flatMap((l) =>
            Object.entries(summary.lines.find((x) => x.name === l.name)?.by_direction_type ?? {}).map(([d, byType]) => ({
              name: `${l.name} · ${d}`, by_type: pick(byType),
            })),
          )} />
        </section>
      )}

      {tab === "movements" && (
        <section className="card p-4">
          <h2 className="mb-3 font-semibold">Movements (from road → to road)</h2>
          <StackedBars rows={movements.map((m) => ({
            name: `${m.from} → ${m.to}`,
            by_type: pick(m.by_type),
            swatches: [roadColor(analysis, m.from), roadColor(analysis, m.to)],
          }))} />
        </section>
      )}

      {tab === "video" && analysis.has_annotated_video && (
        <section className="card p-4">
          <video src={api.annotatedVideoUrl(analysis.id)} controls className="max-h-[560px] w-full rounded-lg bg-black" />
        </section>
      )}
    </div>
  );
}

function SummaryTable({ rows }: { rows: { name: string; total: number; by_type: Record<string, number> }[] }) {
  const types = presentTypes(rows);
  return (
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
          {rows.map((row) => (
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

function VehicleTable({ analysisId, zoneId, types }: { analysisId: string; zoneId?: string; types: Set<string> }) {
  const [rows, setRows] = useState<VehicleRow[] | null>(null);
  const [page, setPage] = useState(0);
  const size = 50;
  const typeKey = [...types].sort().join(",");
  useEffect(() => setPage(0), [zoneId, typeKey]);
  useEffect(() => {
    // All records of the area once (up to 10k), filtered by type here; pages are client-side.
    const q = new URLSearchParams({ limit: "10000" });
    if (zoneId) q.set("zone_id", zoneId);
    fetch(`/api/analyses/${analysisId}/vehicles?${q}`)
      .then((r) => r.json())
      .then((d) => setRows(d.items));
  }, [analysisId, zoneId]);
  if (!rows) return <p className="text-sm text-ink-3">Loading…</p>;
  const all = types.size ? rows.filter((r) => types.has(r.vehicle_type)) : rows;
  const total = all.length;
  const visible = all.slice(page * size, (page + 1) * size);
  return (
    <section className="card overflow-x-auto p-4">
      <h2 className="mb-3 font-semibold">Counted vehicles <span className="font-normal text-ink-3">· {total} area events</span></h2>
      {total === 0 ? <p className="text-sm text-ink-3">No vehicles match the filters.</p> : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-ink-3">
              {["Area", "Track", "Type", "Direction", "First seen", "Last seen", "Confidence"].map((h) => (
                <th key={h} className="py-1.5 pr-3 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
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
      )}
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
