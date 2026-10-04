# 0005. Keep documents only until they are read; no archive

**Status:** Accepted. Recorded 30 September 2026.

## Context

A document waits in Redis until a worker reads it. Redis keeps everything in
memory, which is expensive per gigabyte, and every document in it is a copy of
someone's possibly confidential file. Some uses need an audit trail: a record
of exactly which file produced which answer, kept for months or years.

## Decision

Keep each document only as long as it is needed to read it:

- It is stored as raw bytes, in a key of its own, when it is uploaded.
- It is deleted the moment its task is finished, whether done or failed.
- If nobody ever reads it, it expires after `TASK_MAX_AGE_SECONDS` (two days).
- Results expire after `RESULT_TTL_SECONDS` (a day).

There is no archive of source documents or results.

## Consequences

Good:

- Redis memory holds only work in progress, so it stays small and cheap.
- The system holds as little of anyone's data, for as short a time, as it can.

Costs:

- No audit trail. Once a result expires, nothing shows what was read.
- A result cannot be recomputed later from the original file; the client must
  send it again.

## If you need an archive

Have the API also write each upload to object storage (Azure Blob Storage or
Google Cloud Storage) before queueing it, keyed by task ID or by its fingerprint,
with a retention rule that suits your obligations; store the result next to it
when the task finishes. Nothing else in the pipeline needs to change. Decide the
retention period and who may read the archive first: an archive of documents is
itself sensitive data.

## Alternatives considered

- **Keep documents in Redis longer.** Memory is the most expensive place to keep
  them, and Redis is not built as an archive.
- **Always archive.** Adds cost and a store of sensitive data for users who do
  not need it.
