"""Shared queue operations for the worker, the reaper, and the demo worker.

Redis layout:

    ocr_tasks               waiting queue. Producer LPUSHes to the head; consumers
                            take from the tail, so the oldest task goes first.
    ocr_tasks:processing    in-progress list. A task is moved here atomically when
                            claimed, and removed only once it reaches a final state.
    ocr_tasks:dead          dead letter queue. Task IDs that failed for good.
    ocr_webhooks            finished tasks whose client asked for a callback.
    task:{id}               the task hash: status, filename, extension, attempts,
                            claimed_at, result, error, warning, cache_key,
                            callback_url, callback_status.
    taskdata:{id}           the document itself, as raw bytes. Deleted as soon as
                            the task reaches a final state.
    cache:{ver}:{profile}:{sha256}
                            points at the task that processed a document with
                            this exact content, so an identical upload can reuse it.

A task is never in limbo: it is on exactly one of the two lists, or it is
finished. That is what makes recovery possible when a worker dies.
"""
import base64
import os
import time

import redis
from redis.client import NEVER_DECODE

QUEUE_KEY = "ocr_tasks"
PROCESSING_KEY = "ocr_tasks:processing"
DEAD_KEY = "ocr_tasks:dead"
WEBHOOK_KEY = "ocr_webhooks"
DEAD_KEEP = 10000

# Z.ai error codes that will never succeed on retry: billing (1113) and
# authentication (1000, 1001, 1003). Matched against the error text because that
# is all the SDK gives us.
NON_RETRYABLE_MARKERS = (
    '"code":"1113"',
    '"code":"1000"',
    '"code":"1001"',
    '"code":"1003"',
    "MissingApiKeyError",
)

# Prefix for errors about the document itself (corrupt, too many pages). The same
# bytes fail the same way every time, so these are never retried either.
REJECTED_PREFIX = "document rejected:"


def make_redis():
    return redis.Redis(
        host=os.getenv("REDIS_HOST", "ocr-redis-service"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        password=os.getenv("REDIS_PASSWORD") or None,
        db=0,
        decode_responses=True,
    )


def task_key(task_id):
    return f"task:{task_id}"


def data_key(task_id):
    return f"taskdata:{task_id}"


def is_non_retryable(error_text):
    text = error_text or ""
    return text.startswith(REJECTED_PREFIX) or any(marker in text for marker in NON_RETRYABLE_MARKERS)


def read_document(r, task_id, task_hash):
    """Return the document's bytes, or None if it is gone.

    The client decodes replies as text, which would mangle a PDF, so this one
    read asks Redis for the raw bytes. Tasks queued by an older API kept the
    document base64-encoded in the hash; those are still read, so an upgrade
    never strands work already waiting.
    """
    raw = r.execute_command("GET", data_key(task_id), **{NEVER_DECODE: []})
    if raw is not None:
        return raw
    legacy = task_hash.get("data")
    if legacy:
        return base64.b64decode(legacy)
    return None


def claim_first(r, timeout_seconds):
    """Block until a task is available, then move it to the in-progress list.

    Uses BLMOVE RIGHT LEFT: pop the oldest from the waiting queue, push onto the
    in-progress list, in one atomic step. (BRPOPLPUSH did the same and is
    deprecated since Redis 6.2.)
    """
    return r.blmove(QUEUE_KEY, PROCESSING_KEY, timeout_seconds, "RIGHT", "LEFT")


def claim_next(r):
    """Non-blocking version of claim_first, for filling a batch."""
    return r.lmove(QUEUE_KEY, PROCESSING_KEY, "RIGHT", "LEFT")


def mark_claimed(r, task_id):
    """Record that a worker has started on this task. Returns the attempt number."""
    key = task_key(task_id)
    attempts = r.hincrby(key, "attempts", 1)
    r.hset(key, mapping={"status": "processing", "claimed_at": f"{time.time():.3f}"})
    return int(attempts)


def _settle_cache(r, task_id, cache_key, keep_seconds):
    """Keep or drop the cache pointer, but only if it still points at this task.

    A clean success keeps it for as long as the result lives. A failure, or a
    success with lost regions, drops it, so the next identical upload gets a
    fresh attempt instead of a replay of a bad answer. The check and the change
    happen in one transaction, so a newer task's pointer is never touched.
    """
    if not cache_key:
        return

    def txn(pipe):
        if pipe.get(cache_key) != task_id:
            return
        pipe.multi()
        if keep_seconds:
            pipe.expire(cache_key, keep_seconds)
        else:
            pipe.delete(cache_key)

    r.transaction(txn, cache_key)


def _finish(r, task_id, mapping, ttl_seconds, keep_cache):
    key = task_key(task_id)
    extra = r.hmget(key, "cache_key", "callback_url")
    cache_key, callback_url = extra[0], extra[1]
    if callback_url:
        mapping["callback_status"] = "pending"
    pipe = r.pipeline()
    pipe.hset(key, mapping=mapping)
    # Older tasks carried the document in the hash; drop it with the rest.
    pipe.hdel(key, "data")
    pipe.expire(key, ttl_seconds)
    pipe.delete(data_key(task_id))
    pipe.lrem(PROCESSING_KEY, 0, task_id)
    if callback_url:
        pipe.lpush(WEBHOOK_KEY, task_id)
    removed = pipe.execute()[4]
    _settle_cache(r, task_id, cache_key, ttl_seconds if keep_cache else None)
    return removed


def finish_done(r, task_id, result_json, ttl_seconds, warning=None):
    mapping = {"status": "done", "result": result_json}
    if warning:
        mapping["warning"] = warning
    return _finish(r, task_id, mapping, ttl_seconds, keep_cache=not warning)


def finish_failed(r, task_id, error, ttl_seconds):
    """Terminal failure. The task goes to the dead letter queue for inspection."""
    removed = _finish(r, task_id, {"status": "failed", "error": str(error)[:2000]}, ttl_seconds, keep_cache=False)
    r.rpush(DEAD_KEY, task_id)
    # The task hashes expire; the ID list would not. Keep the most recent
    # DEAD_KEEP entries so it cannot grow without bound.
    r.ltrim(DEAD_KEY, -DEAD_KEEP, -1)
    return removed


def requeue(r, task_id, error):
    """Put a task back at the front of the waiting queue for another attempt.

    RPUSH puts it at the tail, which is where consumers take from, so a
    recovered task is processed next rather than waiting behind new arrivals.
    """
    key = task_key(task_id)
    r.hset(key, mapping={"status": "queued", "last_error": str(error)[:2000]})
    r.hdel(key, "claimed_at")
    removed = r.lrem(PROCESSING_KEY, 0, task_id)
    r.rpush(QUEUE_KEY, task_id)
    return removed


def handle_failure(r, task_id, error, attempts, max_attempts, ttl_seconds):
    """Decide between another attempt and giving up. Returns the action taken."""
    error_text = str(error)
    if is_non_retryable(error_text):
        finish_failed(r, task_id, f"{error_text} (not retried: this error cannot succeed on retry)", ttl_seconds)
        return "failed"
    if attempts >= max_attempts:
        finish_failed(r, task_id, f"{error_text} (gave up after {attempts} attempts)", ttl_seconds)
        return "failed"
    requeue(r, task_id, error_text)
    return "requeued"


def depths(r):
    return {
        "waiting": r.llen(QUEUE_KEY),
        "processing": r.llen(PROCESSING_KEY),
        "dead": r.llen(DEAD_KEY),
        "webhooks": r.llen(WEBHOOK_KEY),
    }
