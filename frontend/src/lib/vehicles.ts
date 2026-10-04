export const VEHICLE_TYPES = ["car", "lgv1", "lgv2", "truck", "bus", "motorcycle", "bicycle"] as const;

export const VEHICLE_LABELS: Record<string, string> = {
  car: "Car",
  lgv1: "LGV1",
  lgv2: "LGV2",
  truck: "Truck / HGV",
  bus: "Bus / Coach",
  motorcycle: "Motorcycle",
  bicycle: "Bicycle",
};

export const VEHICLE_HINTS: Record<string, string> = {
  lgv1: "Small car-derived vans (e.g. Transit Connect, Caddy, Berlingo)",
  lgv2: "Large vans up to 3.5 t (e.g. Transit, Sprinter, Crafter, Luton)",
  truck: "Goods vehicles over 3.5 t",
};

/** Colour follows the vehicle type (fixed slot), never its rank in a chart. */
export function vehicleColor(type: string): string {
  const i = VEHICLE_TYPES.indexOf(type as (typeof VEHICLE_TYPES)[number]);
  return i >= 0 ? `var(--series-${i + 1})` : "var(--text-muted)";
}

export const DIRECTION_ORDER = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "stationary"];

export function directionLabel(d: string): string {
  const names: Record<string, string> = {
    N: "↑ N", NE: "↗ NE", E: "→ E", SE: "↘ SE", S: "↓ S", SW: "↙ SW", W: "← W", NW: "↖ NW", stationary: "• Stationary",
  };
  return names[d] ?? d;
}

/** Distinct colours for user-drawn roads/areas/lines — same list and order as backend app/colors.py. */
export const REGION_COLORS = ["#f59e0b", "#06b6d4", "#a855f7", "#84cc16", "#ec4899", "#3b82f6", "#ef4444", "#14b8a6"];
export const WHOLE_FRAME_COLOR = "#9ca3af";
export function regionColor(index: number): string {
  return REGION_COLORS[index % REGION_COLORS.length];
}
