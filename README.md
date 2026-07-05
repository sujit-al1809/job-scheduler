# Distributed Job Scheduler

A production-inspired distributed job scheduling platform. **PostgreSQL is the single
source of truth _and_ the queue itself** — atomic job claiming uses
`SELECT ... FOR UPDATE SKIP LOCKED`, with no Redis or RabbitMQ in the core path.

Four components:

- **API server** (`app/`) — FastAPI REST API: auth, projects, queues, jobs, schedules, DLQ, workers, metrics
- **Worker** (`worker/`) — claims jobs atomically, executes concurrently, heartbeats, shuts down gracefully
- **Scheduler** (`scheduler/`) — promotes delayed jobs, materializes cron jobs, reaps dead workers
- **Dashboard** (`web/`) — React app for queues, jobs, workers, and metrics

See [`docs/architecture.md`](docs/architecture.md) for diagrams,
[`docs/er-diagram.md`](docs/er-diagram.md) for the schema, and
[`docs/design-decisions.md`](docs/design-decisions.md) for the _why_.

## Highlights

- **Exactly-once claiming** under concurrency — proven by a 3-workers × 500-jobs test
  asserting zero duplicate executions ([`tests/test_e2e.py`](tests/test_e2e.py)).
- **Retry policies** (fixed / linear / exponential + jitter + max cap) with a
  **dead-letter queue** for exhausted jobs.
- **Failure recovery** — a heartbeat-based reaper requeues a dead worker's in-flight
  jobs; workers drain in-flight work on graceful shutdown.
- **Cron scheduling** — recurring templates materialize one job per tick, safe under
  multiple schedulers.
- **Metrics** — throughput, success rate, and p50/p95 latency derived from execution
  history; live dashboard.

## Prerequisites

- Docker (for PostgreSQL) · Python 3.12 · Node 18+ (for the dashboard)

## Quickstart

```bash
# 1. Start Postgres (dev on :5432, test on :5433)
docker compose up -d db db_test

# 2. Python env + deps
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Configure + migrate
cp .env.example .env
alembic upgrade head

# 4. Run the API (docs at http://localhost:8000/docs)
uvicorn app.main:app --reload --port 8000
```

### The live demo (5 terminals)

With the API running, open more terminals (all with the venv activated):

```bash
# terminal 2 & 3 — two workers, to show distributed claiming
python -m worker.main
python -m worker.main

# terminal 4 — the scheduler (promotion, cron, reaper)
python -m scheduler.main

# terminal 5 — pump a stream of mixed jobs
python scripts/seed_demo.py --loop            # or: --count 500 for one burst

# dashboard
cd web && npm install && npm run dev          # http://localhost:5173
```

Register in the dashboard, then watch **Jobs**, **Workers**, and **Metrics** move in
real time. Kill a worker with Ctrl-C to see graceful drain; `kill -9` it to see the
reaper requeue its jobs.

## Tests

Integration tests run against the real Postgres test container (`db_test` on :5433)
— we depend on `SKIP LOCKED`, so there is no SQLite fallback.

```bash
docker compose up -d db_test
pytest -x
```

## Configuration

Set via `.env` (see [`.env.example`](.env.example)):

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://scheduler:scheduler@localhost:5432/scheduler` | Async DB URL for API/worker/scheduler |
| `TEST_DATABASE_URL` | `...@localhost:5433/scheduler_test` | Test DB (compose service `db_test`) |
| `JWT_SECRET` | `change-me-...` | HMAC secret for access tokens |
| `ACCESS_TOKEN_TTL_MIN` | `60` | Access-token lifetime (minutes) |
| `WORKER_CONCURRENCY` | `8` | Max concurrent jobs per worker |
| `WORKER_POLL_INTERVAL_S` | `1.0` | Claim poll interval |
| `WORKER_CLAIM_BATCH_SIZE` | `10` | Max jobs claimed per poll |
| `DRAIN_TIMEOUT_S` | `30` | Graceful-shutdown drain budget |
| `HEARTBEAT_INTERVAL_S` | `5` | Worker heartbeat cadence |
| `HEARTBEAT_TIMEOUT_S` | `30` | Reaper marks a worker dead after this silence |
| `SCHEDULER_POLL_INTERVAL_S` | `1.0` | Scheduler loop interval |

## API

All routes are under `/api/v1` and require a JWT bearer token except `/auth/*` and
`/health`. Interactive docs at **`/docs`**; a static export lives at
[`docs/openapi.json`](docs/openapi.json). See [`docs/api.md`](docs/api.md) for an
endpoint map.

## Repo layout

```
app/         FastAPI service (core, models, schemas, api/v1, services)
worker/      claim + execute + retry engine, heartbeats, graceful shutdown
scheduler/   promotion, cron materialization, dead-worker reaper
web/         React + Vite + TS dashboard
tests/       unit + integration (incl. multi-worker concurrency)
alembic/     migrations
docs/        architecture, ER diagram, API, design decisions
scripts/     seed_demo.py
```
