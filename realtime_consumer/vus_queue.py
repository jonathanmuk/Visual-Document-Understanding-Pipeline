"""Shared queue operations for the worker and the reaper.

Redis layout:

    ocr_tasks               waiting queue. Producer LPUSHes to the head; consumers
                            take from the tail, so the oldest task goes first.
    ocr_tasks:processing    in-progress list. A task is moved here atomically when
                            claimed, and removed only once it reaches a final state.
    ocr_tasks:dead          dead letter queue. Task IDs that failed for good.
    task:{id}               the task hash: status, filename, extension, data,
                            attempts, claimed_at, result, error, warning.

A task is never in limbo: it is on exactly one of the two lists, or it is
finished. That is what makes recovery possible when a worker dies.
"""
import os
import time

import redis

QUEUE_KEY = "ocr_tasks"
PROCESSING_KEY = "ocr_tasks:processing"
DEAD_KEY = "ocr_tasks:dead"
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


def is_non_retryable(error_text):
    text = error_text or ""
    return any(marker in text for marker in NON_RETRYABLE_MARKERS)


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


def finish_done(r, task_id, result_json, ttl_seconds, warning=None):
    key = task_key(task_id)
    mapping = {"status": "done", "result": result_json, "data": ""}
    if warning:
        mapping["warning"] = warning
    r.hset(key, mapping=mapping)
    r.expire(key, ttl_seconds)
    return r.lrem(PROCESSING_KEY, 0, task_id)


def finish_failed(r, task_id, error, ttl_seconds):
    """Terminal failure. The task goes to the dead letter queue for inspection."""
    key = task_key(task_id)
    r.hset(key, mapping={"status": "failed", "error": str(error)[:2000], "data": ""})
    r.expire(key, ttl_seconds)
    removed = r.lrem(PROCESSING_KEY, 0, task_id)
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
    }
