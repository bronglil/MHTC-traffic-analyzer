import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { Analysis } from "../api";
import { countEntries } from "../counts";
import { REGION_COLORS, WHOLE_FRAME_COLOR, regionColor, vehicleColor } from "../vehicles";

function analysis(over: Partial<Analysis> = {}, cfg: Partial<Analysis["config"]> = {}): Analysis {
  return {
    id: "a1",
    video_id: "v1",
    status: "running",
    progress: 0.5,
    message: null,
    config: {
      vehicle_types: ["car", "bus"],
      include_whole_frame: false,
      detector: "yolo",
      tracker: "bytetrack",
      classification: "size",
      confidence: 0.3,
      frame_stride: 1,
      min_seconds_in_zone: 0.3,
      anchor: "bottom_center",
      time_bin_seconds: 60,
      generate_annotated_video: false,
      annotated_video_layout: "overlay",
      regions: [
        { id: "n", name: "North Road", kind: "polygon", points: [], color: "#f59e0b" },
        { id: "e", name: "East Road", kind: "polygon", points: [], color: "#06b6d4" },
        { id: "g", name: "Gate", kind: "line", points: [], color: null },
      ],
      ...cfg,
    },
    live_counts: {},
    live_breakdown: {
      n: { total: 2, by_type: { car: 2 }, by_direction: { S: 1, N: 1 } },
      g: { total: 1, by_type: { bus: 1 }, by_direction: { eastbound: 1 } },
      // movement keys are not roads and must not appear in the list
      "mv:n>e": { total: 1, by_type: { car: 1 }, by_direction: {} },
    },
    frames_processed: 10,
    has_annotated_video: false,
    created_at: "2026-10-05T00:00:00Z",
    started_at: null,
    finished_at: null,
    ...over,
  };
}

describe("countEntries", () => {
  it("lists every selected road in drawing order, with zero for roads with no vehicles yet", () => {
    const rows = countEntries(analysis());
    expect(rows.map((r) => [r.name, r.kind, r.total])).toEqual([
      ["North Road", "area", 2],
      ["East Road", "area", 0],
      ["Gate", "line", 1],
    ]);
    expect(rows[0].by_type).toEqual({ car: 2 });
    expect(rows[2].by_direction).toEqual({ eastbound: 1 });
  });

  it("uses each road's own colour, falling back to its palette slot", () => {
    const rows = countEntries(analysis());
    expect(rows.map((r) => r.color)).toEqual(["#f59e0b", "#06b6d4", regionColor(2)]);
  });

  it("omits Whole Frame when roads are selected, includes it when ticked", () => {
    expect(countEntries(analysis()).some((r) => r.id === "whole_frame")).toBe(false);
    const withWf = countEntries(analysis({}, { include_whole_frame: true }));
    expect(withWf[0]).toMatchObject({ id: "whole_frame", name: "Whole Frame", color: WHOLE_FRAME_COLOR });
  });

  it("falls back to Whole Frame when no area is drawn", () => {
    const rows = countEntries(analysis({ live_breakdown: { whole_frame: { total: 4, by_type: { car: 4 }, by_direction: {} } } },
      { regions: [] }));
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ id: "whole_frame", total: 4 });
  });

  it("switches to the final summary once completed", () => {
    const done = analysis({
      status: "completed",
      live_breakdown: {},
      summary: {
        time_bin_seconds: 60,
        areas: [{ id: "n", name: "North Road", total: 2, by_type: { car: 2 }, by_direction: { S: 2 } },
                { id: "e", name: "East Road", total: 3, by_type: { car: 2, bus: 1 }, by_direction: { E: 3 } }],
        lines: [],
        by_area_type: [], by_area_direction: [], by_time: [],
        frames_processed: 100, video_duration_seconds: 10, processing_seconds: 2,
      },
    });
    expect(countEntries(done).map((r) => [r.name, r.total])).toEqual([["North Road", 2], ["East Road", 3], ["Gate", 0]]);
    expect(countEntries(done)[1].by_type).toEqual({ car: 2, bus: 1 });
  });
});

describe("colours", () => {
  it("region palette matches the backend's (same order), so UI and video agree", () => {
    const py = readFileSync(fileURLToPath(new URL("../../../../backend/app/colors.py", import.meta.url)), "utf8");
    const backend = JSON.parse(py.match(/REGION_COLORS = (\[[^\]]+\])/)![1].replace(/'/g, '"'));
    expect(REGION_COLORS).toEqual(backend);
  });

  it("vehicle colours are fixed per type", () => {
    expect(vehicleColor("car")).toBe("var(--series-1)");
    expect(vehicleColor("lgv2")).toBe("var(--series-3)");
    expect(vehicleColor("unknown")).toBe("var(--text-muted)");
  });
});
