# API Reference

Base path: **`/api/v1`**. All routes require a `Authorization: Bearer <jwt>` header
except `/auth/*` and `/health`.

- **Interactive docs** (Swagger UI): `http://localhost:8000/docs`
- **Static schema**: [`openapi.json`](openapi.json) (regenerate any time with the
  snippet at the bottom)

## Conventions

- **Auth** — JWT access tokens; obtain via `POST /auth/register` or `POST /auth/login`.
- **Pagination** — list endpoints accept `limit` / `offset` and return
  `{"items": [...], "total": n, "limit": l, "offset": o}`.
- **Errors** — uniform envelope: `{"error": {"code": "QUEUE_NOT_FOUND", "message": "...", "details": {...}}}`.
  201 on create, 200 on idempotent replay, 409 on conflict, 404 scoped to the caller's
  org (no existence leaks).

## Endpoint map

### Auth
| Method | Path | Notes |
|---|---|---|
| POST | `/auth/register` | Creates user + personal org + owner membership; returns user + token |
| POST | `/auth/login` | Returns a JWT access token |
| GET | `/auth/me` | Current user (protected) |

### Projects
| Method | Path | Notes |
|---|---|---|
| POST / GET | `/projects` | Create / list (org-scoped) |
| GET / PATCH / DELETE | `/projects/{id}` | Fetch / update / delete |

### Queues
| Method | Path | Notes |
|---|---|---|
| POST / GET | `/projects/{id}/queues` | Create (inline or referenced retry policy) / list |
| GET / PATCH / DELETE | `/projects/{id}/queues/{qid}` | Fetch / update / delete |
| POST | `/projects/{id}/queues/{qid}/pause` · `/resume` | Toggle claiming |
| GET | `/projects/{id}/queues/{qid}/stats` | Counts by status, oldest-queued age, avg duration |

### Jobs
| Method | Path | Notes |
|---|---|---|
| POST | `/queues/{qid}/jobs` | Submit (immediate/delayed; idempotent replay → 200) |
| POST | `/queues/{qid}/jobs/batch` | Atomic array submit |
| POST | `/queues/{qid}/jobs/retry-failed` | Bulk re-enqueue failed/dead jobs |
| GET | `/jobs` | List with filters: `status`, `queue_id`, `type`, `created_after/before` |
| GET | `/jobs/{id}` | Detail with executions + logs |
| POST | `/jobs/{id}/cancel` | Cancel (legal only pre-running) |

### Schedules (cron)
| Method | Path | Notes |
|---|---|---|
| POST / GET | `/queues/{qid}/schedules` | Create (cron validated) / list |
| GET / PATCH / DELETE | `/queues/{qid}/schedules/{sid}` | Fetch / update / delete |
| POST | `/queues/{qid}/schedules/{sid}/pause` · `/activate` | Toggle |

### Dead letter queue
| Method | Path | Notes |
|---|---|---|
| GET | `/projects/{id}/dlq` | List dead-lettered jobs |
| POST | `/dlq/{id}/retry` | Re-enqueue fresh (attempts reset) |
| DELETE | `/dlq/{id}` | Discard |

### Workers & metrics
| Method | Path | Notes |
|---|---|---|
| GET | `/workers` | Worker fleet |
| GET | `/workers/{id}` · `/workers/{id}/heartbeats` | Worker detail / heartbeat samples |
| GET | `/projects/{id}/metrics` | Throughput/min, success rate, p50/p95, queue depth |

### Health
| Method | Path | Notes |
|---|---|---|
| GET | `/health` | Liveness (unauthenticated) |

## Regenerating `openapi.json`

```bash
python -c "import json; from app.main import app; open('docs/openapi.json','w').write(json.dumps(app.openapi(), indent=2))"
```
