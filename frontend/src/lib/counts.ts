import { WHOLE_FRAME_ID, type Analysis } from "./api";
import { WHOLE_FRAME_COLOR, regionColor } from "./vehicles";

export interface CountEntry {
  id: string;
  name: string;
  kind: "area" | "line";
  color: string;
  total: number;
  by_type: Record<string, number>;
  by_direction: Record<string, number>;
}

/**
 * Per road/area/line counts for display: live (incl. vehicles still in view)
 * while running, final from the summary once completed. Every configured road
 * is listed, even with zero vehicles, in the order it was drawn.
 */
export function countEntries(a: Analysis): CountEntry[] {
  const regions = a.config.regions ?? [];
  const polygons = regions.filter((r) => r.kind === "polygon");
  const wholeFrame = a.config.include_whole_frame || polygons.length === 0;
  const defs: Omit<CountEntry, "total" | "by_type" | "by_direction">[] = [
    ...(wholeFrame ? [{ id: WHOLE_FRAME_ID, name: "Whole Frame", kind: "area" as const, color: WHOLE_FRAME_COLOR }] : []),
    ...regions.map((r, i) => ({
      id: r.id,
      name: r.name,
      kind: r.kind === "polygon" ? ("area" as const) : ("line" as const),
      color: r.color || regionColor(i),
    })),
  ];
  const final = a.status === "completed" && a.summary;
  const source: Record<string, { total: number; by_type: Record<string, number>; by_direction: Record<string, number> }> =
    {};
  if (final) {
    for (const b of [...a.summary!.areas, ...a.summary!.lines]) source[b.id] = b;
  } else {
    Object.assign(source, a.live_breakdown ?? {});
  }
  return defs.map((d) => ({
    ...d,
    total: source[d.id]?.total ?? 0,
    by_type: source[d.id]?.by_type ?? {},
    by_direction: source[d.id]?.by_direction ?? {},
  }));
}
