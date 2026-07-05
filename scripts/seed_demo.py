"""Seed the running API with demo data for a dashboard walkthrough.

Registers (or logs in) a demo user, creates a project + a couple of queues + a
cron schedule, then submits a stream of mixed jobs (sleeps, random failures,
always-fails) so the dashboard shows live movement.

Usage:
    # API must be running (uvicorn app.main:app --port 8000)
    python scripts/seed_demo.py                 # one burst of ~200 jobs
    python scripts/seed_demo.py --count 500     # bigger burst
    python scripts/seed_demo.py --loop          # keep pumping until Ctrl-C

Env:
    API_BASE   (default http://localhost:8000)
    DEMO_EMAIL (default demo@local.test)
    DEMO_PASSWORD (default supersecret)
"""
from __future__ import annotations

import argparse
import os
import random
import time

import httpx

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
EMAIL = os.environ.get("DEMO_EMAIL", "demo@local.test")
PASSWORD = os.environ.get("DEMO_PASSWORD", "supersecret")


def _auth(client: httpx.Client) -> str:
    reg = client.post(
        "/api/v1/auth/register", json={"email": EMAIL, "password": PASSWORD}
    )
    if reg.status_code == 201:
        return reg.json()["access_token"]
    # Already registered — log in instead.
    login = client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )
    login.raise_for_status()
    return login.json()["access_token"]


def _get_or_create_project(client: httpx.Client) -> int:
    existing = client.get("/api/v1/projects?limit=200").json()["items"]
    for p in existing:
        if p["name"] == "demo":
            return p["id"]
    return client.post("/api/v1/projects", json={"name": "demo"}).json()["id"]


def _get_or_create_queue(
    client: httpx.Client, project_id: int, name: str, concurrency: int
) -> int:
    existing = client.get(
        f"/api/v1/projects/{project_id}/queues?limit=200"
    ).json()["items"]
    for q in existing:
        if q["name"] == name:
            return q["id"]
    body = {
        "name": name,
        "concurrency_limit": concurrency,
        "retry_policy": {
            "strategy": "exponential",
            "base_delay_s": 2,
            "max_attempts": 4,
            "jitter": True,
        },
    }
    return client.post(
        f"/api/v1/projects/{project_id}/queues", json=body
    ).json()["id"]


def _ensure_schedule(client: httpx.Client, queue_id: int) -> None:
    schedules = client.get(
        f"/api/v1/queues/{queue_id}/schedules?limit=50"
    ).json()["items"]
    if not schedules:
        client.post(
            f"/api/v1/queues/{queue_id}/schedules",
            json={
                "type": "demo.sleep",
                "cron_expr": "* * * * *",
                "payload": {"sleep_s": 1},
            },
        )


def _random_job() -> dict:
    roll = random.random()
    if roll < 0.6:
        return {"type": "demo.sleep", "payload": {"sleep_s": round(random.uniform(0, 1.5), 2)}}
    if roll < 0.9:
        return {"type": "demo.random_fail", "payload": {"fail_rate": 0.4}}
    return {"type": "demo.always_fail", "payload": {"message": "demo failure"}}


def submit_burst(client: httpx.Client, queue_id: int, count: int) -> None:
    jobs = [_random_job() for _ in range(count)]
    # Submit in atomic batches of 50.
    for i in range(0, len(jobs), 50):
        chunk = jobs[i : i + 50]
        client.post(f"/api/v1/queues/{queue_id}/jobs/batch", json={"jobs": chunk})
    print(f"submitted {count} jobs to queue {queue_id}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()

    with httpx.Client(base_url=API_BASE, timeout=30) as client:
        token = _auth(client)
        client.headers["Authorization"] = f"Bearer {token}"

        project_id = _get_or_create_project(client)
        fast = _get_or_create_queue(client, project_id, "fast", concurrency=20)
        _get_or_create_queue(client, project_id, "batch", concurrency=5)
        _ensure_schedule(client, fast)
        print(f"project={project_id} queue(fast)={fast}")
        print("Open the dashboard (web/) and watch Jobs / Workers / Metrics move.")

        if args.loop:
            print("Looping — Ctrl-C to stop.")
            try:
                while True:
                    submit_burst(client, fast, args.count)
                    time.sleep(5)
            except KeyboardInterrupt:
                print("\nstopped.")
        else:
            submit_burst(client, fast, args.count)


if __name__ == "__main__":
    main()
