# 0002. A reliable queue in Redis, with an in-progress list and a reaper

**Status:** Accepted. Recorded 30 September 2026.

## Context

Documents wait in a Redis list until a worker takes one. A worker that takes a
document off a plain list, for example with `BRPOP`, removes it from the list in
the same step. If that worker then dies (out of memory, its machine reclaimed,
scaled down), the document is simply gone: nobody is working on it and nothing
records that it existed. Two more things must hold: a failure must be recorded
as a failure, never reported as a success, and finished work must not fill
memory forever.

GPU workers die more often than ordinary services, because the autoscaler
removes them whenever work runs out.

## Decision

Use the reliable queue pattern:

- A worker takes a document with `BLMOVE`, which moves it from the waiting list
  to an **in-progress list** in one atomic step, and stamps when it did so. A
  document is always on exactly one of the two lists, or finished.
- Only when the result is written (done or failed) is it removed from the
  in-progress list.
- A small, always-running **reaper** looks at the in-progress list. A document
  claimed longer ago than `STALE_AFTER_SECONDS` belongs to a worker that is not
  coming back, so the reaper puts it back in the waiting list, or, after
  `MAX_ATTEMPTS`, moves it to a **dead letter list** with the reason.
- Errors that cannot succeed on a retry (billing, authentication, a corrupt
  file) fail at once instead of being retried.
- Finished results, and waiting documents, expire.

`BLMOVE` is the current form of the older `BRPOPLPUSH`, which Redis has
deprecated since 6.2.

## Consequences

Good:

- A worker dying mid-document never loses the document. The tests kill a worker
  and watch the document finish on the next one.
- Every document ends as `done` or `failed` with a reason; `done` means done.
- The dead letter list shows what failed for good, and why.
- Queue lengths are honest signals for the autoscaler.

Costs:

- A document can be read twice: if a worker is merely slow and passes
  `STALE_AFTER_SECONDS`, the reaper hands it out again. The setting must be
  longer than the slowest document takes (15 minutes by default).
- One more component to run (the reaper), though it is tiny.
- Redis is a single copy. It writes every change to disk and is password
  protected, but a lost disk would lose the queue. It is a queue and a
  short-lived store, not a system of record.

## Alternatives considered

- **Redis Streams with consumer groups.** Built-in acknowledgement and
  reclaiming. A larger rewrite of both sides for the same guarantees; the list
  pattern keeps the existing data layout.
- **A managed queue (Azure Service Bus, Google Pub/Sub).** Strong guarantees,
  but ties the system to one cloud, and KEDA would scale on a different signal
  on each.
