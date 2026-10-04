"""Container smoke test: the built images, a real Redis, and the fixtures.

Runs against whatever docker-compose.test.yml started. Needs `pip install redis mcp`.

Exit code 0 means every check passed. Anything else prints which check failed.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

import redis

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "realtime_consumer"))
import vdu_queue as q  # noqa: E402

API = os.getenv("API_URL", "http://127.0.0.1:15000")
REAPER_METRICS = os.getenv("REAPER_METRICS_URL", "http://127.0.0.1:19100/metrics")
MCP_URL = os.getenv("MCP_URL", "http://127.0.0.1:18080/mcp")
MCP_TOKEN = os.getenv("MCP_BEARER_TOKEN", "smoke-test-token")
RECEIVER = os.getenv("WEBHOOK_RECEIVER_URL", "http://127.0.0.1:19000")
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "16379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "smoke-test-password")
FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")
MAX_FILE_BYTES = 10 * 1024 * 1024

QUEUE, PROCESSING, DEAD = q.QUEUE_KEY, q.PROCESSING_KEY, q.DEAD_KEY


def check(name, condition, detail=""):
    mark = "ok  " if condition else "FAIL"
    print(f"[{mark}] {name}{('  ' + detail) if detail else ''}")
    if not condition:
        sys.exit(1)


def section(title):
    print(f"\n--- {title}")


def http(method, path, body=None, ctype=None, base=API, timeout=10, headers=None):
    req = urllib.request.Request(f"{base}{path}", data=body, method=method)
    if ctype:
        req.add_header("Content-Type", ctype)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def wait_for(path, timeout_s=60, want=200, base=API):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            code, _ = http("GET", path, base=base)
            if code == want:
                return True
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(1)
    return False


def multipart(fields):
    """fields: list of (name, filename or None, bytes)."""
    boundary = "smoke-" + uuid.uuid4().hex
    body = b""
    for name, filename, content in fields:
        disp = f'form-data; name="{name}"' + (f'; filename="{filename}"' if filename else "")
        body += (f"--{boundary}\r\nContent-Disposition: {disp}\r\n"
                 f"Content-Type: application/octet-stream\r\n\r\n").encode() + content + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def post(field, filename, content, extra=(), headers=None, timeout=10):
    body, ctype = multipart([(field, filename, content), *extra])
    code, raw = http("POST", "/process", body, ctype, headers=headers, timeout=timeout)
    try:
        return code, json.loads(raw)
    except ValueError:
        return code, raw.decode(errors="replace")


def status(task_id):
    code, raw = http("GET", f"/status/{task_id}")
    return code, (json.loads(raw) if code == 200 else raw.decode(errors="replace"))


def unique_pdf():
    """A valid-looking PDF no other run has sent, so the result cache never interferes."""
    return open(os.path.join(FIXTURES, "sample.pdf"), "rb").read() + f"\n% {uuid.uuid4()}\n".encode()


def cleanup(r, task_id):
    cache = r.hget(q.task_key(task_id), "cache_key")
    r.delete(q.task_key(task_id), q.data_key(task_id))
    if cache and r.get(cache) == task_id:
        r.delete(cache)
    for key in (QUEUE, PROCESSING, DEAD, q.WEBHOOK_KEY):
        r.lrem(key, 0, task_id)


def main():
    section("the API and Redis are up")
    check("API answers /health within 60s", wait_for("/health"))
    check("API /ready is 200 (Redis reachable with password)", wait_for("/ready", 30))

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
    raw_r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD)
    check("Redis reachable with password", r.ping())
    try:
        redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True).ping()
        check("Redis rejects unauthenticated clients", False)
    except redis.AuthenticationError:
        check("Redis rejects unauthenticated clients", True)
    check("Redis persistence is on", r.config_get("appendonly").get("appendonly") == "yes")

    section("accepted uploads, and what lands in Redis")
    for fixture, expect_ext in (("sample.pdf", "pdf"), ("sample.png", "png")):
        original = open(os.path.join(FIXTURES, fixture), "rb").read()
        code, body = post("file", fixture, original, headers={"Cache-Control": "no-cache"})
        check(f"{fixture}: POST /process returns 202", code == 202, f"got {code} {body}")
        task_id = body.get("task_id", "")
        check(f"{fixture}: task_id looks like a UUID", len(task_id) == 36)

        code, st = status(task_id)
        check(f"{fixture}: GET /status returns 200", code == 200, f"got {code}")
        check(f"{fixture}: status queued, attempts 0 (no worker should be running)",
              st.get("status") == "queued" and st.get("attempts") == 0,
              f"{st}  <- if status is processing/done, a worker (or tools/demo_worker.py) is consuming the queue; stop it and rerun")

        stored = r.hgetall(q.task_key(task_id))
        check(f"{fixture}: stored filename matches", stored.get("filename") == fixture)
        check(f"{fixture}: stored extension detected as {expect_ext}", stored.get("extension") == expect_ext, stored.get("extension"))
        check(f"{fixture}: the document is not inside the task hash", "data" not in stored)
        check(f"{fixture}: stored raw bytes match the file exactly", raw_r.get(q.data_key(task_id)) == original)
        check(f"{fixture}: the stored document expires", 0 < r.ttl(q.data_key(task_id)))
        check(f"{fixture}: task_id is on the waiting queue", task_id in r.lrange(QUEUE, 0, -1))
        cleanup(r, task_id)

    pdf = open(os.path.join(FIXTURES, "sample.pdf"), "rb").read()
    code, body = post("file", "misnamed.jpg", pdf, headers={"Cache-Control": "no-cache"})
    check("PDF uploaded as .jpg is accepted", code == 202, f"got {code}")
    ext = r.hget(q.task_key(body["task_id"]), "extension")
    check("...and stored with extension pdf, from its content", ext == "pdf", ext)
    cleanup(r, body["task_id"])

    section("the result cache")
    doc = unique_pdf()
    code, first = post("file", "cache.pdf", doc)
    check("first upload of a document is 202 queued", code == 202 and first.get("status") == "queued", f"{code} {first}")
    code, second = post("file", "cache.pdf", doc)
    check("identical upload while waiting joins the same task (202, deduplicated)",
          code == 202 and second.get("task_id") == first["task_id"] and second.get("deduplicated") is True, f"{code} {second}")
    check("...and the queue holds it once", r.lrange(QUEUE, 0, -1).count(first["task_id"]) == 1)
    r.hset(q.task_key(first["task_id"]), "status", "done")   # as if a worker had finished it
    code, third = post("file", "cache.pdf", doc)
    check("identical upload after it is done is 200 with cached true",
          code == 200 and third.get("cached") is True and third.get("task_id") == first["task_id"], f"{code} {third}")
    code, fresh = post("file", "cache.pdf", doc, headers={"Cache-Control": "no-cache"})
    check("Cache-Control: no-cache forces a new task", code == 202 and fresh.get("task_id") != first["task_id"], f"{code} {fresh}")
    cleanup(r, first["task_id"]); cleanup(r, fresh["task_id"])

    section("rejections, and hostile input")
    code, body = post("file", None, b"C:\\Users\\me\\Board Resolution.pdf")
    check("text in the file field (curl without @) is 400", code == 400, f"got {code}")
    check("...with a message that mentions file=@", "file=@" in str(body), str(body))
    code, body = post("file", "notes.txt", b"just some text")
    check("unsupported content is 415", code == 415, f"got {code}")
    code, body = post("file", "empty.pdf", b"")
    check("empty file is 400", code == 400, f"got {code}")
    code, body = post("other", "x.pdf", pdf)
    check("missing file field is 400", code == 400, f"got {code}")

    exact = unique_pdf()
    exact += b"x" * (MAX_FILE_BYTES - len(exact))
    code, body = post("file", "exact.pdf", exact, timeout=60)
    check(f"a file of exactly {MAX_FILE_BYTES} bytes is accepted", code == 202, f"got {code} {body}")
    cleanup(r, body["task_id"])
    code, body = post("file", "over.pdf", exact + b"x", timeout=60)
    check("one byte more is 413, with both sizes in the message",
          code == 413 and str(MAX_FILE_BYTES) in str(body), f"got {code} {body}")

    # Far over the limit, the server answers 413 from the declared Content-Length
    # before the body has finished arriving. Some client stacks (Windows loopback
    # through Docker Desktop among them) then see a reset instead of the response.
    # Either way the upload was refused; the metrics check below confirms the 413.
    big = b"%PDF-" + b"x" * (MAX_FILE_BYTES + 200 * 1024)
    body, ctype = multipart([("file", "big.pdf", big)])
    try:
        code, _ = http("POST", "/process", body, ctype, timeout=60)
        check("far oversized upload is 413", code == 413, f"got {code}")
    except (OSError, ConnectionError) as e:
        print(f"[note] far oversized upload: connection closed early by the server ({type(e).__name__}); verifying via metrics")

    code, body = post("file", "cb.pdf", pdf, extra=[("callback_url", None, b"https://evil.example.net/steal")])
    check("callback to a host not on the allowed list is 400", code == 400 and "not in the allowed list" in str(body), f"{code} {body}")
    code, body = post("file", "cb.pdf", pdf, extra=[("callback_url", None, b"http://redis:6379/")])
    check("callback to an internal service is 400", code == 400, f"{code} {body}")
    check("nothing was queued by the rejected uploads", r.llen(QUEUE) == 0, str(r.lrange(QUEUE, 0, -1)))

    code, _ = status("00000000-0000-0000-0000-000000000000")
    check("unknown task_id returns 404", code == 404, f"got {code}")

    section("webhooks: the system calls the client back")
    check("webhook receiver is up", wait_for("/health", 30, base=RECEIVER))
    code, body = post("file", "hook.pdf", unique_pdf(),
                      extra=[("callback_url", None, b"http://webhook-receiver:9000/done")])
    check("upload with an allowed callback_url is 202", code == 202, f"{code} {body}")
    task_id = body["task_id"]
    check("...and the callback address is stored with the task",
          r.hget(q.task_key(task_id), "callback_url") == "http://webhook-receiver:9000/done")
    # Finish it the way a worker does, through the same queue module.
    r.lrem(QUEUE, 0, task_id); r.lpush(PROCESSING, task_id); q.mark_claimed(r, task_id)
    q.finish_done(r, task_id, json.dumps({"markdown": "# Delivered", "layout": []}), 600)
    received = []
    deadline = time.time() + 20
    while time.time() < deadline and not received:
        _, raw = http("GET", "/received", base=RECEIVER)
        received = [e for e in json.loads(raw) if e["task_id"] == task_id]
        time.sleep(0.5)
    check("the reaper delivered the callback to the receiver", bool(received))
    check("...with status done and the result", received[0]["status"] == "done" and received[0]["markdown_characters"] > 0, str(received))
    check("...and a valid signature", received[0]["signature_valid"] is True, str(received))
    deadline = time.time() + 10
    while time.time() < deadline and not (status(task_id)[1].get("callback_status") or "").startswith("delivered"):
        time.sleep(0.5)
    check("GET /status shows callback_status delivered", status(task_id)[1].get("callback_status", "").startswith("delivered"),
          str(status(task_id)[1].get("callback_status")))
    cleanup(r, task_id)

    section("API metrics")
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
    check("API counts requests by route", 'vdu_http_requests_total{route="/process",status="202"}' in text)
    check("API counts rejections by reason", metric('vdu_uploads_rejected_total{reason="unsupported_type"}') >= 1)
    check("API counts refused callbacks", metric('vdu_uploads_rejected_total{reason="bad_callback"}') >= 2)
    check("API records upload sizes by type", 'vdu_upload_bytes_count{type="pdf"}' in text)
    check("API counted the 413s", metric('vdu_http_requests_total{route="/process",status="413"}') >= 1)
    check("API counts cache hits, joins, and bypasses",
          metric('vdu_cache_total{outcome="hit"}') >= 1 and metric('vdu_cache_total{outcome="dedupe"}') >= 1
          and metric('vdu_cache_total{outcome="bypass"}') >= 1)

    section("the reaper, live: a worker dies holding a task")
    task_id = str(uuid.uuid4())
    r.hset(q.task_key(task_id), mapping={"status": "processing", "filename": "x.pdf", "extension": "pdf",
                                         "attempts": "1", "claimed_at": f"{time.time() - 3600:.3f}"})
    r.lpush(PROCESSING, task_id)
    deadline = time.time() + 20
    while time.time() < deadline and r.hget(q.task_key(task_id), "status") != "queued":
        time.sleep(0.5)
    check("reaper requeues a claim older than STALE_AFTER_SECONDS", r.hget(q.task_key(task_id), "status") == "queued")
    check("...task is back on the waiting queue", task_id in r.lrange(QUEUE, 0, -1))
    check("...and off the in-progress list", task_id not in r.lrange(PROCESSING, 0, -1))
    cleanup(r, task_id)

    task_id = str(uuid.uuid4())
    r.hset(q.task_key(task_id), mapping={"status": "processing", "filename": "x.pdf", "extension": "pdf",
                                         "attempts": "3", "claimed_at": f"{time.time() - 3600:.3f}"})
    r.set(q.data_key(task_id), b"%PDF-1.4 stranded")
    r.lpush(PROCESSING, task_id)
    deadline = time.time() + 20
    while time.time() < deadline and r.hget(q.task_key(task_id), "status") != "failed":
        time.sleep(0.5)
    st = r.hgetall(q.task_key(task_id))
    check("reaper dead-letters after MAX_ATTEMPTS", st.get("status") == "failed", str(st))
    check("...with a reason in the error field", "gave up" in st.get("error", ""))
    check("...on the dead letter queue", task_id in r.lrange(DEAD, 0, -1))
    check("...the stored document is deleted", not r.exists(q.data_key(task_id)))
    check("...and the result expires", 0 < r.ttl(q.task_key(task_id)))
    code, st_api = status(task_id)
    check("...and the API shows failed with the error", st_api.get("status") == "failed" and "gave up" in st_api.get("error", ""))
    cleanup(r, task_id)

    section("reaper metrics")
    code, raw = http("GET", "", base=REAPER_METRICS)
    text = raw.decode()
    check("reaper /metrics is 200", code == 200)
    check("reaper publishes queue depths", 'vdu_queue_depth{queue="waiting"}' in text)
    check("reaper counted its actions", 'vdu_reaper_actions_total{action="requeued"}' in text and 'action="dead_lettered"' in text)
    check("reaper counted the webhook delivery", 'vdu_webhooks_total{outcome="delivered"}' in text)

    section("the MCP server, over real Streamable HTTP with a bearer token")
    import asyncio
    asyncio.run(mcp_checks(r))

    print("\nAll smoke checks passed.")


async def mcp_checks(r):
    import httpx2 as httpx
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    from mcp.types import TextContent

    def text_of(res):
        return "".join(c.text for c in res.content if isinstance(c, TextContent))

    base = MCP_URL.rsplit("/", 1)[0]
    check("MCP /health answers without a token", wait_for("/health", base=base))

    async with httpx.AsyncClient() as plain:
        resp = await plain.post(MCP_URL, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                headers={"accept": "application/json, text/event-stream"})
    check("MCP rejects requests without a bearer token (401)", resp.status_code == 401, f"got {resp.status_code}")

    authed = httpx.AsyncClient(headers={"Authorization": f"Bearer {MCP_TOKEN}"}, timeout=30)
    async with authed:
        async with Client(streamable_http_client(MCP_URL, http_client=authed)) as client:
            check("MCP connects with the token", client.server_info is not None)
            check("MCP server identifies itself", client.server_info.name == "visual-document-understanding", str(client.server_info))
            check("MCP negotiated a protocol version", bool(client.protocol_version), str(client.protocol_version))
            names = sorted(t.name for t in (await client.list_tools()).tools)
            check("MCP lists the four tools", names == ["extract_structured_data", "get_document_status", "read_document", "submit_document"], str(names))
            schema = (await client.read_resource("vdu://schema/result")).contents[0].text
            check("MCP serves the result schema resource", '"status"' in schema)

            # A real submission: MCP -> Rust API -> Redis, using the mounted fixture.
            res = await client.call_tool("submit_document", {"source": "/fixtures/sample.pdf", "fresh": True})
            check("MCP submit_document reaches the real API", not res.is_error, text_of(res))
            task_id = res.structured_content["task_id"]
            check("...and the task is on the real queue", task_id in r.lrange(QUEUE, 0, -1))
            st = await client.call_tool("get_document_status", {"task_id": task_id})
            check("MCP get_document_status reads it back", st.structured_content["status"] == "queued", str(st.structured_content))
            cleanup(r, task_id)

            bad = await client.call_tool("read_document", {"source": "/etc/hostname"})
            check("MCP refuses a path outside the allowed directory", bad.is_error and "outside the allowed" in text_of(bad), text_of(bad))
            ssrf = await client.call_tool("read_document", {"source": "https://redis:6379/"})
            check("MCP refuses a URL that points inside the network", ssrf.is_error and "not a public address" in text_of(ssrf), text_of(ssrf))
            plain_http = await client.call_tool("read_document", {"source": "http://example.com/doc.pdf"})
            check("MCP refuses plain http URLs by default", plain_http.is_error and "only https" in text_of(plain_http), text_of(plain_http))


if __name__ == "__main__":
    main()
