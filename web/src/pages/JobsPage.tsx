import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Job, JobDetail, JobStatus, Page, Queue } from "../api/types";
import { useProject } from "../project/ProjectContext";
import {
  EmptyNote,
  ErrorNote,
  Spinner,
  StatusChip,
  fmtMs,
  timeAgo,
} from "../components/ui";

const STATUSES: JobStatus[] = [
  "scheduled",
  "queued",
  "claimed",
  "running",
  "completed",
  "failed",
  "dead",
  "cancelled",
];
const PAGE_SIZE = 25;

export default function JobsPage() {
  const { selectedId } = useProject();
  const [status, setStatus] = useState<string>("");
  const [queueId, setQueueId] = useState<string>("");
  const [type, setType] = useState<string>("");
  const [offset, setOffset] = useState(0);
  const [openJob, setOpenJob] = useState<number | null>(null);

  const queues = useQuery({
    queryKey: ["queues", selectedId],
    queryFn: () =>
      api.get<Page<Queue>>(`/api/v1/projects/${selectedId}/queues?limit=200`),
    enabled: !!selectedId,
  });

  const params = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String(offset),
  });
  if (status) params.set("status", status);
  if (queueId) params.set("queue_id", queueId);
  if (type) params.set("type", type);

  const jobs = useQuery({
    queryKey: ["jobs", params.toString()],
    queryFn: () => api.get<Page<Job>>(`/api/v1/jobs?${params.toString()}`),
    refetchInterval: 5000,
  });

  return (
    <div>
      <h1 className="mb-4 text-lg font-semibold">Jobs</h1>

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Filter label="Status">
          <select
            className="input w-36"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">All</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </Filter>
        <Filter label="Queue">
          <select
            className="input w-40"
            value={queueId}
            onChange={(e) => {
              setQueueId(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">All</option>
            {queues.data?.items.map((q) => (
              <option key={q.id} value={q.id}>
                {q.name}
              </option>
            ))}
          </select>
        </Filter>
        <Filter label="Type">
          <input
            className="input w-40"
            value={type}
            placeholder="e.g. demo.sleep"
            onChange={(e) => {
              setType(e.target.value);
              setOffset(0);
            }}
          />
        </Filter>
      </div>

      {jobs.isLoading ? (
        <Spinner />
      ) : jobs.error ? (
        <ErrorNote error={jobs.error} />
      ) : !jobs.data || jobs.data.items.length === 0 ? (
        <EmptyNote>No jobs match these filters.</EmptyNote>
      ) : (
        <>
          <div className="card overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-edge/40 text-left text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th className="px-4 py-2">ID</th>
                  <th className="px-4 py-2">Type</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2">Attempts</th>
                  <th className="px-4 py-2">Priority</th>
                  <th className="px-4 py-2">Created</th>
                </tr>
              </thead>
              <tbody>
                {jobs.data.items.map((j) => (
                  <tr
                    key={j.id}
                    className="cursor-pointer border-t border-edge hover:bg-edge/30"
                    onClick={() => setOpenJob(j.id)}
                  >
                    <td className="px-4 py-2 font-mono text-xs">{j.id}</td>
                    <td className="px-4 py-2">{j.type}</td>
                    <td className="px-4 py-2">
                      <StatusChip status={j.status} />
                    </td>
                    <td className="px-4 py-2">
                      {j.attempts}/{j.max_attempts}
                    </td>
                    <td className="px-4 py-2">{j.priority}</td>
                    <td className="px-4 py-2 text-muted">{timeAgo(j.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <Pager
            total={jobs.data.total}
            offset={offset}
            onPrev={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            onNext={() => setOffset(offset + PAGE_SIZE)}
          />
        </>
      )}

      {openJob !== null ? (
        <JobDrawer jobId={openJob} onClose={() => setOpenJob(null)} />
      ) : null}
    </div>
  );
}

function Filter({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="label">{label}</div>
      {children}
    </div>
  );
}

function Pager({
  total,
  offset,
  onPrev,
  onNext,
}: {
  total: number;
  offset: number;
  onPrev: () => void;
  onNext: () => void;
}) {
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE_SIZE, total);
  return (
    <div className="mt-3 flex items-center justify-between text-sm text-muted">
      <span>
        {from}–{to} of {total}
      </span>
      <div className="flex gap-2">
        <button className="btn-ghost" disabled={offset === 0} onClick={onPrev}>
          Prev
        </button>
        <button className="btn-ghost" disabled={to >= total} onClick={onNext}>
          Next
        </button>
      </div>
    </div>
  );
}

function JobDrawer({ jobId, onClose }: { jobId: number; onClose: () => void }) {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.get<JobDetail>(`/api/v1/jobs/${jobId}`),
    refetchInterval: 3000,
  });

  const cancel = useMutation({
    mutationFn: () => api.post(`/api/v1/jobs/${jobId}/cancel`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["job", jobId] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  const canCancel =
    data && ["scheduled", "queued", "claimed"].includes(data.status);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <div
        className="h-full w-full max-w-xl overflow-auto border-l border-edge bg-panel p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold">Job #{jobId}</h2>
          <button className="text-muted hover:text-white" onClick={onClose}>
            ✕
          </button>
        </div>

        {isLoading ? (
          <Spinner />
        ) : error ? (
          <ErrorNote error={error} />
        ) : data ? (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <StatusChip status={data.status} />
              <span className="text-muted">{data.type}</span>
              <span className="text-muted">
                attempts {data.attempts}/{data.max_attempts}
              </span>
              {canCancel ? (
                <button
                  className="btn-ghost ml-auto text-red-300"
                  onClick={() => cancel.mutate()}
                  disabled={cancel.isPending}
                >
                  Cancel
                </button>
              ) : null}
            </div>

            {data.last_error ? (
              <ErrorNote error={new Error(data.last_error)} />
            ) : null}

            <Section title="Payload">
              <pre className="overflow-auto rounded-md bg-surface p-3 text-xs text-slate-300">
                {JSON.stringify(data.payload, null, 2)}
              </pre>
            </Section>

            <Section title={`Executions (${data.executions.length})`}>
              {data.executions.length === 0 ? (
                <EmptyNote>No attempts yet.</EmptyNote>
              ) : (
                <div className="space-y-2">
                  {data.executions.map((ex) => (
                    <div
                      key={ex.id}
                      className="flex items-center justify-between rounded-md border border-edge px-3 py-2 text-sm"
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-muted">#{ex.attempt}</span>
                        <StatusChip status={ex.status} />
                        {ex.error ? (
                          <span className="text-xs text-red-300">{ex.error}</span>
                        ) : null}
                      </div>
                      <span className="text-xs text-muted">
                        {fmtMs(ex.duration_ms)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </Section>

            <Section title={`Logs (${data.logs.length})`}>
              <div className="max-h-64 space-y-1 overflow-auto rounded-md bg-surface p-3 font-mono text-xs">
                {data.logs.map((log) => (
                  <div key={log.id} className="text-slate-300">
                    <span className="text-muted">{timeAgo(log.created_at)} </span>
                    <span
                      className={
                        log.level === "error"
                          ? "text-red-300"
                          : log.level === "warning"
                            ? "text-amber-300"
                            : "text-slate-400"
                      }
                    >
                      [{log.level}]
                    </span>{" "}
                    {log.message}
                  </div>
                ))}
              </div>
            </Section>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">
        {title}
      </div>
      {children}
    </div>
  );
}
