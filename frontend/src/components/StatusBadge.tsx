import type { AnalysisStatus } from "../lib/api";

const STYLES: Record<AnalysisStatus, { cls: string; icon: string; label: string }> = {
  queued: { cls: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300", icon: "◷", label: "Queued" },
  running: { cls: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300", icon: "◔", label: "Running" },
  completed: { cls: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300", icon: "✓", label: "Completed" },
  failed: { cls: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300", icon: "!", label: "Failed" },
  cancelled: { cls: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300", icon: "■", label: "Cancelled" },
};

export default function StatusBadge({ status, progress }: { status: AnalysisStatus; progress?: number }) {
  const s = STYLES[status];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${s.cls}`}>
      <span aria-hidden>{s.icon}</span>
      {s.label}
      {status === "running" && progress !== undefined && ` ${Math.round(progress * 100)}%`}
    </span>
  );
}
