import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import SettingsForm, { DEFAULT_SETTINGS, defaultTimeBin, settingsInvalid } from "../components/SettingsForm";
import { api, formatDuration, type AnalysisSettings, type Meta, type VideoListItem } from "../lib/api";

/** Choose settings once and queue every selected video; each keeps its own areas. */
export default function BatchNewPage() {
  const [params] = useSearchParams();
  const ids = (params.get("videos") ?? "").split(",").filter(Boolean);
  const navigate = useNavigate();
  const [videos, setVideos] = useState<VideoListItem[] | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [name, setName] = useState("");
  // Resolution and tile scanning are picked per video from its size.
  const [settings, setSettings] = useState<AnalysisSettings>({ ...DEFAULT_SETTINGS, image_size: null, sliced_detection: null });
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.listVideos().then((all) => {
      const byId = new Map(all.map((v) => [v.id, v]));
      const chosen = ids.map((id) => byId.get(id)).filter((v): v is VideoListItem => !!v);
      setVideos(chosen);
      const longest = Math.max(0, ...chosen.map((v) => v.duration_seconds));
      setSettings((s) => ({ ...s, time_bin_seconds: defaultTimeBin(longest) }));
    }).catch((e) => setError(e.message));
    api.meta().then(setMeta).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  if (!videos) return <p className="text-sm text-ink-3">{error ?? "Loading…"}</p>;
  if (videos.length === 0) return <p className="text-sm text-ink-2">No videos selected. <Link className="underline" to="/">Back to videos</Link></p>;

  const total = videos.reduce((s, v) => s + v.duration_seconds, 0);
  const withoutAreas = videos.filter((v) => v.area_count + v.line_count === 0).length;
  const invalid = settingsInvalid(settings);

  const run = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const b = await api.createBatch(videos.map((v) => v.id), settings, name.trim() || undefined);
      navigate(`/batches/${b.id}`);
    } catch (e) {
      setError((e as Error).message);
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <Link to="/" className="text-sm text-ink-3 hover:underline">← Videos</Link>
        <h1 className="text-lg font-semibold">Run {videos.length} video{videos.length === 1 ? "" : "s"} as a batch</h1>
        <p className="text-xs text-ink-3">
          {formatDuration(total)} of video in total. Videos are analysed one after another in this order, each with its
          own areas and lines and its own report.
        </p>
      </div>
      {error && <div className="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <section className="card overflow-x-auto p-4">
          <h2 className="mb-2 font-semibold">Videos</h2>
          {withoutAreas > 0 && (
            <p className="mb-2 text-xs text-ink-3">
              {withoutAreas} video{withoutAreas === 1 ? " has" : "s have"} no areas drawn: the whole frame is counted.
            </p>
          )}
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-ink-3">
                <th className="py-1.5 pr-2 font-medium">#</th>
                <th className="py-1.5 pr-2 font-medium">Video</th>
                <th className="py-1.5 pr-2 font-medium">Length</th>
                <th className="py-1.5 pr-2 font-medium">Counts</th>
                <th className="py-1.5 font-medium" />
              </tr>
            </thead>
            <tbody>
              {videos.map((v, i) => (
                <tr key={v.id} className="border-b border-line last:border-0">
                  <td className="py-1.5 pr-2 tabular-nums text-ink-3">{i + 1}</td>
                  <td className="max-w-[18rem] truncate py-1.5 pr-2" title={v.original_name}>{v.original_name}</td>
                  <td className="py-1.5 pr-2 tabular-nums">{formatDuration(v.duration_seconds)}</td>
                  <td className="py-1.5 pr-2 text-xs">
                    {v.region_names.length ? v.region_names.join(", ") : <span className="text-ink-3">Whole frame</span>}
                  </td>
                  <td className="py-1.5 text-right">
                    <Link className="text-xs underline" to={`/videos/${v.id}`}>Draw areas</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <aside className="card space-y-3 p-4">
          <label className="block space-y-1">
            <span className="label">Batch name</span>
            <input className="input" placeholder={`Batch of ${videos.length} videos`} value={name}
              onChange={(e) => setName(e.target.value)} />
          </label>
          <SettingsForm settings={settings} setSettings={setSettings} meta={meta} />
          <button className="btn btn-primary w-full py-2" disabled={submitting || !!invalid} onClick={run}>
            {submitting ? "Queuing…" : `Run batch (${videos.length} video${videos.length === 1 ? "" : "s"})`}
          </button>
          {invalid && <p className="text-xs text-red-600">{invalid}</p>}
        </aside>
      </div>
    </div>
  );
}
