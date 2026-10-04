"""A stand-in for the real worker, for learning the system without a GPU or an API key.

It claims tasks from the queue exactly as the real worker does, using the same
vdu_queue module, so claiming, retries, the in-progress list, TTLs, the dead
letter queue, the result cache, and webhook queueing all behave identically. It
also runs the same pre-flight check, so a corrupt file is rejected the same way.
The only difference is what it does in the middle: instead of running layout
detection and a vision model, it returns canned Markdown after a short delay.

This is a teaching tool, not part of the system. It is never deployed.

    python tools/demo_worker.py                  normal: succeeds after ~6s
    python tools/demo_worker.py --delay 20       slow, to watch progress reporting
    python tools/demo_worker.py --fail           always fails, to see the failure path
    python tools/demo_worker.py --warn           succeeds with a "regions lost" warning
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "realtime_consumer"))

import vdu_inspect  # noqa: E402
import vdu_queue as q  # noqa: E402

SAMPLE = """# ACME CORPORATION

Invoice #: INV-2026-0042
Date: 2026-09-20
Due: 2026-10-20

| Item | Qty | Unit price | Total |
| --- | --- | --- | --- |
| Widget, large | 12 | 45.00 | 540.00 |
| Widget, small | 30 | 12.50 | 375.00 |
| Delivery | 1 | 85.00 | 85.00 |

Subtotal: 1000.00
VAT (18%): 180.00
**Total due: 1180.00 USD**

Payment within 30 days to ACME CORPORATION, account 0123456789.
"""

LAYOUT = [[
    {"label": "doc_title", "bbox_2d": [40, 30, 560, 70], "content": "ACME CORPORATION"},
    {"label": "text", "bbox_2d": [40, 90, 400, 160], "content": "Invoice #: INV-2026-0042"},
    {"label": "table", "bbox_2d": [40, 180, 560, 320], "content": "| Item | Qty | Unit price | Total |"},
    {"label": "text", "bbox_2d": [40, 340, 400, 420], "content": "Subtotal: 1000.00"},
]]


def main():
    # Print UTF-8 even when the output is piped, as in Git Bash on Windows, so a
    # euro sign or any other character in a document shows correctly instead of
    # garbling or stopping the script.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=6.0, help="seconds to pretend to work")
    ap.add_argument("--fail", action="store_true", help="always fail, to see the failure path")
    ap.add_argument("--warn", action="store_true", help="succeed but report lost regions")
    args = ap.parse_args()

    r = q.make_redis()
    ttl = int(os.getenv("RESULT_TTL_SECONDS", "86400"))
    max_attempts = int(os.getenv("MAX_ATTEMPTS", "3"))

    print(f"demo worker ready (delay {args.delay}s, fail={args.fail}, warn={args.warn})", flush=True)
    print("this is a stand-in: no layout detection, no model, canned output", flush=True)

    while True:
        task_id = q.claim_first(r, 2)
        if not task_id:
            continue
        attempts = q.mark_claimed(r, task_id)
        task = r.hgetall(q.task_key(task_id))
        name = task.get("filename")
        print(f"claimed {task_id} ({name}), attempt {attempts}", flush=True)

        document = q.read_document(r, task_id, task)
        problem = ("the document is no longer stored" if document is None
                   else vdu_inspect.inspect(document, task.get("extension", "jpg")))
        if problem:
            q.finish_failed(r, task_id, problem, ttl)
            print(f"  failed: {problem}", flush=True)
            continue

        time.sleep(args.delay)

        if args.fail:
            action = q.handle_failure(
                r, task_id, "demo worker was told to fail (--fail)", attempts, max_attempts, ttl)
            print(f"  {action}: demo failure", flush=True)
            continue

        warning = None
        if args.warn:
            warning = ("2 region(s) in this batch of 1 document(s) failed to transcribe "
                       "and were dropped from the output; this document may be incomplete")
        body = SAMPLE if name and name.lower().endswith(".pdf") else SAMPLE.replace("# ACME", "# SCANNED IMAGE: ACME")
        q.finish_done(r, task_id, json.dumps({"markdown": body, "layout": LAYOUT}), ttl, warning)
        print(f"  done{' (with warning)' if warning else ''}", flush=True)


if __name__ == "__main__":
    main()
