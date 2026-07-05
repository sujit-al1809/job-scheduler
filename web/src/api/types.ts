export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface User {
  id: number;
  email: string;
  created_at: string;
}

export interface Project {
  id: number;
  org_id: number;
  name: string;
  api_key: string;
  created_at: string;
  updated_at: string;
}

export type RetryStrategy = "fixed" | "linear" | "exponential";

export interface Queue {
  id: number;
  project_id: number;
  name: string;
  priority: number;
  concurrency_limit: number;
  is_paused: boolean;
  retry_policy_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface QueueStats {
  queue_id: number;
  total: number;
  by_status: Record<string, number>;
  oldest_queued_age_s: number | null;
  avg_duration_ms: number | null;
  in_flight: number;
}

export type JobStatus =
  | "scheduled"
  | "queued"
  | "claimed"
  | "running"
  | "completed"
  | "failed"
  | "dead"
  | "cancelled";

export interface Job {
  id: number;
  queue_id: number;
  project_id: number;
  type: string;
  payload: Record<string, unknown>;
  status: JobStatus;
  priority: number;
  run_at: string;
  attempts: number;
  max_attempts: number;
  idempotency_key: string | null;
  worker_id: number | null;
  claimed_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobExecution {
  id: number;
  attempt: number;
  worker_id: number | null;
  status: "running" | "completed" | "failed" | "timeout";
  error: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface JobLog {
  id: number;
  execution_id: number | null;
  level: string;
  message: string;
  created_at: string;
}

export interface JobDetail extends Job {
  executions: JobExecution[];
  logs: JobLog[];
}

export type WorkerStatus = "online" | "draining" | "stopped" | "dead";

export interface Worker {
  id: number;
  name: string;
  status: WorkerStatus;
  concurrency: number | null;
  started_at: string;
  last_heartbeat_at: string;
  stopped_at: string | null;
  created_at: string;
}

export interface WorkerHeartbeat {
  id: number;
  worker_id: number;
  in_flight: number;
  created_at: string;
}

export interface DeadLetterJob {
  id: number;
  job_id: number;
  project_id: number;
  queue_id: number | null;
  type: string;
  payload: Record<string, unknown>;
  final_error: string | null;
  attempts: number;
  moved_at: string;
  created_at: string;
}

export interface ThroughputBucket {
  minute: string;
  completed: number;
  failed: number;
}

export interface QueueDepth {
  queue_id: number;
  name: string;
  depth: number;
  in_flight: number;
}

export interface ProjectMetrics {
  window_minutes: number;
  total_completed: number;
  total_failed: number;
  success_rate: number | null;
  p50_duration_ms: number | null;
  p95_duration_ms: number | null;
  throughput_per_minute: ThroughputBucket[];
  queue_depths: QueueDepth[];
}
