export type RegionKind = "polygon" | "line";
export type Point = [number, number]; // normalized 0..1

export interface Region {
  id: string;
  video_id: string;
  name: string;
  kind: RegionKind;
  points: Point[];
  color: string | null;
  label_forward: string;
  label_backward: string;
  role?: "count" | "in" | "out" | "both" | null;
  created_at: string;
}

export interface Video {
  id: string;
  original_name: string;
  size_bytes: number;
  width: number;
  height: number;
  fps: number;
  frame_count: number;
  duration_seconds: number;
  created_at: string;
}

export interface VideoDetail extends Video {
  regions: Region[];
}

export type AnalysisStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface AnalysisSettings {
  vehicle_types: string[];
  region_ids?: string[] | null;
  include_whole_frame: boolean;
  detector: "yolo" | "motion";
  model_path?: string | null;
  tracker: string;
  classification: "size" | "detector" | "classifier";
  classifier_model?: string | null;
  confidence: number;
  frame_stride: number;
  min_seconds_in_zone: number;
  anchor: "bottom_center" | "center";
  time_bin_seconds: number;
  generate_annotated_video: boolean;
  annotated_video_layout: "overlay" | "pipeline";
  count_stationary?: boolean;
  count_rule?: "crossing" | "entering" | "present";
  sliced_detection?: boolean;
  low_light?: "off" | "auto" | "on";
  footage?: "normal" | "timelapse";
  start_seconds?: number;
  end_seconds?: number | null;
  image_size?: 640 | 960 | 1280 | 1920;
}

export interface StageSnapshot {
  frame_index: number | null;
  timestamp: number | null;
  stages: { key: string; title: string; url: string; version: number }[];
  live_url: string | null;
}

export interface Breakdown {
  id: string;
  name: string;
  total: number;
  by_type: Record<string, number>;
  by_direction: Record<string, number>;
  by_direction_type?: Record<string, Record<string, number>>; // lines only
}

export interface TimeRow {
  source: "area" | "line";
  name: string;
  period_start: number;
  period: string;
  total: number;
  by_type: Record<string, number>;
}

export interface Summary {
  time_bin_seconds: number;
  areas: Breakdown[];
  lines: Breakdown[];
  by_area_type: { area: string; vehicle_type: string; count: number }[];
  by_area_direction: { area: string; direction: string; count: number }[];
  by_time: TimeRow[];
  frames_processed: number;
  video_duration_seconds: number;
  processing_seconds: number;
}

export interface LiveEntry {
  total: number;
  by_type: Record<string, number>;
  by_direction: Record<string, number>;
}

export interface Analysis {
  id: string;
  video_id: string;
  status: AnalysisStatus;
  progress: number;
  message: string | null;
  config: AnalysisSettings & { regions: Pick<Region, "id" | "name" | "kind" | "points" | "color">[] };
  live_counts: Record<string, number>;
  live_breakdown?: Record<string, LiveEntry> | null;
  frames_processed: number;
  has_annotated_video: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  summary?: Summary | null;
}

export interface Meta {
  vehicle_types: string[];
  trackers: string[];
  default_model: string;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  meta: () => request<Meta>("/api/meta"),
  listVideos: () => request<Video[]>("/api/videos"),
  getVideo: (id: string) => request<VideoDetail>(`/api/videos/${id}`),
  deleteVideo: (id: string) => request<void>(`/api/videos/${id}`, { method: "DELETE" }),
  videoUrl: (id: string) => `/api/videos/${id}/file`,
  thumbnailUrl: (id: string) => `/api/videos/${id}/thumbnail`,
  frameUrl: (id: string, t: number) => `/api/videos/${id}/frame?t=${t.toFixed(2)}`,

  uploadVideo(file: File, onProgress: (fraction: number) => void): Promise<Video> {
    // XHR rather than fetch for upload progress events.
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/videos");
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
      xhr.onload = () => {
        let body: any = null;
        try {
          body = JSON.parse(xhr.responseText);
        } catch {
          /* ignore */
        }
        if (xhr.status >= 200 && xhr.status < 300) resolve(body);
        else reject(new ApiError(xhr.status, body?.detail ?? xhr.statusText));
      };
      xhr.onerror = () => reject(new ApiError(0, "Network error during upload"));
      const form = new FormData();
      form.append("file", file);
      xhr.send(form);
    });
  },

  createRegion: (videoId: string, r: Omit<Region, "id" | "video_id" | "created_at" | "color"> & { color?: string | null }) =>
    request<Region>(`/api/videos/${videoId}/regions`, json("POST", r)),
  updateRegion: (videoId: string, id: string, r: Partial<Region>) =>
    request<Region>(`/api/videos/${videoId}/regions/${id}`, json("PATCH", r)),
  deleteRegion: (videoId: string, id: string) =>
    request<void>(`/api/videos/${videoId}/regions/${id}`, { method: "DELETE" }),

  createAnalysis: (videoId: string, s: AnalysisSettings) =>
    request<Analysis>(`/api/videos/${videoId}/analyses`, json("POST", s)),
  listAnalyses: (videoId: string) => request<Analysis[]>(`/api/videos/${videoId}/analyses`),
  getAnalysis: (id: string) => request<Analysis>(`/api/analyses/${id}`),
  stages: (id: string) => request<StageSnapshot>(`/api/analyses/${id}/stages`),
  cancelAnalysis: (id: string) => request<Analysis>(`/api/analyses/${id}/cancel`, { method: "POST" }),
  deleteAnalysis: (id: string) => request<void>(`/api/analyses/${id}`, { method: "DELETE" }),
  exportUrl: (id: string, format: "csv" | "csv_bundle" | "xlsx" | "json") => `/api/analyses/${id}/export?format=${format}`,
  annotatedVideoUrl: (id: string, download = false) =>
    `/api/analyses/${id}/annotated-video${download ? "?download=true" : ""}`,

  progressSocket(id: string): WebSocket {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    return new WebSocket(`${proto}://${location.host}/api/analyses/${id}/ws`);
  },
};

export const WHOLE_FRAME_ID = "whole_frame";

export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(1)} ${units[i]}`;
}
