import { useEffect, useMemo, useState } from "react";
import { Arrow, Circle, Group, Layer, Line, Stage, Text } from "react-konva";
import type { KonvaEventObject } from "konva/lib/Node";
import type { Point, Region, RegionKind } from "../lib/api";
import { regionColor } from "../lib/vehicles";

export type EditorMode = "select" | "rect" | RegionKind;

interface Props {
  width: number;
  height: number;
  regions: Region[];
  mode: EditorMode;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onCreate: (kind: RegionKind, points: Point[]) => void;
  onChangePoints: (id: string, points: Point[]) => void;
  onCancelDraw: () => void;
}

const CLOSE_RADIUS = 12;
const clamp = (v: number) => Math.min(1, Math.max(0, v));

/**
 * Konva overlay for drawing and editing polygon ROIs and counting lines.
 * Regions are stored normalized (0..1) so they are independent of display size.
 *
 * Rectangle: press and drag over a road. Polygon: click to add points; click the first point, double-click, or press
 * Enter to close. Line: click start and end. Esc cancels; Backspace removes the
 * last point. In select mode drag vertices or whole shapes to edit.
 */
export default function RegionEditor({
  width, height, regions, mode, selectedId, onSelect, onCreate, onChangePoints, onCancelDraw,
}: Props) {
  const [draft, setDraft] = useState<Point[]>([]);
  const [cursor, setCursor] = useState<Point | null>(null);
  // Local copy while dragging so edits feel instant; committed on drag end.
  const [dragPoints, setDragPoints] = useState<{ id: string; points: Point[] } | null>(null);
  // Rectangle being dragged out: start corner (normalized).
  const [rectStart, setRectStart] = useState<Point | null>(null);

  const toPx = (p: Point) => [p[0] * width, p[1] * height] as const;
  const toNorm = (x: number, y: number): Point => [clamp(x / width), clamp(y / height)];

  useEffect(() => {
    setDraft([]);
    setRectStart(null);
  }, [mode]);

  const pointer = (e: KonvaEventObject<Event>): Point | null => {
    const pos = e.target.getStage()?.getPointerPosition();
    return pos ? toNorm(pos.x, pos.y) : null;
  };
  const rectDown = (e: KonvaEventObject<MouseEvent | TouchEvent>) => {
    if (mode !== "rect") return;
    const p = pointer(e);
    if (p) {
      setRectStart(p);
      setCursor(p);
    }
  };
  const rectUp = (e: KonvaEventObject<MouseEvent | TouchEvent>) => {
    if (mode !== "rect" || !rectStart) return;
    const end = pointer(e) ?? cursor;
    setRectStart(null);
    if (!end) return;
    const [x1, x2] = [Math.min(rectStart[0], end[0]), Math.max(rectStart[0], end[0])];
    const [y1, y2] = [Math.min(rectStart[1], end[1]), Math.max(rectStart[1], end[1])];
    // Ignore accidental clicks: need at least ~8px in both directions.
    if ((x2 - x1) * width < 8 || (y2 - y1) * height < 8) return;
    onCreate("polygon", [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]);
  };

  const finishPolygon = (pts: Point[]) => {
    if (pts.length >= 3) onCreate("polygon", pts);
    setDraft([]);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest("input, textarea, select")) return;
      if (e.key === "Escape") {
        if (draft.length) setDraft([]);
        else onCancelDraw();
      } else if (e.key === "Enter" && mode === "polygon") {
        finishPolygon(draft);
      } else if (e.key === "Backspace" && draft.length) {
        e.preventDefault();
        setDraft((d) => d.slice(0, -1));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const handleStageClick = (e: KonvaEventObject<MouseEvent | TouchEvent>) => {
    const pos = e.target.getStage()?.getPointerPosition();
    if (!pos) return;
    if (mode === "select") {
      if (e.target === e.target.getStage()) onSelect(null);
      return;
    }
    if (mode === "rect") return; // handled by mouse down / up
    const p = toNorm(pos.x, pos.y);
    if (mode === "line") {
      if (draft.length === 0) setDraft([p]);
      else {
        onCreate("line", [draft[0], p]);
        setDraft([]);
      }
      return;
    }
    // polygon: close when clicking near the first vertex
    if (draft.length >= 3) {
      const [fx, fy] = toPx(draft[0]);
      if (Math.hypot(fx - pos.x, fy - pos.y) <= CLOSE_RADIUS) {
        finishPolygon(draft);
        return;
      }
    }
    setDraft((d) => {
      // Ignore the repeated click of a double-click.
      const last = d[d.length - 1];
      if (last) {
        const [lx, ly] = toPx(last);
        if (Math.hypot(lx - pos.x, ly - pos.y) < 4) return d;
      }
      return [...d, p];
    });
  };

  // Konva fires dblclick for any two quick clicks, even far apart; only treat it
  // as "finish" when the second click landed on the last placed point.
  const handleDblClick = (e: KonvaEventObject<MouseEvent>) => {
    if (mode !== "polygon" || draft.length < 3) return;
    const pos = e.target.getStage()?.getPointerPosition();
    const [lx, ly] = toPx(draft[draft.length - 1]);
    if (pos && Math.hypot(lx - pos.x, ly - pos.y) < 6) finishPolygon(draft);
  };

  const handleMove = (e: KonvaEventObject<MouseEvent>) => {
    if (mode === "select") return;
    const pos = e.target.getStage()?.getPointerPosition();
    if (pos) setCursor(toNorm(pos.x, pos.y));
  };

  const shapes = useMemo(
    () =>
      regions.map((r, i) => ({
        region: r,
        color: r.color || regionColor(i),
        points: dragPoints?.id === r.id ? dragPoints.points : r.points,
      })),
    [regions, dragPoints],
  );

  const drawing = mode !== "select";

  return (
    <Stage
      width={width}
      height={height}
      onClick={handleStageClick}
      onTap={handleStageClick}
      onDblClick={handleDblClick}
      onMouseMove={handleMove}
      onTouchMove={handleMove as never}
      onMouseDown={rectDown}
      onTouchStart={rectDown}
      onMouseUp={rectUp}
      onTouchEnd={rectUp}
      onMouseLeave={(e) => {
        if (rectStart) rectUp(e);
        setCursor(null);
      }}
      style={{ cursor: drawing ? "crosshair" : "default" }}
    >
      <Layer>
        {shapes.map(({ region, color, points }) => {
          const flat = points.flatMap((p) => toPx(p));
          const selected = region.id === selectedId;
          const select = (e: KonvaEventObject<Event>) => {
            if (drawing) return;
            e.cancelBubble = true;
            onSelect(region.id);
          };
          const [lx, ly] = toPx(points[0]);
          return (
            <Group
              key={region.id}
              draggable={selected && !drawing}
              onDragEnd={(e) => {
                // Vertex handle drags bubble up here too; only handle whole-shape drags.
                if (e.target !== e.currentTarget) return;
                const dx = e.target.x() / width;
                const dy = e.target.y() / height;
                e.target.position({ x: 0, y: 0 });
                onChangePoints(region.id, points.map(([x, y]) => [clamp(x + dx), clamp(y + dy)] as Point));
              }}
            >
              <Line
                points={flat}
                closed={region.kind === "polygon"}
                fill={region.kind === "polygon" ? color + (selected ? "40" : "26") : undefined}
                stroke={color}
                strokeWidth={selected ? 3 : 2}
                hitStrokeWidth={14}
                listening={!drawing}
                onClick={select}
                onTap={select}
              />
              {region.kind === "line" && <DirectionArrow points={points.map(toPx) as [number, number][]} color={color}
                label={region.label_forward} />}
              <Text x={lx + 6} y={ly + 6} text={region.name} fontSize={13} fontStyle="bold" fill="#fff"
                shadowColor="#000" shadowBlur={4} shadowOpacity={0.9} listening={false} />
              {selected && !drawing &&
                points.map((p, idx) => {
                  const [x, y] = toPx(p);
                  return (
                    <Circle
                      key={idx}
                      x={x}
                      y={y}
                      radius={6}
                      fill="#fff"
                      stroke={color}
                      strokeWidth={2}
                      draggable
                      onDragMove={(e) => {
                        e.cancelBubble = true;
                        const next = [...points];
                        next[idx] = toNorm(e.target.x(), e.target.y());
                        setDragPoints({ id: region.id, points: next });
                      }}
                      onDragEnd={(e) => {
                        e.cancelBubble = true;
                        const next = [...points];
                        next[idx] = toNorm(e.target.x(), e.target.y());
                        setDragPoints(null);
                        onChangePoints(region.id, next);
                      }}
                      onMouseEnter={(e) => {
                        const c = e.target.getStage()?.container();
                        if (c) c.style.cursor = "move";
                      }}
                      onMouseLeave={(e) => {
                        const c = e.target.getStage()?.container();
                        if (c) c.style.cursor = "default";
                      }}
                    />
                  );
                })}
            </Group>
          );
        })}

        {drawing && draft.length > 0 && (
          <Group listening={false}>
            <Line
              points={[...draft, ...(cursor ? [cursor] : [])].flatMap((p) => toPx(p))}
              stroke="#fff"
              strokeWidth={2}
              dash={[6, 4]}
              closed={false}
            />
            {draft.map((p, i) => {
              const [x, y] = toPx(p);
              return <Circle key={i} x={x} y={y} radius={i === 0 ? 7 : 4} fill={i === 0 ? "#22c55e" : "#fff"}
                stroke="#000" strokeWidth={1} />;
            })}
          </Group>
        )}

        {mode === "rect" && rectStart && cursor && (() => {
          const [ax, ay] = toPx(rectStart);
          const [bx, by] = toPx(cursor);
          return (
            <Line
              listening={false}
              points={[ax, ay, bx, ay, bx, by, ax, by]}
              closed
              stroke="#fff"
              strokeWidth={2}
              dash={[6, 4]}
              fill="rgba(255,255,255,0.15)"
            />
          );
        })()}
      </Layer>
    </Stage>
  );
}

/** Arrow perpendicular to a counting line, pointing in the "forward" crossing direction. */
function DirectionArrow({ points, color, label }: { points: [number, number][]; color: string; label: string }) {
  if (points.length < 2) return null;
  const [[ax, ay], [bx, by]] = points;
  const mx = (ax + bx) / 2;
  const my = (ay + by) / 2;
  const len = Math.hypot(bx - ax, by - ay) || 1;
  // Right-hand normal of a->b in screen space (y down) = (-dy, dx).
  const nx = -(by - ay) / len;
  const ny = (bx - ax) / len;
  const L = 28;
  return (
    <Group listening={false}>
      <Arrow points={[mx, my, mx + nx * L, my + ny * L]} stroke={color} fill={color} strokeWidth={2}
        pointerLength={8} pointerWidth={8} />
      <Text x={mx + nx * (L + 6) - 4} y={my + ny * (L + 6) - 6} text={label} fontSize={11} fill="#fff"
        shadowColor="#000" shadowBlur={3} shadowOpacity={0.9} />
      <Circle x={ax} y={ay} radius={3} fill={color} />
      <Text x={ax - 14} y={ay - 14} text="A" fontSize={11} fill="#fff" shadowColor="#000" shadowBlur={3} />
      <Text x={bx + 4} y={by + 2} text="B" fontSize={11} fill="#fff" shadowColor="#000" shadowBlur={3} />
    </Group>
  );
}
