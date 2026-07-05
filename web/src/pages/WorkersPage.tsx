import { useQuery } from "@tanstack/react-query";
import { Line, LineChart, ResponsiveContainer } from "recharts";
import { api } from "../api/client";
import type { Page, Worker, WorkerHeartbeat } from "../api/types";
import { EmptyNote, ErrorNote, Spinner, StatusChip, timeAgo } from "../components/ui";

export default function WorkersPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["workers"],
    queryFn: () => api.get<Page<Worker>>("/api/v1/workers?limit=200"),
    refetchInterval: 5000,
  });

  return (
    <div>
      <h1 className="mb-4 text-lg font-semibold">Workers</h1>
      {isLoading ? (
        <Spinner />
      ) : error ? (
        <ErrorNote error={error} />
      ) : !data || data.items.length === 0 ? (
        <EmptyNote>No workers have registered. Start one with `python -m worker.main`.</EmptyNote>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-edge/40 text-left text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="px-4 py-2">Name</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Concurrency</th>
                <th className="px-4 py-2">Last heartbeat</th>
                <th className="px-4 py-2">In-flight</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((w) => (
                <WorkerRow key={w.id} worker={w} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function WorkerRow({ worker }: { worker: Worker }) {
  const { data } = useQuery({
    queryKey: ["heartbeats", worker.id],
    queryFn: () =>
      api.get<Page<WorkerHeartbeat>>(
        `/api/v1/workers/${worker.id}/heartbeats?limit=30`,
      ),
    refetchInterval: 5000,
  });

  const series = (data?.items ?? [])
    .slice()
    .reverse()
    .map((hb) => ({ in_flight: hb.in_flight }));
  const current = series.length ? series[series.length - 1].in_flight : 0;

  return (
    <tr className="border-t border-edge">
      <td className="px-4 py-2 font-mono text-xs">{worker.name}</td>
      <td className="px-4 py-2">
        <StatusChip status={worker.status} />
      </td>
      <td className="px-4 py-2">{worker.concurrency ?? "—"}</td>
      <td className="px-4 py-2 text-muted">{timeAgo(worker.last_heartbeat_at)}</td>
      <td className="px-4 py-2">
        <div className="flex items-center gap-2">
          <span className="w-6 font-semibold text-amber-300">{current}</span>
          <div className="h-8 w-28">
            {series.length > 1 ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={series}>
                  <Line
                    type="monotone"
                    dataKey="in_flight"
                    stroke="#f59e0b"
                    strokeWidth={1.5}
                    dot={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            ) : null}
          </div>
        </div>
      </td>
    </tr>
  );
}
