import { useState, type ReactNode } from "react";
import { VEHICLE_LABELS, VEHICLE_TYPES, vehicleColor } from "../lib/vehicles";

interface TooltipState {
  x: number;
  y: number;
  content: ReactNode;
}

function Tooltip({ state }: { state: TooltipState | null }) {
  if (!state) return null;
  return (
    <div
      className="pointer-events-none fixed z-50 rounded-lg border border-line bg-surface-1 px-2.5 py-1.5 text-xs text-ink shadow-lg"
      style={{ left: state.x + 12, top: state.y + 12 }}
    >
      {state.content}
    </div>
  );
}

export function Legend({ types }: { types: string[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
      {types.map((t) => (
        <span key={t} className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: vehicleColor(t) }} />
          {VEHICLE_LABELS[t] ?? t}
        </span>
      ))}
    </div>
  );
}

/** Types present in the data, in the fixed catalogue order (colour follows the type). */
export function presentTypes(rows: { by_type: Record<string, number> }[]): string[] {
  const seen = new Set(rows.flatMap((r) => Object.keys(r.by_type).filter((k) => r.by_type[k] > 0)));
  return [...VEHICLE_TYPES.filter((t) => seen.has(t)), ...[...seen].filter((t) => !VEHICLE_TYPES.includes(t as never))];
}

function Breakdown({ label, byType, types }: { label: string; byType: Record<string, number>; types: string[] }) {
  const total = types.reduce((s, t) => s + (byType[t] ?? 0), 0);
  return (
    <div>
      <div className="mb-1 font-medium">{label}</div>
      {types.filter((t) => byType[t]).map((t) => (
        <div key={t} className="flex items-center justify-between gap-4">
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-sm" style={{ background: vehicleColor(t) }} />
            {VEHICLE_LABELS[t] ?? t}
          </span>
          <span className="tabular-nums">{byType[t]}</span>
        </div>
      ))}
      <div className="mt-1 flex justify-between border-t border-line pt-1 text-ink-2">
        <span>Total</span>
        <span className="tabular-nums">{total}</span>
      </div>
    </div>
  );
}

/** Horizontal stacked bars: one row per entity, segments per vehicle type. */
export function StackedBars({ rows }: { rows: { name: string; by_type: Record<string, number> }[] }) {
  const [tip, setTip] = useState<TooltipState | null>(null);
  const types = presentTypes(rows);
  const max = Math.max(1, ...rows.map((r) => Object.values(r.by_type).reduce((a, b) => a + b, 0)));
  return (
    <div className="space-y-3">
      {types.length > 1 && <Legend types={types} />}
      <div className="space-y-2">
        {rows.map((r) => {
          const total = types.reduce((s, t) => s + (r.by_type[t] ?? 0), 0);
          return (
            <div key={r.name} className="grid grid-cols-[minmax(6rem,10rem)_1fr_3rem] items-center gap-3 text-sm">
              <span className="truncate text-ink-2" title={r.name}>{r.name}</span>
              <div
                className="flex h-5 cursor-default gap-[2px]"
                style={{ width: `${(total / max) * 100}%` }}
                onMouseMove={(e) =>
                  setTip({ x: e.clientX, y: e.clientY, content: <Breakdown label={r.name} byType={r.by_type} types={types} /> })
                }
                onMouseLeave={() => setTip(null)}
              >
                {types.filter((t) => r.by_type[t]).map((t, i, arr) => (
                  <div
                    key={t}
                    className={`h-full ${i === arr.length - 1 ? "rounded-r" : ""}`}
                    style={{ flexGrow: r.by_type[t], flexBasis: 0, background: vehicleColor(t), minWidth: 2 }}
                  />
                ))}
              </div>
              <span className="text-right text-sm font-medium tabular-nums">{total}</span>
            </div>
          );
        })}
      </div>
      <Tooltip state={tip} />
    </div>
  );
}

