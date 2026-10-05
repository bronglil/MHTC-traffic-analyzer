"""Turn raw count records into summary tables (by area / type / direction / time)."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from typing import Any


def _bin_label(seconds: float, bin_seconds: int) -> tuple[int, str]:
    start = int(seconds // bin_seconds) * bin_seconds
    end = start + bin_seconds

    def fmt(s: int) -> str:
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}"

    return start, f"{fmt(start)}–{fmt(end)}"


def summarize(
    zone_counts: Iterable[Mapping[str, Any]],
    line_crossings: Iterable[Mapping[str, Any]],
    time_bin_seconds: int = 60,
    movements: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build the results summary.

    Each zone count / line crossing is a mapping with at least ``vehicle_type``,
    ``direction`` and either (``zone_id``, ``zone_name``, ``first_time``) or
    (``line_id``, ``line_name``, ``time``).
    """
    zone_counts = list(zone_counts)
    line_crossings = list(line_crossings)
    bin_s = max(1, int(time_bin_seconds))

    areas: dict[str, dict[str, Any]] = {}
    for c in zone_counts:
        a = areas.setdefault(
            c["zone_id"],
            {"id": c["zone_id"], "name": c["zone_name"], "total": 0, "by_type": Counter(), "by_direction": Counter(),
             "by_direction_type": defaultdict(Counter)},
        )
        a["by_direction_type"][c["direction"]][c["vehicle_type"]] += 1
        a["total"] += 1
        a["by_type"][c["vehicle_type"]] += 1
        a["by_direction"][c["direction"]] += 1

    lines: dict[str, dict[str, Any]] = {}
    for lc in line_crossings:
        ln = lines.setdefault(
            lc["line_id"],
            {"id": lc["line_id"], "name": lc["line_name"], "total": 0, "by_type": Counter(), "by_direction": Counter(),
             "by_direction_type": defaultdict(Counter)},
        )
        ln["by_direction_type"][lc["direction"]][lc["vehicle_type"]] += 1
        ln["total"] += 1
        ln["by_type"][lc["vehicle_type"]] += 1
        ln["by_direction"][lc["direction"]] += 1

    # Flat breakdown rows convenient for tables and spreadsheets.
    by_area_type: Counter[tuple[str, str]] = Counter()
    by_area_direction: Counter[tuple[str, str]] = Counter()
    time_rows: dict[tuple[str, int], dict[str, Any]] = {}
    for c in zone_counts:
        by_area_type[(c["zone_name"], c["vehicle_type"])] += 1
        by_area_direction[(c["zone_name"], c["direction"])] += 1
        start, label = _bin_label(float(c["first_time"]), bin_s)
        row = time_rows.setdefault(
            (c["zone_id"], start),
            {"source": "area", "name": c["zone_name"], "period_start": start, "period": label, "total": 0,
             "by_type": defaultdict(int)},
        )
        row["total"] += 1
        row["by_type"][c["vehicle_type"]] += 1
    for lc in line_crossings:
        start, label = _bin_label(float(lc["time"]), bin_s)
        row = time_rows.setdefault(
            (lc["line_id"], start),
            {"source": "line", "name": lc["line_name"], "period_start": start, "period": label, "total": 0,
             "by_type": defaultdict(int)},
        )
        row["total"] += 1
        row["by_type"][lc["vehicle_type"]] += 1

    def plain(d: dict[str, Any]) -> dict[str, Any]:
        out = {**d, "by_type": dict(d["by_type"])}
        if "by_direction" in d:
            out["by_direction"] = dict(d["by_direction"])
        if "by_direction_type" in d:
            out["by_direction_type"] = {k: dict(v) for k, v in d["by_direction_type"].items()}
        return out

    # Origin -> destination movements (e.g. junction turning counts).
    mv: dict[tuple[str, str], dict[str, Any]] = {}
    for m in movements:
        row = mv.setdefault((m["from_name"], m["to_name"]),
                            {"from": m["from_name"], "to": m["to_name"], "total": 0, "by_type": Counter()})
        row["total"] += 1
        row["by_type"][m["vehicle_type"]] += 1
        start, label = _bin_label(float(m["start_time"]), bin_s)
        trow = time_rows.setdefault(
            (f"mv:{m['from_name']}>{m['to_name']}", start),
            {"source": "movement", "name": f"{m['from_name']} → {m['to_name']}", "period_start": start,
             "period": label, "total": 0, "by_type": defaultdict(int)},
        )
        trow["total"] += 1
        trow["by_type"][m["vehicle_type"]] += 1

    return {
        "time_bin_seconds": bin_s,
        "movements": [plain(r) for r in sorted(mv.values(), key=lambda r: (r["from"], r["to"]))],
        "areas": [plain(a) for a in areas.values()],
        "lines": [plain(ln) for ln in lines.values()],
        "by_area_type": [{"area": a, "vehicle_type": t, "count": n} for (a, t), n in sorted(by_area_type.items())],
        "by_area_direction": [
            {"area": a, "direction": d, "count": n} for (a, d), n in sorted(by_area_direction.items())
        ],
        "by_time": [
            plain(r) for r in sorted(time_rows.values(), key=lambda r: (r["source"], r["name"], r["period_start"]))
        ],
    }
