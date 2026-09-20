"""The reaper: puts back tasks whose worker died, and gives up on the hopeless ones.

A worker claims a task by moving it onto the in-progress list and stamping
claimed_at. If the worker is killed mid-task (out of memory, node eviction,
scale-down), the entry stays on that list with a claimed_at that keeps getting
older. This loop looks for those and either sends them back to the waiting queue
or, once they have used up their attempts, to the dead letter queue.

It also publishes the depth of every queue as metrics, because it is the one
process guaranteed to be running when the workers are scaled to zero.
"""
import os
import sys
import time

from loguru import logger

import vus_metrics
import vus_queue as q


class Settings:
    def __init__(self):
        self.interval_seconds = int(os.getenv("REAPER_INTERVAL_SECONDS", "30"))
        # Must be longer than the longest document you expect a worker to take,
        # or the reaper will requeue work that is still in progress.
        self.stale_after_seconds = int(os.getenv("STALE_AFTER_SECONDS", "900"))
        self.max_attempts = int(os.getenv("MAX_ATTEMPTS", "3"))
        self.result_ttl_seconds = int(os.getenv("RESULT_TTL_SECONDS", "86400"))


def sweep(r, settings, now=None):
    """One pass over the in-progress list. Returns a summary of actions taken."""
    now = time.time() if now is None else now
    actions = {"requeued": 0, "dead_lettered": 0, "orphan_removed": 0, "healthy": 0}

    for task_id in r.lrange(q.PROCESSING_KEY, 0, -1):
        task = r.hgetall(q.task_key(task_id))
        log = logger.bind(task_id=task_id)

        if not task:
            # The hash expired or never existed. Nothing to recover, nothing to tell.
            r.lrem(q.PROCESSING_KEY, 0, task_id)
            actions["orphan_removed"] += 1
            log.warning("In-progress entry with no task data; removed")
            continue

        claimed_at = float(task.get("claimed_at") or 0)
        age = now - claimed_at
        if age < settings.stale_after_seconds:
            actions["healthy"] += 1
            continue

        attempts = int(task.get("attempts") or 0)
        reason = f"abandoned by its worker (no completion after {int(age)}s, attempt {attempts})"
        if attempts >= settings.max_attempts:
            q.finish_failed(r, task_id, f"{reason}; gave up after {attempts} attempts", settings.result_ttl_seconds)
            actions["dead_lettered"] += 1
            log.error(f"Dead-lettered: {reason}")
        else:
            q.requeue(r, task_id, reason)
            actions["requeued"] += 1
            log.warning(f"Requeued: {reason}")

    for action, n in actions.items():
        if action != "healthy" and n:
            vus_metrics.REAPER_ACTIONS_TOTAL.labels(action=action).inc(n)
    vus_metrics.record_depths(q.depths(r))
    return actions


def main():
    logger.remove()
    logger.add(sys.stderr, serialize=os.getenv("LOG_FORMAT", "text").lower() == "json")
    settings = Settings()
    r = q.make_redis()
    port = vus_metrics.serve()
    logger.info(
        f"Reaper started (every {settings.interval_seconds}s, stale after {settings.stale_after_seconds}s, "
        f"max attempts {settings.max_attempts}). Metrics on :{port}/metrics"
    )
    while True:
        try:
            summary = sweep(r, settings)
            if summary["requeued"] or summary["dead_lettered"] or summary["orphan_removed"]:
                logger.info(f"Sweep: {summary}")
        except Exception as e:
            logger.error(f"Sweep failed: {e}")
        time.sleep(settings.interval_seconds)


if __name__ == "__main__":
    main()
