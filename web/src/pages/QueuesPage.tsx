import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Page, Queue, QueueStats, RetryStrategy } from "../api/types";
import { useProject } from "../project/ProjectContext";
import Modal from "../components/Modal";
import { EmptyNote, ErrorNote, Spinner, fmtMs } from "../components/ui";

interface QueueForm {
  name: string;
  priority: number;
  concurrency_limit: number;
  strategy: RetryStrategy;
  base_delay_s: number;
  max_delay_s: number;
  max_attempts: number;
  jitter: boolean;
}

const DEFAULT_FORM: QueueForm = {
  name: "",
  priority: 0,
  concurrency_limit: 10,
  strategy: "exponential",
  base_delay_s: 5,
  max_delay_s: 3600,
  max_attempts: 5,
  jitter: true,
};

export default function QueuesPage() {
  const { selectedId, projects, isLoading } = useProject();
  const [modal, setModal] = useState<null | { queue?: Queue }>(null);

  if (isLoading) return <Spinner />;
  if (projects.length === 0) return <CreateFirstProject />;
  if (!selectedId) return <EmptyNote>Select a project.</EmptyNote>;

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold">Queues</h1>
        <button className="btn-primary" onClick={() => setModal({})}>
          + New queue
        </button>
      </div>
      <QueueList projectId={selectedId} onEdit={(q) => setModal({ queue: q })} />
      {modal ? (
        <QueueModal
          projectId={selectedId}
          queue={modal.queue}
          onClose={() => setModal(null)}
        />
      ) : null}
    </div>
  );
}

function QueueList({
  projectId,
  onEdit,
}: {
  projectId: number;
  onEdit: (q: Queue) => void;
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["queues", projectId],
    queryFn: () =>
      api.get<Page<Queue>>(`/api/v1/projects/${projectId}/queues?limit=200`),
  });

  if (isLoading) return <Spinner />;
  if (error) return <ErrorNote error={error} />;
  if (!data || data.items.length === 0)
    return <EmptyNote>No queues yet. Create one to start scheduling jobs.</EmptyNote>;

  return (
    <div className="space-y-3">
      {data.items.map((q) => (
        <QueueRow key={q.id} projectId={projectId} queue={q} onEdit={onEdit} />
      ))}
    </div>
  );
}

function QueueRow({
  projectId,
  queue,
  onEdit,
}: {
  projectId: number;
  queue: Queue;
  onEdit: (q: Queue) => void;
}) {
  const qc = useQueryClient();
  const { data: stats } = useQuery({
    queryKey: ["queue-stats", queue.id],
    queryFn: () =>
      api.get<QueueStats>(
        `/api/v1/projects/${projectId}/queues/${queue.id}/stats`,
      ),
    refetchInterval: 5000,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["queues", projectId] });
    qc.invalidateQueries({ queryKey: ["queue-stats", queue.id] });
  };

  const pause = useMutation({
    mutationFn: (paused: boolean) =>
      api.post(
        `/api/v1/projects/${projectId}/queues/${queue.id}/${paused ? "pause" : "resume"}`,
      ),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: () =>
      api.del(`/api/v1/projects/${projectId}/queues/${queue.id}`),
    onSuccess: invalidate,
  });

  const depth = stats?.by_status.queued ?? 0;

  return (
    <div className="card flex items-center justify-between p-4">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium">{queue.name}</span>
          {queue.is_paused ? (
            <span className="chip bg-amber-500/20 text-amber-300">paused</span>
          ) : null}
        </div>
        <div className="mt-1 text-xs text-muted">
          priority {queue.priority} · concurrency {queue.concurrency_limit} · avg{" "}
          {fmtMs(stats?.avg_duration_ms ?? null)}
        </div>
      </div>

      <div className="flex items-center gap-4">
        <div className="flex gap-3 text-center">
          <Metric label="queued" value={depth} tone="text-blue-300" />
          <Metric
            label="in-flight"
            value={stats?.in_flight ?? 0}
            tone="text-amber-300"
          />
          <Metric
            label="done"
            value={stats?.by_status.completed ?? 0}
            tone="text-emerald-300"
          />
          <Metric
            label="dead"
            value={stats?.by_status.dead ?? 0}
            tone="text-rose-300"
          />
        </div>
        <div className="flex gap-2">
          <button
            className="btn-ghost"
            onClick={() => pause.mutate(!queue.is_paused)}
          >
            {queue.is_paused ? "Resume" : "Pause"}
          </button>
          <button className="btn-ghost" onClick={() => onEdit(queue)}>
            Edit
          </button>
          <button
            className="btn-ghost text-red-300"
            onClick={() => {
              if (confirm(`Delete queue "${queue.name}"?`)) remove.mutate();
            }}
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: string;
}) {
  return (
    <div className="w-14">
      <div className={`text-lg font-semibold ${tone}`}>{value}</div>
      <div className="text-[10px] uppercase tracking-wide text-muted">{label}</div>
    </div>
  );
}

