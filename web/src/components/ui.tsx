import type { JobStatus } from "../api/types";

const STATUS_COLORS: Record<string, string> = {
  scheduled: "bg-purple-500/20 text-purple-300",
  queued: "bg-blue-500/20 text-blue-300",
  claimed: "bg-cyan-500/20 text-cyan-300",
  running: "bg-amber-500/20 text-amber-300",
  completed: "bg-emerald-500/20 text-emerald-300",
  failed: "bg-red-500/20 text-red-300",
  dead: "bg-rose-700/30 text-rose-300",
  cancelled: "bg-slate-500/20 text-slate-300",
  online: "bg-emerald-500/20 text-emerald-300",
  draining: "bg-amber-500/20 text-amber-300",
  stopped: "bg-slate-500/20 text-slate-300",
  timeout: "bg-orange-500/20 text-orange-300",
};

export function StatusChip({ status }: { status: JobStatus | string }) {
  const cls = STATUS_COLORS[status] ?? "bg-slate-500/20 text-slate-300";
  return <span className={`chip ${cls}`}>{status}</span>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-edge border-t-brand" />
      {label ?? "Loading…"}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  const message =
    error instanceof Error ? error.message : "Something went wrong.";
  return (
    <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">
      {message}
    </div>
  );
}

export function EmptyNote({ children }: { children: React.ReactNode }) {
  return <div className="py-8 text-center text-sm text-muted">{children}</div>;
}

export function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return `${Math.floor(secs)}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

export function fmtMs(ms: number | null): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}
