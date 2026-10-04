"""Measure the whole pipeline: how fast documents go in one end and out the other.

Sends the same document COUNT times, each marked no-cache so every copy is
really read, a few at a time, then waits until every one is finished. Reports
documents per minute, pages per second, and how long each document took from
upload to result. This is the number the GPUs are for; tools/benchmark.py
measures only the front door.

    python tools/throughput.py --file C:/test/sample.pdf --count 20 --label demo-worker
    python tools/throughput.py --file my-report.pdf --count 50 --concurrency 10 \\
        --label aks-first-run --hardware "AKS, 1 x A100 80GB, 1 x T4, 30 Sep 2026"

The API address comes from API_URL (default http://127.0.0.1:15000, the test
stack, or a port-forward to a cluster). Behind a gateway, set API_KEY, and
API_KEY_HEADER if the header is not Ocp-Apim-Subscription-Key.

Results are printed and saved to benchmarks/throughput-<label>.json.
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

API = os.getenv("API_URL", "http://127.0.0.1:15000")
KEY = os.getenv("API_KEY", "")
KEY_HEADER = os.getenv("API_KEY_HEADER", "Ocp-Apim-Subscription-Key")
FINAL = ("done", "failed")


def count_pages(data):
    """Pages in a PDF; 1 for an image. Uses pypdfium2, the SDK's own PDF reader."""
    if not data.startswith(b"%PDF-"):
        return 1
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(data)
    try:
        return len(pdf)
    finally:
        pdf.close()


def percentile(values, p):
    s = sorted(values)
    k = max(0, min(len(s) - 1, round(p / 100 * (len(s) - 1))))
    return s[k]


def summarise(tasks, pages_per_document, wall_seconds):
    """tasks: list of dicts with status, seconds (upload to final state), warning."""
    done = [t for t in tasks if t["status"] == "done"]
    seconds = [t["seconds"] for t in done]
    out = {
        "documents": len(tasks),
        "done": len(done),
        "failed": sum(1 for t in tasks if t["status"] == "failed"),
        "unfinished": sum(1 for t in tasks if t["status"] not in FINAL),
        "with_warning": sum(1 for t in done if t.get("warning")),
        "pages_per_document": pages_per_document,
        "wall_seconds": round(wall_seconds, 2),
    }
    if done and wall_seconds > 0:
        out["documents_per_minute"] = round(len(done) / wall_seconds * 60, 2)
        out["pages_per_second"] = round(len(done) * pages_per_document / wall_seconds, 3)
        out["seconds_per_document"] = {
            "p50": round(percentile(seconds, 50), 2),
            "p95": round(percentile(seconds, 95), 2),
            "max": round(max(seconds), 2),
            "mean": round(statistics.mean(seconds), 2),
        }
    return out


async def run(path, count, concurrency, timeout, poll_seconds):
    data = open(path, "rb").read()
    name = os.path.basename(path)
    pages = count_pages(data)
    headers = {KEY_HEADER: KEY} if KEY else {}
    sem = asyncio.Semaphore(concurrency)
    tasks = []

    async with httpx.AsyncClient(base_url=API, timeout=120, headers=headers) as client:

        async def one():
            async with sem:
                started = time.perf_counter()
                r = await client.post("/process", files={"file": (name, data)},
                                      headers={"Cache-Control": "no-cache"})
                if r.status_code not in (200, 202):
                    tasks.append({"status": "failed", "seconds": 0.0, "error": f"HTTP {r.status_code}: {r.text[:200]}"})
                    return
                task = {"task_id": r.json()["task_id"], "status": "queued", "started": started}
                tasks.append(task)
                deadline = started + timeout
                while time.perf_counter() < deadline:
                    s = (await client.get(f"/status/{task['task_id']}")).json()
                    if s["status"] in FINAL:
                        task.update(status=s["status"], warning=s.get("warning"), error=s.get("error"))
                        break
                    await asyncio.sleep(poll_seconds)
                task["seconds"] = time.perf_counter() - started

        t0 = time.perf_counter()
        await asyncio.gather(*(one() for _ in range(count)))
        wall = time.perf_counter() - t0

    return summarise(tasks, pages, wall), tasks


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", required=True, help="the document to send")
    ap.add_argument("--count", type=int, default=20, help="how many copies to send")
    ap.add_argument("--concurrency", type=int, default=5, help="how many to send at once")
    ap.add_argument("--timeout", type=float, default=1800, help="seconds to wait for each document")
    ap.add_argument("--poll", type=float, default=1.0, help="seconds between status checks")
    ap.add_argument("--label", required=True, help="name for this run; the results file is named after it")
    ap.add_argument("--hardware", default="", help="what it ran on, for the record")
    args = ap.parse_args()

    result, tasks = asyncio.run(run(args.file, args.count, args.concurrency, args.timeout, args.poll))
    report = {
        "label": args.label,
        "when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "api": API,
        "hardware": args.hardware or f"not stated (measured from {platform.system()} {platform.release()})",
        "file": os.path.basename(args.file),
        "count": args.count,
        "concurrency": args.concurrency,
        "result": result,
        "errors": sorted({t["error"] for t in tasks if t.get("error")})[:5],
    }
    os.makedirs("benchmarks", exist_ok=True)
    path = os.path.join("benchmarks", f"throughput-{args.label}.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
    print(f"\nsaved to {path}")


if __name__ == "__main__":
    main()
