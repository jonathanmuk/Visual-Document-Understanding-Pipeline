"""Measure the ingest layer: the Rust API and Redis. No GPU involved.

What it measures, and why each matters:

    large    Upload a ~9.5 MB document ten times. How long does one upload take,
             and how much Redis memory does one waiting document occupy?
    poll     While that large document waits, ask for its status 50 times. Every
             assistant and client polls; this is how long each poll takes.
    ingest   Fire 500 small uploads, 20 at a time. How many uploads per second
             can the API accept, and how long does each wait?
    cache    Upload the same document twice. How long does the second, cached
             answer take? (Only meaningful once the result cache exists.)

It does NOT measure OCR speed, GPU throughput, or cost. Those need real
hardware. Run it against the compose stack with no worker running, so nothing
consumes the queue mid-measurement.

    python tools/benchmark.py --label before
    python tools/benchmark.py --label after

Results are printed and saved to benchmarks/<label>.json.
"""
import argparse
import asyncio
import json
import os
import platform
import statistics
import time
from datetime import datetime, timezone

import httpx
import redis

API = os.getenv("API_URL", "http://127.0.0.1:15000")
R = redis.Redis(host=os.getenv("REDIS_HOST", "127.0.0.1"), port=int(os.getenv("REDIS_PORT", "16379")),
                password=os.getenv("REDIS_PASSWORD", "smoke-test-password"))
NO_CACHE = {"Cache-Control": "no-cache"}
SMALL = open(os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "sample.pdf"), "rb").read()


def pct(values, p):
    s = sorted(values)
    k = max(0, min(len(s) - 1, round(p / 100 * (len(s) - 1))))
    return s[k]


def summary(ms):
    return {"n": len(ms), "p50_ms": round(pct(ms, 50), 2), "p95_ms": round(pct(ms, 95), 2),
            "p99_ms": round(pct(ms, 99), 2), "mean_ms": round(statistics.mean(ms), 2)}


def big_document(size=9_500_000):
    # Passes the API's type check (starts with %PDF-); the body is filler. The
    # API does not parse PDFs, so this measures transfer and storage only.
    return b"%PDF-1.4\n" + os.urandom(size) + b"\n%%EOF\n"


def task_memory(task_id):
    total = 0
    for key in (f"task:{task_id}", f"taskdata:{task_id}"):
        used = R.memory_usage(key)
        total += used or 0
    return total


def cleanup(task_id):
    sha = R.hget(f"task:{task_id}", "cache_key")
    R.delete(f"task:{task_id}", f"taskdata:{task_id}")
    if sha:
        R.delete(sha)
    R.lrem("ocr_tasks", 0, task_id)


async def large(client):
    doc = big_document()
    times, mem, ids = [], [], []
    for _ in range(10):
        t0 = time.perf_counter()
        r = await client.post("/process", files={"file": ("big.pdf", doc)}, headers=NO_CACHE)
        times.append((time.perf_counter() - t0) * 1000)
        assert r.status_code in (200, 202), r.text
        tid = r.json()["task_id"]
        ids.append(tid)
        mem.append(task_memory(tid))
    for tid in ids[1:]:
        cleanup(tid)
    return {"document_bytes": len(doc), "upload": summary(times),
            "redis_bytes_per_waiting_document": int(statistics.mean(mem))}, ids[0]


async def poll(client, task_id):
    times = []
    for _ in range(50):
        t0 = time.perf_counter()
        r = await client.get(f"/status/{task_id}")
        times.append((time.perf_counter() - t0) * 1000)
        assert r.status_code == 200
    cleanup(task_id)
    return {"status_poll_while_large_document_waits": summary(times)}


async def ingest(client, total=500, concurrency=20):
    sem = asyncio.Semaphore(concurrency)
    times, ids = [], []

    async def one():
        async with sem:
            t0 = time.perf_counter()
            r = await client.post("/process", files={"file": ("s.pdf", SMALL)}, headers=NO_CACHE)
            times.append((time.perf_counter() - t0) * 1000)
            ids.append(r.json()["task_id"])

    t0 = time.perf_counter()
    await asyncio.gather(*(one() for _ in range(total)))
    wall = time.perf_counter() - t0
    for tid in ids:
        cleanup(tid)
    return {"uploads": total, "concurrency": concurrency, "seconds": round(wall, 2),
            "uploads_per_second": round(total / wall, 1), "upload": summary(times)}


async def cache(client):
    first = await client.post("/process", files={"file": ("c.pdf", SMALL)})
    tid = first.json()["task_id"]
    # Pretend a worker finished it, so the next identical upload can be served
    # from the cache.
    R.hset(f"task:{tid}", mapping={"status": "done", "result": json.dumps({"markdown": "x", "layout": []})})
    times, hits = [], 0
    for _ in range(50):
        t0 = time.perf_counter()
        r = await client.post("/process", files={"file": ("c.pdf", SMALL)})
        times.append((time.perf_counter() - t0) * 1000)
        body = r.json()
        hits += 1 if body.get("cached") else 0
    cleanup(tid)
    return {"cache_hits": hits, "of": 50, "cached_upload": summary(times)}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--skip", nargs="*", default=[])
    args = ap.parse_args()

    out = {"label": args.label, "when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "machine": f"{platform.system()} {platform.release()}, {os.cpu_count()} CPUs, Docker Desktop",
           "scope": "Rust API + Redis only, compose stack, no worker running. Not OCR or GPU performance."}
    limits = httpx.Limits(max_connections=50)
    async with httpx.AsyncClient(base_url=API, timeout=120, limits=limits) as client:
        if "large" not in args.skip:
            res, keep = await large(client)
            out["large"] = res
            out["poll"] = await poll(client, keep)
        if "ingest" not in args.skip:
            out["ingest"] = await ingest(client)
        if "cache" not in args.skip:
            out["cache"] = await cache(client)

    os.makedirs("benchmarks", exist_ok=True)
    path = os.path.join("benchmarks", f"{args.label}.json")
    json.dump(out, open(path, "w"), indent=2)
    print(json.dumps(out, indent=2))
    print(f"\nsaved to {path}")


if __name__ == "__main__":
    asyncio.run(main())
