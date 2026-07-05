# Entity–Relationship Diagram

13 tables. Multi-tenant identity (`users` / `organizations` / `org_members`) →
`projects` → `queues` → `jobs`, with execution history, cron templates, worker
tracking, and a dead-letter table hanging off `jobs`.

```mermaid
erDiagram
    ORGANIZATIONS ||--o{ ORG_MEMBERS : "has"
    USERS         ||--o{ ORG_MEMBERS : "has"
    ORGANIZATIONS ||--o{ PROJECTS : "owns"
    PROJECTS      ||--o{ RETRY_POLICIES : "defines"
    PROJECTS      ||--o{ QUEUES : "contains"
    RETRY_POLICIES ||--o{ QUEUES : "default for"
    QUEUES        ||--o{ JOBS : "holds"
    QUEUES        ||--o{ SCHEDULED_JOBS : "cron templates"
    PROJECTS      ||--o{ JOBS : "scopes"
    JOBS          ||--o{ JOB_EXECUTIONS : "attempts"
    JOBS          ||--o{ JOB_LOGS : "logs"
    JOB_EXECUTIONS ||--o{ JOB_LOGS : "logs (optional)"
    WORKERS       ||--o{ WORKER_HEARTBEATS : "samples"
    WORKERS       ||--o{ JOBS : "claims (SET NULL)"
    JOBS          ||--o{ DEAD_LETTER_JOBS : "snapshot on death"

    USERS {
        bigint id PK
        string email UK
        string password_hash
    }
    ORGANIZATIONS {
        bigint id PK
        string name
    }
    ORG_MEMBERS {
        bigint id PK
        bigint user_id FK
        bigint org_id FK
        enum   role
    }
    PROJECTS {
        bigint id PK
        bigint org_id FK
        string name
        string api_key UK
    }
    RETRY_POLICIES {
        bigint id PK
        bigint project_id FK
        enum   strategy
        float  base_delay_s
        float  max_delay_s
        int    max_attempts
        bool   jitter
    }
    QUEUES {
        bigint id PK
        bigint project_id FK
        string name
        int    priority
        int    concurrency_limit
        bool   is_paused
        bigint retry_policy_id FK
    }
    JOBS {
        bigint id PK
        bigint queue_id FK
        bigint project_id FK
        string type
        jsonb  payload
        enum   status
        int    priority
        timestamptz run_at
        int    attempts
        int    max_attempts
        string idempotency_key
        bigint worker_id FK
    }
    JOB_EXECUTIONS {
        bigint id PK
        bigint job_id FK
        int    attempt
        bigint worker_id FK
        enum   status
        text   error
        timestamptz started_at
        timestamptz finished_at
        bigint duration_ms
    }
    JOB_LOGS {
        bigint id PK
        bigint job_id FK
        bigint execution_id FK
        string level
        text   message
    }
    SCHEDULED_JOBS {
        bigint id PK
        bigint queue_id FK
        string type
        string cron_expr
        jsonb  payload
        timestamptz next_run_at
        bool   is_active
    }
    WORKERS {
        bigint id PK
        string name
        enum   status
        int    concurrency
        timestamptz last_heartbeat_at
        timestamptz stopped_at
    }
    WORKER_HEARTBEATS {
        bigint id PK
        bigint worker_id FK
        int    in_flight
        timestamptz created_at
    }
    DEAD_LETTER_JOBS {
        bigint id PK
        bigint job_id FK
        bigint project_id FK
        bigint queue_id FK
        string type
        jsonb  payload
        text   final_error
        int    attempts
        timestamptz moved_at
    }
```

## Cascades & indexes at a glance

- **Cascade delete** flows `projects → queues → jobs → {job_executions, job_logs,
  dead_letter_jobs}`; deleting a project tears down its whole subtree.
- **`SET NULL`** on `jobs.worker_id` and `job_executions.worker_id` — losing a
  worker never deletes job history.
- Hot path index: partial `jobs (queue_id, priority DESC, run_at, id)
  WHERE status = 'queued'`. See [design-decisions.md](design-decisions.md) for the
  full index rationale.
