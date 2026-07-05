# Distributed Job Scheduler

A production-inspired distributed job scheduling platform. PostgreSQL is the single
source of truth **and** the queue itself — atomic job claiming uses
`SELECT ... FOR UPDATE SKIP LOCKED`, no Redis or RabbitMQ in the core path.

Four components:

- **API server** (`app/`) — FastAPI REST API: auth, projects, queues, jobs, DLQ, metrics
- **Worker** (`worker/`) — claims jobs atomically, executes concurrently, heartbeats, graceful shutdown
- **Scheduler** (`scheduler/`) — promotes delayed jobs, materializes cron jobs, reaps dead workers
- **Dashboard** (`web/`) — React app for queues, jobs, workers, metrics

## Quickstart

```bash
# 1. Start Postgres
docker compose up -d db

# 2. Python env + deps
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Migrate
alembic upgrade head

# 4. Run the API
uvicorn app.main:app --reload --port 8000           # docs at http://localhost:8000/docs

# 5. Run workers + scheduler (separate terminals)
python -m worker.main
python -m scheduler.main

# 6. Dashboard
cd web && npm install && npm run dev                # http://localhost:5173
```

## Configuration

Copy `.env.example` to `.env` and adjust. See the env table in `docs/` for details.

## Tests

```bash
docker compose up -d db_test
pytest -x
```

## Docs

See [`docs/`](docs/) for architecture, ER diagram, API reference, and design decisions.
