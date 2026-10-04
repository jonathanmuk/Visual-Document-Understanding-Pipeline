"""Webhook delivery against a real local HTTP server."""
import http.server
import json
import threading
import time

import fakeredis
import pytest

import vdu_queue as q
import vdu_webhook as w

SECRET = "test-secret"


class Receiver(http.server.BaseHTTPRequestHandler):
    received = []
    reply = 200
    redirect_to = None

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        # self.headers looks names up case-insensitively, as HTTP requires.
        type(self).received.append({"path": self.path, "headers": self.headers, "body": body})
        if type(self).redirect_to:
            self.send_response(307)
            self.send_header("Location", type(self).redirect_to)
        else:
            self.send_response(type(self).reply)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    Receiver.received, Receiver.reply, Receiver.redirect_to = [], 200, None
    httpd = http.server.HTTPServer(("127.0.0.1", 0), Receiver)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


@pytest.fixture
def r():
    return fakeredis.FakeRedis(decode_responses=True)


def settings(**overrides):
    s = w.Settings()
    s.secret, s.allowed_hosts, s.allow_http = SECRET, ["127.0.0.1"], True
    s.attempts, s.timeout_seconds, s.backoff_seconds = 3, 2, 0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def finished_task(r, task_id, url, status="done"):
    r.hset(q.task_key(task_id), mapping={"status": "processing", "callback_url": url, "attempts": "1"})
    r.lpush(q.PROCESSING_KEY, task_id)
    if status == "done":
        q.finish_done(r, task_id, json.dumps({"markdown": "# Hi", "layout": []}), 3600)
    else:
        q.finish_failed(r, task_id, "document rejected: the PDF has no pages", 3600)
    assert r.rpop(q.WEBHOOK_KEY) == task_id


def test_delivers_a_signed_result(r, server):
    finished_task(r, "t1", server + "/hook")
    status = w.deliver(r, "t1", settings())
    assert status == "delivered (HTTP 200)"
    assert r.hget(q.task_key("t1"), "callback_status") == status

    got = Receiver.received[0]
    body = json.loads(got["body"])
    assert got["path"] == "/hook"
    assert body == {"task_id": "t1", "status": "done", "result": {"markdown": "# Hi", "layout": []}}
    assert w.verify(SECRET, got["headers"][w.TIMESTAMP_HEADER], got["body"], got["headers"][w.SIGNATURE_HEADER])


def test_failure_is_delivered_too(r, server):
    finished_task(r, "t1", server, status="failed")
    w.deliver(r, "t1", settings())
    body = json.loads(Receiver.received[0]["body"])
    assert body["status"] == "failed"
    assert "no pages" in body["error"]
    assert "result" not in body


def test_retries_then_records_the_failure(r, server):
    Receiver.reply = 500
    finished_task(r, "t1", server)
    status = w.deliver(r, "t1", settings())
    assert status == "failed after 3 attempts: HTTP 500"
    assert len(Receiver.received) == 3


def test_does_not_follow_redirects(r, server):
    Receiver.redirect_to = "http://169.254.169.254/latest/meta-data"
    finished_task(r, "t1", server)
    status = w.deliver(r, "t1", settings(attempts=1))
    assert status == "failed after 1 attempts: HTTP 307"
    assert len(Receiver.received) == 1


def test_host_is_checked_again_at_delivery(r, server):
    finished_task(r, "t1", server)
    status = w.deliver(r, "t1", settings(allowed_hosts=["hooks.example.com"]))
    assert status.startswith("failed: callback host is not in")
    assert Receiver.received == []


def test_unreachable_host_is_recorded_not_raised(r):
    finished_task(r, "t1", "http://127.0.0.1:1/hook")
    assert w.deliver(r, "t1", settings(attempts=1)).startswith("failed after 1 attempts:")


def test_expired_task_is_not_recreated(r, server):
    finished_task(r, "t1", server)
    r.delete(q.task_key("t1"))
    assert w.deliver(r, "t1", settings()) is None
    assert not r.exists(q.task_key("t1"))


def test_signature_rules():
    body, ts = b'{"a":1}', str(int(time.time()))
    sig = w.sign(SECRET, ts, body)
    assert w.verify(SECRET, ts, body, sig)
    assert not w.verify("other-secret", ts, body, sig), "wrong secret"
    assert not w.verify(SECRET, ts, b'{"a":2}', sig), "tampered body"
    assert not w.verify(SECRET, str(int(ts) - 3600), body, w.sign(SECRET, str(int(ts) - 3600), body)), "replayed"
    assert not w.verify(SECRET, "not-a-number", body, sig)


def test_host_rules_match_the_api():
    s = settings(allowed_hosts=["hooks.example.com", "*.corp.example"], allow_http=False)
    assert w.host_allowed("https://hooks.example.com/x", s)
    assert w.host_allowed("https://a.b.corp.example/x", s)
    assert not w.host_allowed("https://corp.example/x", s)
    assert not w.host_allowed("https://hooks.example.com.evil.net/x", s)
    assert not w.host_allowed("http://hooks.example.com/x", s), "https only unless allowed"


def test_start_does_nothing_when_callbacks_are_off(r):
    assert w.start(r, settings(allowed_hosts=[])) == []
