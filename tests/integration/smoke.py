"""Container smoke test: the built API and reaper images, a real Redis, and the fixtures.

Runs against whatever docker-compose.test.yml started. Uses only the standard
library plus redis-py, so it needs no extra setup beyond `pip install redis`.

Exit code 0 means every check passed. Anything else prints which check failed.
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

import redis

API = os.getenv("API_URL", "http://127.0.0.1:15000")
REAPER_METRICS = os.getenv("REAPER_METRICS_URL", "http://127.0.0.1:19100/metrics")
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "16379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "smoke-test-password")
FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")

QUEUE, PROCESSING, DEAD = "ocr_tasks", "ocr_tasks:processing", "ocr_tasks:dead"


def check(name, condition, detail=""):
    mark = "ok  " if condition else "FAIL"
    print(f"[{mark}] {name}{('  ' + detail) if detail else ''}")
    if not condition:
        sys.exit(1)


def http(method, path, body=None, ctype=None, base=API, timeout=10):
    req = urllib.request.Request(f"{base}{path}", data=body, method=method)
    if ctype:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def wait_for(path, timeout_s=60, want=200):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            code, _ = http("GET", path)
            if code == want:
                return True
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(1)
    return False


def multipart(field, filename, content):
    boundary = "smoke-" + uuid.uuid4().hex
    disp = f'form-data; name="{field}"' + (f'; filename="{filename}"' if filename else "")
    body = (f"--{boundary}\r\nContent-Disposition: {disp}\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def post(field, filename, content):
    body, ctype = multipart(field, filename, content)
    code, raw = http("POST", "/process", body, ctype)
    try:
        return code, json.loads(raw)
    except ValueError:
        return code, raw.decode(errors="replace")


def status(task_id):
    code, raw = http("GET", f"/status/{task_id}")
    return code, (json.loads(raw) if code == 200 else raw.decode(errors="replace"))


def main():
    check("API answers /health within 60s", wait_for("/health"))
    check("API /ready is 200 (Redis reachable with password)", wait_for("/ready", 30))

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
    check("Redis reachable with password", r.ping())
    try:
        redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True).ping()
        check("Redis rejects unauthenticated clients", False)
    except redis.AuthenticationError:
        check("Redis rejects unauthenticated clients", True)
    check("Redis persistence is on", r.config_get("appendonly").get("appendonly") == "yes")

    # --- accepted uploads, and what lands in Redis ---
    for fixture, expect_ext in (("sample.pdf", "pdf"), ("sample.png", "png")):
        original = open(os.path.join(FIXTURES, fixture), "rb").read()
        code, body = post("file", fixture, original)
        check(f"{fixture}: POST /process returns 202", code == 202, f"got {code} {body}")
        task_id = body.get("task_id", "")
        check(f"{fixture}: task_id looks like a UUID", len(task_id) == 36)

        code, st = status(task_id)
        check(f"{fixture}: GET /status returns 200", code == 200, f"got {code}")
        check(f"{fixture}: status queued, attempts 0", st.get("status") == "queued" and st.get("attempts") == 0, str(st))

        stored = r.hgetall(f"task:{task_id}")
        check(f"{fixture}: stored filename matches", stored.get("filename") == fixture)
        check(f"{fixture}: stored extension detected as {expect_ext}", stored.get("extension") == expect_ext, stored.get("extension"))
        check(f"{fixture}: stored bytes round-trip exactly", base64.b64decode(stored.get("data", "")) == original)
        check(f"{fixture}: task_id is on the waiting queue", task_id in r.lrange(QUEUE, 0, -1))
        r.delete(f"task:{task_id}"); r.lrem(QUEUE, 0, task_id)

    # --- gap 21: content decides the type, not the name ---
    pdf = open(os.path.join(FIXTURES, "sample.pdf"), "rb").read()
    code, body = post("file", "misnamed.jpg", pdf)
    check("PDF uploaded as .jpg is accepted", code == 202, f"got {code}")
    ext = r.hget(f"task:{body['task_id']}", "extension")
    check("...and stored with extension pdf, from its content", ext == "pdf", ext)
    r.delete(f"task:{body['task_id']}"); r.lrem(QUEUE, 0, body["task_id"])

    # --- rejections ---
    code, body = post("file", None, b"C:\\Users\\me\\Board Resolution.pdf")
    check("text in the file field (curl without @) is 400", code == 400, f"got {code}")
    check("...with a message that mentions file=@", "file=@" in str(body), str(body))
    code, body = post("file", "notes.txt", b"just some text")
    check("unsupported content is 415", code == 415, f"got {code}")
    code, body = post("file", "empty.pdf", b"")
    check("empty file is 400", code == 400, f"got {code}")
    code, body = post("other", "x.pdf", pdf)
    check("missing file field is 400", code == 400, f"got {code}")
    # The server answers 413 from the declared Content-Length before the body
    # has finished arriving. Some client stacks (Windows loopback through Docker
    # Desktop among them) then see a reset or a stall instead of the response.
    # Either way the upload was refused; the metrics check below confirms the
    # 413 was actually issued.
    big = b"%PDF-" + b"x" * (10 * 1024 * 1024 + 1024)
    body, ctype = multipart("file", "big.pdf", big)
    try:
        code, _ = http("POST", "/process", body, ctype, timeout=60)
        check("oversized upload is 413", code == 413, f"got {code}")
    except (OSError, ConnectionError) as e:
        print(f"[note] oversized upload: connection closed early by the server ({type(e).__name__}); verifying via metrics")
    check("nothing was queued by the rejected uploads", r.llen(QUEUE) == 0, str(r.llen(QUEUE)))

    code, _ = status("00000000-0000-0000-0000-000000000000")
    check("unknown task_id returns 404", code == 404, f"got {code}")

    # --- API metrics ---
    code, raw = http("GET", "/metrics")
    text = raw.decode()

    def metric(sample):
        """Value of one metric sample line, or -1 if absent. Exact counts depend on
        how many times the test has run against the same container."""
        for line in text.splitlines():
            if line.startswith(sample + " "):
                return float(line.split()[-1])
        return -1

    check("API /metrics is 200", code == 200)
    check("API counts requests by route", 'vus_http_requests_total{route="/process",status="202"}' in text)
    check("API counts rejections by reason", metric('vus_uploads_rejected_total{reason="unsupported_type"}') >= 1, str([l for l in text.splitlines() if "rejected_total{" in l]))
    check("API records upload sizes by type", 'vus_upload_bytes_count{type="pdf"}' in text)
    check("API counted the 413 from the body limit layer", metric('vus_http_requests_total{route="/process",status="413"}') >= 1, str([l for l in text.splitlines() if "413" in l]))

    # --- the reaper, live: a worker "dies" holding a task ---
    task_id = str(uuid.uuid4())
    r.hset(f"task:{task_id}", mapping={"status": "processing", "filename": "x.pdf", "extension": "pdf",
                                       "data": "", "attempts": "1", "claimed_at": f"{time.time() - 60:.3f}"})
    r.lpush(PROCESSING, task_id)
    deadline = time.time() + 20
    while time.time() < deadline and r.hget(f"task:{task_id}", "status") != "queued":
        time.sleep(0.5)
    check("reaper requeues a stale claim (STALE_AFTER_SECONDS=3)", r.hget(f"task:{task_id}", "status") == "queued")
    check("...task is back on the waiting queue", task_id in r.lrange(QUEUE, 0, -1))
    check("...and off the in-progress list", task_id not in r.lrange(PROCESSING, 0, -1))
    r.delete(f"task:{task_id}"); r.lrem(QUEUE, 0, task_id)

    task_id = str(uuid.uuid4())
    r.hset(f"task:{task_id}", mapping={"status": "processing", "filename": "x.pdf", "extension": "pdf",
                                       "data": "", "attempts": "3", "claimed_at": f"{time.time() - 60:.3f}"})
    r.lpush(PROCESSING, task_id)
    deadline = time.time() + 20
    while time.time() < deadline and r.hget(f"task:{task_id}", "status") != "failed":
        time.sleep(0.5)
    st = r.hgetall(f"task:{task_id}")
    check("reaper dead-letters after MAX_ATTEMPTS", st.get("status") == "failed", str(st))
    check("...with a reason in the error field", "gave up" in st.get("error", ""))
    check("...on the dead letter queue", task_id in r.lrange(DEAD, 0, -1))
    check("...and the result expires", 0 < r.ttl(f"task:{task_id}"))
    code, st_api = status(task_id)
    check("...and the API shows failed with the error", st_api.get("status") == "failed" and "gave up" in st_api.get("error", ""))
    r.delete(f"task:{task_id}"); r.lrem(DEAD, 0, task_id)

    # --- reaper metrics ---
    code, raw = http("GET", "", base=REAPER_METRICS)
    text = raw.decode()
    check("reaper /metrics is 200", code == 200)
    check("reaper publishes queue depths", 'vus_queue_depth{queue="waiting"}' in text)
    check("reaper counted its actions", 'vus_reaper_actions_total{action="requeued"}' in text and 'action="dead_lettered"' in text)

    print("\nAll smoke checks passed.")


if __name__ == "__main__":
    main()