function QueueModal({
  projectId,
  queue,
  onClose,
}: {
  projectId: number;
  queue?: Queue;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [form, setForm] = useState<QueueForm>(
    queue
      ? { ...DEFAULT_FORM, name: queue.name, priority: queue.priority, concurrency_limit: queue.concurrency_limit }
      : DEFAULT_FORM,
  );
  const [error, setError] = useState<unknown>(null);

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: form.name,
        priority: form.priority,
        concurrency_limit: form.concurrency_limit,
        retry_policy: {
          strategy: form.strategy,
          base_delay_s: form.base_delay_s,
          max_delay_s: form.max_delay_s,
          max_attempts: form.max_attempts,
          jitter: form.jitter,
        },
      };
      return queue
        ? api.patch(`/api/v1/projects/${projectId}/queues/${queue.id}`, body)
        : api.post(`/api/v1/projects/${projectId}/queues`, body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["queues", projectId] });
      onClose();
    },
    onError: (e) => setError(e),
  });

  const set = <K extends keyof QueueForm>(k: K, v: QueueForm[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  return (
    <Modal title={queue ? "Edit queue" : "New queue"} onClose={onClose}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        {error ? <ErrorNote error={error} /> : null}
        <div>
          <label className="label">Name</label>
          <input
            className="input"
            value={form.name}
            onChange={(e) => set("name", e.target.value)}
            required
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <NumField label="Priority" value={form.priority} onChange={(v) => set("priority", v)} />
          <NumField label="Concurrency limit" min={1} value={form.concurrency_limit} onChange={(v) => set("concurrency_limit", v)} />
        </div>

        <div className="border-t border-edge pt-3 text-xs uppercase tracking-wide text-muted">
          Retry policy
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Strategy</label>
            <select
              className="input"
              value={form.strategy}
              onChange={(e) => set("strategy", e.target.value as RetryStrategy)}
            >
              <option value="fixed">fixed</option>
              <option value="linear">linear</option>
              <option value="exponential">exponential</option>
            </select>
          </div>
          <NumField label="Max attempts" min={1} value={form.max_attempts} onChange={(v) => set("max_attempts", v)} />
          <NumField label="Base delay (s)" min={0} value={form.base_delay_s} onChange={(v) => set("base_delay_s", v)} />
          <NumField label="Max delay (s)" min={0} value={form.max_delay_s} onChange={(v) => set("max_delay_s", v)} />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.jitter}
            onChange={(e) => set("jitter", e.target.checked)}
          />
          Apply jitter
        </label>

        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function NumField({
  label,
  value,
  onChange,
  min,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
}) {
  return (
    <div>
      <label className="label">{label}</label>
      <input
        className="input"
        type="number"
        min={min}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  );
}

function CreateFirstProject() {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [error, setError] = useState<unknown>(null);
  const create = useMutation({
    mutationFn: () => api.post("/api/v1/projects", { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
    onError: (e) => setError(e),
  });

  return (
    <div className="mx-auto max-w-md">
      <div className="card space-y-4 p-6">
        <div>
          <h1 className="text-lg font-semibold">Create your first project</h1>
          <p className="text-sm text-muted">
            Projects group your queues and jobs.
          </p>
        </div>
        {error ? <ErrorNote error={error} /> : null}
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <input
            className="input"
            placeholder="Project name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <button className="btn-primary w-full" disabled={create.isPending}>
            {create.isPending ? "Creating…" : "Create project"}
          </button>
        </form>
      </div>
    </div>
  );
}
