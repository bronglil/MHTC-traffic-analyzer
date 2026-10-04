import { useEffect, useRef, useState, type ReactNode } from "react";
import { formatDuration } from "../lib/api";

interface Props {
  src: string;
  aspect: number; // width / height
  /** Server-decoded frame at time t; used when the browser can't play the codec. */
  frameUrl?: (t: number) => string;
  knownDuration?: number;
  fps?: number;
  overlay?: (size: { width: number; height: number }) => ReactNode;
}

/**
 * HTML5 video sized to its exact aspect ratio, with an overlay layer covering
 * precisely the video picture (so normalized ROI coordinates map 1:1) and
 * custom controls underneath (native controls would sit under the overlay).
 */
export default function VideoCanvas({ src, aspect, frameUrl, knownDuration = 0, fps = 25, overlay }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [width, setWidth] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playable, setPlayable] = useState(true);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const height = aspect > 0 ? width / aspect : 0;
  const v = videoRef.current;
  const fallback = !playable && !!frameUrl;
  const total = fallback ? knownDuration : duration;

  // Fallback "playback": step through server-rendered frames a few times a second.
  useEffect(() => {
    if (!fallback || !playing) return;
    const id = setInterval(() => {
      setTime((t) => {
        if (t + 0.25 >= total) {
          setPlaying(false);
          return total;
        }
        return t + 0.25;
      });
    }, 250);
    return () => clearInterval(id);
  }, [fallback, playing, total]);

  const seek = (t: number) => {
    const clamped = Math.max(0, Math.min(total || 0, t));
    if (fallback) setTime(clamped);
    else if (v) v.currentTime = clamped;
  };
  const toggle = () => {
    if (fallback) return setPlaying((p) => !p);
    if (!v) return;
    if (v.paused) v.play();
    else v.pause();
  };
  const step = (frames: number) => {
    if (fallback) setPlaying(false);
    else v?.pause();
    seek(time + frames / fps);
  };

  return (
    <div className="space-y-2">
      <div ref={wrapRef} className="relative w-full overflow-hidden rounded-lg bg-black" style={{ height }}>
        <video
          ref={videoRef}
          src={src}
          className="absolute inset-0 h-full w-full"
          style={{ objectFit: "fill" }}
          preload="auto"
          playsInline
          muted
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
          onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
          onError={() => setPlayable(false)}
        />
        {fallback && (
          <>
            <img src={frameUrl!(Math.round(time * fps) / fps)} alt="" className="absolute inset-0 h-full w-full" draggable={false} />
            <div className="absolute inset-x-0 bottom-0 bg-black/60 px-3 py-1 text-[11px] text-white">
              Browser can’t play this codec — showing frames decoded by the server.
            </div>
          </>
        )}
        {width > 0 && overlay && <div className="absolute inset-0">{overlay({ width, height })}</div>}
      </div>
      <div className="flex items-center gap-2">
        <button className="btn w-20" onClick={toggle} aria-label={playing ? "Pause" : "Play"}>
          {playing ? "❚❚ Pause" : "▶ Play"}
        </button>
        <button className="btn px-2" onClick={() => step(-1)} title="Previous frame">‹</button>
        <button className="btn px-2" onClick={() => step(1)} title="Next frame">›</button>
        <input
          type="range"
          min={0}
          max={total || 0}
          step={0.01}
          value={time}
          onChange={(e) => seek(Number(e.target.value))}
          className="flex-1 accent-[var(--accent)]"
          aria-label="Seek"
        />
        <span className="w-24 text-right text-xs tabular-nums text-ink-2">
          {formatDuration(time)} / {formatDuration(total)}
        </span>
      </div>
    </div>
  );
}
