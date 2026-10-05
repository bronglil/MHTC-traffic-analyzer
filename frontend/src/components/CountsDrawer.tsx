import { useEffect, useState } from "react";
import type { Analysis } from "../lib/api";
import { countEntries } from "../lib/counts";
import { DIRECTION_ORDER, VEHICLE_LABELS, VEHICLE_TYPES, directionLabel, vehicleColor } from "../lib/vehicles";

/**
 * A tab fixed to the right edge of the screen; clicking it slides in a drawer
 * with the classified counts for every selected road/area/line — live while
 * the video is processing, final once it has finished.
 */
export default function CountsDrawer({ analysis }: { analysis: Analysis }) {
  const [open, setOpen] = useState(false);
  const live = analysis.status === "queued" || analysis.status === "running";
  const entries = countEntries(analysis);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <button
        onClick={() => setOpen((o) => !o)}
        className="fixed right-0 top-1/3 z-40 flex flex-col items-center gap-1.5 rounded-l-xl border border-r-0 border-line bg-surface-1 px-2 py-3 shadow-lg hover:bg-surface"
        aria-expanded={open}
        aria-controls="counts-drawer"
        title="Show vehicle counts"
      >
        <svg viewBox="0 0 24 24" className="h-5 w-5 text-accent" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
          <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" strokeLinecap="round" />
        </svg>
        <span className="text-[11px] font-semibold [writing-mode:vertical-rl]">Counts</span>
        {live && <span className="h-2 w-2 animate-pulse rounded-full bg-accent" aria-label="live" />}
      </button>

      <div
        className={`fixed inset-0 z-40 bg-black/20 transition-opacity ${open ? "opacity-100" : "pointer-events-none opacity-0"}`}
        onClick={() => setOpen(false)}
      />
      <aside
        id="counts-drawer"
        aria-label="Vehicle counts"
        className={`fixed right-0 top-0 z-50 flex h-full w-[22rem] max-w-[90vw] flex-col border-l border-line bg-surface-1 shadow-2xl transition-transform duration-200 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <header className="flex items-center justify-between border-b border-line px-4 py-3">
          <div>
            <h2 className="font-semibold">{live ? "Live counts" : "Vehicle counts"}</h2>
            <p className="text-xs text-ink-3">
              {live ? "Updating as the video is processed (provisional)" : analysis.status === "completed" ? "Final results" : analysis.status}
            </p>
          </div>
          <button className="btn px-2 py-1" onClick={() => setOpen(false)} aria-label="Close">✕</button>
        </header>
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {entries.map((e) => {
            const types = VEHICLE_TYPES.filter((t) => e.by_type[t]);
            const max = Math.max(1, ...types.map((t) => e.by_type[t]));
            const rank = (d: string) => (DIRECTION_ORDER.includes(d) ? DIRECTION_ORDER.indexOf(d) : 99);
            const dirs = Object.keys(e.by_direction).sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
            return (
              <section key={e.id} className="rounded-lg border border-line" style={{ borderLeft: `5px solid ${e.color}` }}>
                <div className="flex items-baseline justify-between gap-2 px-3 pt-2">
                  <h3 className="truncate text-sm font-semibold" title={e.name}>
                    {e.name}
                    {e.kind === "line" && <span className="ml-1 text-xs font-normal text-ink-3">(line)</span>}
                  </h3>
                  <span className="text-2xl font-semibold tabular-nums">{e.total}</span>
                </div>
                <div className="space-y-1 px-3 py-2">
                  {types.length === 0 && <p className="text-xs text-ink-3">No vehicles yet</p>}
                  {types.map((t) => (
                    <div key={t} className="grid grid-cols-[6.5rem_1fr_2rem] items-center gap-2 text-xs">
                      <span className="inline-flex items-center gap-1.5 text-ink-2">
                        <span className="h-2 w-2 rounded-sm" style={{ background: vehicleColor(t) }} />
                        {VEHICLE_LABELS[t] ?? t}
                      </span>
                      <span className="h-1.5 rounded-r" style={{ width: `${(e.by_type[t] / max) * 100}%`, background: vehicleColor(t) }} />
                      <span className="text-right font-medium tabular-nums">{e.by_type[t]}</span>
                    </div>
                  ))}
                </div>
                {dirs.length > 0 && (
                  <div className="flex flex-wrap gap-1 border-t border-line px-3 py-2">
                    {dirs.map((d) => (
                      <span key={d} className="rounded bg-surface px-1.5 py-0.5 text-[11px] text-ink-2">
                        {e.kind === "area" ? directionLabel(d) : d} <b className="tabular-nums">{e.by_direction[d]}</b>
                      </span>
                    ))}
                  </div>
                )}
              </section>
            );
          })}
        </div>
      </aside>
    </>
  );
}
