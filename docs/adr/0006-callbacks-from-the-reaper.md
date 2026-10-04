# 0006. Deliver callbacks from the reaper, signed, to listed hosts only

**Status:** Accepted. Recorded 30 September 2026.

## Context

Clients learn that a document is finished by asking again and again. That wastes
their effort and the gateway's rate limit (every status check counts as a call).
A callback, where the system calls the client's address when the result is
ready, removes the polling. But a callback is an outbound request to an address
the client chose, which is dangerous on both ends:

- Pointed at an internal address, it lets any client make the cluster call its
  own services (server-side request forgery).
- A receiver cannot tell a genuine callback from a forged or replayed one.
- A slow or unreachable receiver must not hold up the expensive GPU worker.

## Decision

- **Off unless allowed.** Callbacks work only for hosts listed in
  `CALLBACK_ALLOWED_HOSTS` (exact names, or `*.example.com`). The list is empty
  by default. Only https is accepted, unless plain http is explicitly allowed
  for testing.
- **Checked twice.** The API checks the address when the document is uploaded,
  and the sender checks it again just before calling, in case the list changed.
  Redirects are never followed, because a redirect could lead somewhere not on
  the list.
- **Sent by the reaper, not the worker.** When a task with a callback finishes,
  its ID goes on a list; delivery threads in the always-running reaper send it.
  The GPU worker never waits on a client.
- **Signed.** Each call carries a timestamp and an HMAC-SHA256 signature of the
  timestamp and the body, made with `WEBHOOK_SECRET`. The receiver recomputes it
  with the same secret and rejects a mismatch or an old timestamp.
- **Recorded.** The task's `callback_status` says `delivered`, or `failed` with
  the reason, so a missed callback is visible to the client when it next asks.

## Consequences

Good:

- Clients can stop polling, which also saves gateway quota.
- The system cannot be steered into calling internal addresses.
- Receivers can prove a callback is genuine and fresh.

Costs:

- Delivery is tried a few times, not guaranteed: if the reaper restarts in the
  middle of a delivery, that callback is lost. The result is still there to be
  fetched, and `callback_status` shows what happened.
- Receivers must implement the signature check (the example in
  `tools/webhook_receiver.py` shows how).
- The operator must maintain the host list.

## Alternatives considered

- **Callbacks from the worker.** Simpler, but a slow receiver would hold a GPU.
- **Any host allowed.** The server-side request forgery above.
- **A durable outbox with retries across restarts.** Stronger delivery, more
  machinery. Worth adding if clients come to depend on callbacks alone.
