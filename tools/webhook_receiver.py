"""A tiny webhook receiver, for watching callbacks arrive while you learn the system.

It plays the part of the client's application: it accepts the POST the system
sends when a document finishes, checks the signature exactly as a real receiver
should, prints one line per delivery, and lists everything it received at
GET /received. Standard library only.

    WEBHOOK_SECRET=local-webhook-secret python tools/webhook_receiver.py

This is a teaching tool, not part of the system. It is never deployed.
"""
import hashlib
import hmac
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SECRET = os.getenv("WEBHOOK_SECRET", "")
PORT = int(os.getenv("WEBHOOK_PORT", "9000"))
MAX_AGE_SECONDS = 300
RECEIVED = []


def signature_ok(timestamp, body, signature):
    """What any receiver should do: recompute the HMAC and refuse stale requests."""
    if not SECRET:
        return None
    try:
        if abs(time.time() - int(timestamp)) > MAX_AGE_SECONDS:
            return False
    except (TypeError, ValueError):
        return False
    expected = "sha256=" + hmac.new(SECRET.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code, payload):
        data = json.dumps(payload, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        valid = signature_ok(self.headers.get("X-VDU-Timestamp"), body, self.headers.get("X-VDU-Signature"))
        try:
            event = json.loads(body)
        except ValueError:
            event = {}
        entry = {"path": self.path, "task_id": event.get("task_id"), "status": event.get("status"),
                 "signature_valid": valid, "error": event.get("error"),
                 "markdown_characters": len(((event.get("result") or {}).get("markdown")) or "")}
        RECEIVED.append(entry)
        verdict = {True: "signature valid", False: "SIGNATURE INVALID", None: "unsigned (no secret set)"}[valid]
        print(f"received {entry['task_id']}: {entry['status']}, {verdict}", flush=True)
        # A real receiver refuses a bad signature. It still answers 2xx for a
        # good one quickly and does its slow work afterwards.
        self._reply(401 if valid is False else 200, {"ok": valid is not False})

    def do_GET(self):
        if self.path == "/received":
            self._reply(200, RECEIVED)
        elif self.path == "/health":
            self._reply(200, {"ok": True})
        else:
            self._reply(404, {"error": "not found"})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"webhook receiver listening on :{PORT} ({'checking signatures' if SECRET else 'no secret set'})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
