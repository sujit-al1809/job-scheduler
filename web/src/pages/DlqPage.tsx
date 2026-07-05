import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { DeadLetterJob, Page } from "../api/types";
import { useProject } from "../project/ProjectContext";
import { EmptyNote, ErrorNote, Spinner, timeAgo } from "../components/ui";

export default function DlqPage() {
  const { selectedId } = useProject();
  const qc = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["dlq", selectedId],
    queryFn: () =>
      api.get<Page<DeadLetterJob>>(
        `/api/v1/projects/${selectedId}/dlq?limit=200`,
      ),
    enabled: !!selectedId,
    refetchInterval: 5000,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["dlq", selectedId] });
    qc.invalidateQueries({ queryKey: ["jobs"] });
  };

  const retry = useMutation({
    mutationFn: (dlqId: number) => api.post(`/api/v1/dlq/${dlqId}/retry`),
    onSuccess: invalidate,
  });
  const discard = useMutation({
    mutationFn: (dlqId: number) => api.del(`/api/v1/dlq/${dlqId}`),
    onSuccess: invalidate,
  });

  if (!selectedId) return <EmptyNote>Select a project.</EmptyNote>;

  return (
    <div>
      <h1 className="mb-4 text-lg font-semibold">Dead Letter Queue</h1>
      {isLoading ? (
        <Spinner />
      ) : error ? (
        <ErrorNote error={error} />
      ) : !data || data.items.length === 0 ? (
        <EmptyNote>No dead-letter jobs. Nothing has exhausted its retries.</EmptyNote>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-edge/40 text-left text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="px-4 py-2">Job</th>
                <th className="px-4 py-2">Type</th>
                <th className="px-4 py-2">Attempts</th>
                <th className="px-4 py-2">Final error</th>
                <th className="px-4 py-2">Moved</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {data.items.map((e) => (
                <tr key={e.id} className="border-t border-edge">
                  <td className="px-4 py-2 font-mono text-xs">#{e.job_id}</td>
                  <td className="px-4 py-2">{e.type}</td>
                  <td className="px-4 py-2">{e.attempts}</td>
                  <td className="max-w-xs truncate px-4 py-2 text-red-300">
                    {e.final_error ?? "—"}
                  </td>
                  <td className="px-4 py-2 text-muted">{timeAgo(e.moved_at)}</td>
                  <td className="px-4 py-2">
                    <div className="flex justify-end gap-2">
                      <button
                        className="btn-ghost"
                        onClick={() => retry.mutate(e.id)}
                        disabled={retry.isPending}
                      >
                        Retry
                      </button>
                      <button
                        className="btn-ghost text-red-300"
                        onClick={() => {
                          if (confirm("Discard this dead-letter job?"))
                            discard.mutate(e.id);
                        }}
                        disabled={discard.isPending}
                      >
                        Discard
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
