"""Container smoke test: the built API image, a real Redis, and the fixtures.

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

API = os.getenv("API_URL", "http://localhost:5000")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def check(name, condition, detail=""):
    mark = "ok  " if condition else "FAIL"
    print(f"[{mark}] {name}{('  ' + detail) if detail else ''}")
    if not condition:
        sys.exit(1)


def wait_for_health(timeout_s=60):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{API}/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(1)
    return False


def multipart(field, filename, content, boundary):
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def post_file(path):
    content = open(path, "rb").read()
    body, ctype = multipart("file", os.path.basename(path), content, "smoke-" + uuid.uuid4().hex)
    req = urllib.request.Request(f"{API}/process", data=body, method="POST")
    req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


def get_status(task_id):
    try:
        with urllib.request.urlopen(f"{API}/status/{task_id}", timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


def main():
    check("API answers /health within 60s", wait_for_health())

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    check("Redis reachable", r.ping())

    for fixture in ("sample.pdf", "sample.png"):
        path = os.path.join(FIXTURES, fixture)
        original = open(path, "rb").read()
        ext = fixture.rsplit(".", 1)[1]

        code, body = post_file(path)
        check(f"{fixture}: POST /process returns 202", code == 202, f"got {code}")
        check(f"{fixture}: response says queued", body.get("status") == "queued")
        task_id = body.get("task_id", "")
        check(f"{fixture}: task_id looks like a UUID", len(task_id) == 36)

        code, status = get_status(task_id)
        check(f"{fixture}: GET /status returns 200", code == 200, f"got {code}")
        check(f"{fixture}: status is queued (no worker running)", status.get("status") == "queued")

        stored = r.hgetall(f"task:{task_id}")
        check(f"{fixture}: stored filename matches", stored.get("filename") == fixture, repr(stored.get("filename")))
        check(f"{fixture}: stored extension matches", stored.get("extension") == ext)
        check(f"{fixture}: stored bytes round-trip exactly", base64.b64decode(stored.get("data", "")) == original)
        check(f"{fixture}: task_id is on the queue", task_id in r.lrange("ocr_tasks", 0, -1))

        r.delete(f"task:{task_id}")
        r.lrem("ocr_tasks", 0, task_id)

    code, _ = get_status("00000000-0000-0000-0000-000000000000")
    check("unknown task_id returns 404", code == 404, f"got {code}")

    print("\nAll smoke checks passed.")


if __name__ == "__main__":
    main()
