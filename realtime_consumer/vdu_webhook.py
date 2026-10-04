"""Webhook delivery: tell a client its document is finished instead of making it poll.

When a task with a callback_url reaches a final state, vdu_queue puts its ID on
the ocr_webhooks list. Delivery threads in the reaper take IDs from that list and
POST the outcome to the callback URL. Delivery lives in the reaper, not the
worker, so a slow or unreachable client never holds up the GPU.

Each delivery is signed so the receiver can check it came from this system:

    X-VDU-Timestamp: 1790000000
    X-VDU-Signature: sha256=<hex HMAC-SHA256 of "<timestamp>.<body>" with WEBHOOK_SECRET>

The receiver recomputes the HMAC with the shared secret, compares, and rejects a
timestamp more than a few minutes old so a captured request cannot be replayed.

Delivery is at most once per final state, with retries. If the reaper restarts
mid-delivery, that callback is lost; the result is still available by polling.
The task records callback_status: pending, delivered, or failed with a reason.
"""
import hashlib
import hmac
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from loguru import logger

import vdu_metrics
import vdu_queue as q

SIGNATURE_HEADER = "X-VDU-Signature"
TIMESTAMP_HEADER = "X-VDU-Timestamp"


class Settings:
    def __init__(self):
        self.secret = os.getenv("WEBHOOK_SECRET", "")
        self.allowed_hosts = [h.strip().lower() for h in os.getenv("CALLBACK_ALLOWED_HOSTS", "").split(",") if h.strip()]
        self.allow_http = os.getenv("CALLBACK_ALLOW_HTTP", "").lower() in ("1", "true", "on", "yes")
        self.attempts = int(os.getenv("WEBHOOK_ATTEMPTS", "3"))
        self.timeout_seconds = float(os.getenv("WEBHOOK_TIMEOUT_SECONDS", "5"))
        self.backoff_seconds = float(os.getenv("WEBHOOK_BACKOFF_SECONDS", "2"))
        self.threads = int(os.getenv("WEBHOOK_THREADS", "2"))


def sign(secret, timestamp, body):
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def verify(secret, timestamp, body, signature, max_age_seconds=300, now=None):
    """What a receiver does. Used by the test receiver and the tests."""
    now = time.time() if now is None else now
    try:
        if abs(now - int(timestamp)) > max_age_seconds:
            return False
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), signature or "")


def host_allowed(url, settings):
    """Check again here, not only in the API: the list may have changed since."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" and not (parts.scheme == "http" and settings.allow_http):
        return False
    host = (parts.hostname or "").lower()
    for pattern in settings.allowed_hosts:
        if pattern.startswith("*."):
            if host.endswith(pattern[1:]):
                return True
        elif host == pattern:
            return True
    return False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # A redirect could send the request to a host that is not on the list.
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def payload(task_id, task):
    body = {"task_id": task_id, "status": task.get("status")}
    for field in ("error", "warning"):
        if task.get(field):
            body[field] = task[field]
    if task.get("result"):
        body["result"] = json.loads(task["result"])
    return json.dumps(body).encode()


def post(url, body, settings):
    """One attempt. Returns (delivered, detail)."""
    timestamp = str(int(time.time()))
    headers = {"Content-Type": "application/json", TIMESTAMP_HEADER: timestamp, "User-Agent": "vdu-webhook/1"}
    if settings.secret:
        headers[SIGNATURE_HEADER] = sign(settings.secret, timestamp, body)
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with _opener.open(request, timeout=settings.timeout_seconds) as resp:
            return 200 <= resp.status < 300, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except (urllib.error.URLError, OSError) as e:
        return False, str(getattr(e, "reason", e))


def deliver(r, task_id, settings, sleep=time.sleep):
    """Deliver one task's callback, with retries. Returns the recorded status."""
    key = q.task_key(task_id)
    task = r.hgetall(key)
    url = task.get("callback_url")
    if not task or not url:
        return None
    log = logger.bind(task_id=task_id)
    if not host_allowed(url, settings):
        status = "failed: callback host is not in CALLBACK_ALLOWED_HOSTS"
    else:
        body = payload(task_id, task)
        ok, detail = False, "not attempted"
        for attempt in range(1, settings.attempts + 1):
            ok, detail = post(url, body, settings)
            if ok:
                break
            if attempt < settings.attempts:
                sleep(settings.backoff_seconds * (2 ** (attempt - 1)))
        status = f"delivered ({detail})" if ok else f"failed after {settings.attempts} attempts: {detail}"
    # Only record if the task still exists; never recreate an expired hash.
    if r.exists(key):
        r.hset(key, "callback_status", status)
    outcome = "delivered" if status.startswith("delivered") else "failed"
    vdu_metrics.WEBHOOKS_TOTAL.labels(outcome=outcome).inc()
    (log.info if outcome == "delivered" else log.warning)(f"Callback {status}")
    return status


def run(r, settings, stop=None):
    """Delivery loop for one thread."""
    stop = stop or threading.Event()
    while not stop.is_set():
        try:
            item = r.brpop(q.WEBHOOK_KEY, timeout=2)
            if item:
                deliver(r, item[1], settings)
        except Exception as e:
            logger.error(f"Webhook delivery loop error: {e}")
            time.sleep(1)


def start(r, settings):
    if not settings.allowed_hosts:
        logger.info("Callbacks disabled (CALLBACK_ALLOWED_HOSTS is empty)")
        return []
    if not settings.secret:
        logger.warning("WEBHOOK_SECRET is empty: callbacks will be sent unsigned")
    threads = []
    for i in range(settings.threads):
        t = threading.Thread(target=run, args=(r, settings), name=f"webhook-{i}", daemon=True)
        t.start()
        threads.append(t)
    logger.info(f"Webhook delivery started ({settings.threads} threads, hosts {settings.allowed_hosts})")
    return threads