/** Single-series horizontal bars (e.g. counts by direction). */
export function SimpleBars({ items }: { items: { label: string; value: number }[] }) {
  const [tip, setTip] = useState<TooltipState | null>(null);
  const max = Math.max(1, ...items.map((i) => i.value));
  const total = items.reduce((s, i) => s + i.value, 0);
  return (
    <div className="space-y-1.5">
      {items.map((it) => (
        <div
          key={it.label}
          className="grid grid-cols-[7rem_1fr_3rem] items-center gap-3 text-sm"
          onMouseMove={(e) =>
            setTip({
              x: e.clientX,
              y: e.clientY,
              content: (
                <span>
                  <b>{it.label}</b>: {it.value} ({total ? Math.round((it.value / total) * 100) : 0}%)
                </span>
              ),
            })
          }
          onMouseLeave={() => setTip(null)}
        >
          <span className="truncate text-ink-2">{it.label}</span>
          <div className="h-4">
            <div className="h-full rounded-r" style={{ width: `${(it.value / max) * 100}%`, background: "var(--series-1)", minWidth: it.value ? 2 : 0 }} />
          </div>
          <span className="text-right font-medium tabular-nums">{it.value}</span>
        </div>
      ))}
      <Tooltip state={tip} />
    </div>
  );
}

/** Vertical stacked columns over time periods, segments per vehicle type. */
export function TimeColumns({ rows }: { rows: { period: string; period_start: number; by_type: Record<string, number> }[] }) {
  const [tip, setTip] = useState<TooltipState | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const types = presentTypes(rows);
  const totals = rows.map((r) => types.reduce((s, t) => s + (r.by_type[t] ?? 0), 0));
  const max = Math.max(1, ...totals);
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1];
  const H = 180;
  const labelEvery = Math.max(1, Math.ceil(rows.length / 8));
  return (
    <div className="space-y-3">
      {types.length > 1 && <Legend types={types} />}
      <div className="flex gap-2">
        <div className="relative w-8 text-right text-[11px] text-ink-3" style={{ height: H }}>
          {ticks.map((t) => (
            <span key={t} className="absolute right-0 -translate-y-1/2" style={{ top: H - (t / top) * H }}>{t}</span>
          ))}
        </div>
        <div className="relative flex-1 overflow-x-auto">
          <div className="relative" style={{ height: H, minWidth: rows.length * 14 }}>
            {ticks.map((t) => (
              <div key={t} className="absolute inset-x-0 border-t" style={{ top: H - (t / top) * H, borderColor: "var(--grid)" }} />
            ))}
            <div className="absolute inset-0 flex items-end gap-[2px]">
              {rows.map((r, i) => (
                <div
                  key={r.period_start}
                  className="flex h-full flex-1 flex-col justify-end"
                  style={{ opacity: hover === null || hover === i ? 1 : 0.55 }}
                  onMouseMove={(e) => {
                    setHover(i);
                    setTip({ x: e.clientX, y: e.clientY, content: <Breakdown label={r.period} byType={r.by_type} types={types} /> });
                  }}
                  onMouseLeave={() => {
                    setHover(null);
                    setTip(null);
                  }}
                >
                  <div className="flex flex-col-reverse gap-[2px]" style={{ height: `${(totals[i] / top) * 100}%` }}>
                    {types.filter((t) => r.by_type[t]).map((t, j, arr) => (
                      <div
                        key={t}
                        className={j === arr.length - 1 ? "rounded-t" : ""}
                        style={{ flexGrow: r.by_type[t], flexBasis: 0, background: vehicleColor(t), minHeight: 2 }}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="mt-1 flex gap-[2px] text-[11px] text-ink-3" style={{ minWidth: rows.length * 14 }}>
            {rows.map((r, i) => (
              <span key={r.period_start} className="flex-1 truncate text-center">
                {i % labelEvery === 0 ? r.period.split("–")[0] : ""}
              </span>
            ))}
          </div>
        </div>
      </div>
      <Tooltip state={tip} />
    </div>
  );
}

function niceTicks(max: number): number[] {
  const rough = max / 4;
  const pow = 10 ** Math.floor(Math.log10(Math.max(rough, 1)));
  const step = [1, 2, 5, 10].map((m) => m * pow).find((s) => s >= rough) ?? pow * 10;
  const out = [];
  for (let v = 0; v < max + step; v += step) out.push(v);
  return out;
}
