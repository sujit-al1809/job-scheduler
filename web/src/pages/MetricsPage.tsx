import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api/client";
import type { ProjectMetrics } from "../api/types";
import { useProject } from "../project/ProjectContext";
import { EmptyNote, ErrorNote, Spinner, fmtMs } from "../components/ui";

export default function MetricsPage() {
  const { selectedId } = useProject();
  const { data, isLoading, error } = useQuery({
    queryKey: ["metrics", selectedId],
    queryFn: () =>
      api.get<ProjectMetrics>(
        `/api/v1/projects/${selectedId}/metrics?window_minutes=60`,
      ),
    enabled: !!selectedId,
    refetchInterval: 5000,
  });

  if (!selectedId) return <EmptyNote>Select a project.</EmptyNote>;
  if (isLoading) return <Spinner />;
  if (error) return <ErrorNote error={error} />;
  if (!data) return null;

  const throughput = data.throughput_per_minute.map((b) => ({
    minute: new Date(b.minute).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    }),
    completed: b.completed,
    failed: b.failed,
  }));

  const successPct =
    data.success_rate === null ? "—" : `${(data.success_rate * 100).toFixed(1)}%`;

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold">Metrics (last {data.window_minutes}m)</h1>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Kpi label="Success rate" value={successPct} tone="text-emerald-300" />
        <Kpi label="Completed" value={String(data.total_completed)} tone="text-emerald-300" />
        <Kpi label="Failed" value={String(data.total_failed)} tone="text-red-300" />
        <Kpi label="p95 duration" value={fmtMs(data.p95_duration_ms)} tone="text-amber-300" />
      </div>

      <div className="card p-4">
        <div className="mb-3 text-sm font-medium">Throughput / minute</div>
        {throughput.length === 0 ? (
          <EmptyNote>No executions in this window yet.</EmptyNote>
        ) : (
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={throughput}>
                <CartesianGrid stroke="#232c38" strokeDasharray="3 3" />
                <XAxis dataKey="minute" stroke="#8a97a8" fontSize={11} />
                <YAxis stroke="#8a97a8" fontSize={11} allowDecimals={false} />
                <Tooltip
                  contentStyle={{
                    background: "#161d26",
                    border: "1px solid #232c38",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="completed" stroke="#34d399" dot={false} />
                <Line type="monotone" dataKey="failed" stroke="#f87171" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      <div className="card p-4">
        <div className="mb-3 text-sm font-medium">
          Queue depth (p50 latency {fmtMs(data.p50_duration_ms)})
        </div>
        {data.queue_depths.length === 0 ? (
          <EmptyNote>No queues yet.</EmptyNote>
        ) : (
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.queue_depths}>
                <CartesianGrid stroke="#232c38" strokeDasharray="3 3" />
                <XAxis dataKey="name" stroke="#8a97a8" fontSize={11} />
                <YAxis stroke="#8a97a8" fontSize={11} allowDecimals={false} />
                <Tooltip
                  contentStyle={{
                    background: "#161d26",
                    border: "1px solid #232c38",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="depth" fill="#4f9cf0" name="queued" />
                <Bar dataKey="in_flight" fill="#f59e0b" name="in-flight" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
}

function Kpi({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="card p-4">
      <div className={`text-2xl font-semibold ${tone}`}>{value}</div>
      <div className="mt-1 text-xs uppercase tracking-wide text-muted">{label}</div>
    </div>
  );
}
