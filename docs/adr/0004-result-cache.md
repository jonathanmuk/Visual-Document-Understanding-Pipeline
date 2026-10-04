# 0004. Cache results by the document's exact content

**Status:** Accepted. Recorded 30 September 2026.

## Context

Document workflows repeat themselves: the same invoice sent twice, the same
form resent after a question, several people uploading the same contract. Each
repeat would start a GPU machine to produce an answer that already exists. Two
identical uploads arriving close together would also both be read.

## Decision

The API takes a fingerprint of every upload (a SHA-256 hash of its bytes) and
keeps a pointer from that fingerprint to the task that read it.

- **Already done:** the stored answer comes straight back, `200` with
  `cached: true`. No worker, no GPU.
- **Waiting or being read right now:** the uploader joins that task, `202` with
  `deduplicated: true`, instead of starting a second one.
- **Asked not to:** a request with `Cache-Control: no-cache` always gets a fresh
  reading. So does one with a callback, so that its callback fires.

The fingerprint's name also contains `PIPELINE_VERSION` and the reading profile,
so changing prompts, rules, or profile never serves an answer made under the old
ones. The worker keeps the pointer only for a clean success, and only as long as
the result itself lives; a failure, or a result with lost regions, removes it,
so the next identical upload gets a fresh attempt instead of a replay of a bad
answer. The pointer is only ever changed if it still points at the task in
question, inside a Redis transaction, so a newer task's pointer is never touched.

## Consequences

Good:

- Repeats cost nothing: in the benchmark, 50 of 50 repeat uploads were answered
  from the cache in about 3 ms each.
- Simultaneous identical uploads are read once.

Costs:

- Byte-identical only. A re-scan of the same page, or a PDF saved again, has
  different bytes and is read again.
- An answer can be served that a newer model would improve on, until
  `PIPELINE_VERSION` is raised or the result expires (a day by default).
- Anyone who can call the API can learn whether a given document was read
  recently, by uploading it and seeing `cached: true`. Inside one team this is
  harmless; between tenants it would not be. Turn the cache off
  (`RESULT_CACHE=false`) or add the caller to the fingerprint if tenants must
  not learn about each other's documents.

## Alternatives considered

- **No cache.** Simple, but pays the GPU for every repeat.
- **Fuzzy matching (similar pages).** Would catch re-scans, but risks returning
  another document's answer. Not worth the risk for invoices and contracts.
