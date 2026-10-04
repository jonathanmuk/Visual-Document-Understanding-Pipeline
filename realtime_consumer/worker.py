import asyncio
import json
import logging
import os
import sys
import tempfile
import threading
import time

from loguru import logger

import vdu_inspect
import vdu_metrics
import vdu_profiles
import vdu_queue as q

DEFAULT_SHM_DIR = "/dev/shm"
DEFAULT_HEARTBEAT_PATH = "/tmp/worker-heartbeat"


class Settings:
    def __init__(self):
        self.max_batch_size = int(os.getenv("MAX_BATCH_SIZE", "4"))
        self.window_ms = int(os.getenv("BATCH_WINDOW_MS", "100"))
        self.max_attempts = int(os.getenv("MAX_ATTEMPTS", "3"))
        self.result_ttl_seconds = int(os.getenv("RESULT_TTL_SECONDS", "86400"))
        self.shm_dir = os.getenv("SHM_DIR", DEFAULT_SHM_DIR)
        self.heartbeat_path = os.getenv("HEARTBEAT_PATH", DEFAULT_HEARTBEAT_PATH)
        self.limits = vdu_inspect.Limits()


def configure_logging():
    logger.remove()
    if os.getenv("LOG_FORMAT", "text").lower() == "json":
        logger.add(sys.stderr, serialize=True)
    else:
        logger.add(sys.stderr)


def make_engine(config_path):
    # Imported here so the module can be loaded, and tested, without the SDK.
    from glmocr import GlmOcr
    return GlmOcr(config_path=config_path, enable_layout=True)


def prepare_config():
    """Apply the chosen profile to the base config and check the result.

    Refuses to start on a config that would silently drop a kind of region or
    send a region to the model with no instruction.
    """
    base = os.getenv("GLMOCR_CONFIG_PATH", "config.yaml")
    profile = os.getenv("VDU_PROFILE", "default")
    path, data = vdu_profiles.resolve(base, profile, vdu_profiles.PROFILES_DIR, tempfile.gettempdir())
    problems = vdu_profiles.check(data)
    if problems:
        raise SystemExit(f"config for profile '{profile}' is not usable: " + "; ".join(problems))
    maas = bool(((data.get("pipeline") or {}).get("maas") or {}).get("enabled"))
    if maas and profile != "default":
        logger.warning(f"Profile '{profile}' changes prompts and region rules, which Z.ai mode ignores; "
                       "it only takes effect in self-hosted mode")
    logger.info(f"Using profile '{profile}' ({path}), {'Z.ai' if maas else 'self-hosted'} mode")
    return path


class FailedRegionCounter(logging.Handler):
    """Counts regions the SDK failed to transcribe, by listening to its log stream.

    In self-hosted mode the SDK replaces a failed region's text with an empty
    string, and its formatter then drops empty regions from the result. Nothing
    in the returned object shows a region was lost. The only evidence is the
    SDK's own log line for each final failure, so that is what we count.
    """

    FINAL_FAILURE_PREFIXES = ("Received bad status code", "Error during recognition", "Recognition failed")

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.count = 0
        self._lock = threading.Lock()

    def emit(self, record):
        message = record.getMessage()
        if message.startswith(self.FINAL_FAILURE_PREFIXES):
            with self._lock:
                self.count += 1

    def __enter__(self):
        sdk_logger = logging.getLogger("glmocr")
        # The failure lines are WARNING and ERROR. If the SDK was configured
        # quieter than WARNING they would be filtered before reaching any
        # handler, so open the level for the duration of the parse.
        self._saved_level = sdk_logger.level
        if sdk_logger.level > logging.WARNING:
            sdk_logger.setLevel(logging.WARNING)
        sdk_logger.addHandler(self)
        return self

    def __exit__(self, *exc):
        sdk_logger = logging.getLogger("glmocr")
        sdk_logger.removeHandler(self)
        sdk_logger.setLevel(self._saved_level)
        return False


def evaluate_result(res_obj):
    """Decide whether an SDK result is a real success. Returns (error, markdown, layout)."""
    if res_obj is None:
        return "SDK returned no result for this document", "", []
    error = getattr(res_obj, "_error", None)
    if error:
        return str(error), "", []
    markdown = getattr(res_obj, "markdown_result", "") or ""
    layout = getattr(res_obj, "json_result", None) or []
    if not markdown.strip() and not layout:
        return "SDK returned an empty result (no text and no layout)", "", []
    return None, markdown, layout


async def collect_batch(r, first_task_id, max_batch_size, window_ms):
    # Collector window: after the first task, wait briefly for more so the GPU
    # processes several pages in one pass instead of one at a time. Every task
    # taken here is moved to the in-progress list in the same step.
    batch = [first_task_id]
    deadline = time.time() + (window_ms / 1000.0)
    while len(batch) < max_batch_size:
        remaining = deadline - time.time()
        next_task = q.claim_next(r)
        if next_task:
            batch.append(next_task)
        elif remaining > 0:
            await asyncio.sleep(0.01)
        else:
            break
    return batch


async def process_batch(r, engine, task_ids, settings):
    temp_paths = []
    valid = []  # (task_id, attempts)

    try:
        with _stage("prepare"):
            for task_id in task_ids:
                key = q.task_key(task_id)
                task_data = r.hgetall(key)
                if not task_data:
                    # Nothing to process and nothing to report to. Drop the claim.
                    logger.bind(task_id=task_id).error("Task data not found in Redis; removing claim")
                    r.lrem(q.PROCESSING_KEY, 0, task_id)
                    vdu_metrics.TASKS_TOTAL.labels(outcome="orphan").inc()
                    continue

                attempts = q.mark_claimed(r, task_id)
                log = logger.bind(task_id=task_id, attempt=attempts)

                file_bytes = q.read_document(r, task_id, task_data)
                if file_bytes is None:
                    q.finish_failed(r, task_id, "the document is no longer stored; it expired before a "
                                    "worker reached it, so please submit it again", settings.result_ttl_seconds)
                    vdu_metrics.TASKS_TOTAL.labels(outcome="expired").inc()
                    log.error("Task failed: document expired before processing")
                    continue

                ext = task_data.get("extension", "jpg")
                # A bad document fails here, alone, instead of inside the batch.
                problem = vdu_inspect.inspect(file_bytes, ext, settings.limits)
                if problem:
                    q.finish_failed(r, task_id, problem, settings.result_ttl_seconds)
                    vdu_metrics.TASKS_TOTAL.labels(outcome="rejected").inc()
                    log.error(f"Task failed: {problem}")
                    continue

                # /dev/shm is RAM, so the SDK reads the file without touching disk.
                temp_path = os.path.join(settings.shm_dir, f"{task_id}.{ext}")
                with open(temp_path, "wb") as f:
                    f.write(file_bytes)
                # The SDK spawns sub-processes that may run as a different user.
                os.chmod(temp_path, 0o644)

                temp_paths.append(temp_path)
                valid.append((task_id, attempts))

        if not valid:
            return

        vdu_metrics.BATCH_SIZE.observe(len(valid))
        logger.info(f"Dispatching batch of {len(valid)} to SDK engine")

        with _stage("parse"), FailedRegionCounter() as failed_regions:
            results = await asyncio.to_thread(engine.parse, temp_paths)
        if not isinstance(results, list):
            results = [results]

        warning = None
        if failed_regions.count:
            vdu_metrics.REGIONS_FAILED_TOTAL.inc(failed_regions.count)
            warning = (
                f"{failed_regions.count} region(s) in this batch of {len(valid)} document(s) "
                f"failed to transcribe and were dropped from the output; this document may be incomplete"
            )

        with _stage("write"):
            for i, (task_id, attempts) in enumerate(valid):
                res_obj = results[i] if i < len(results) else None
                error, markdown, layout = evaluate_result(res_obj)
                log = logger.bind(task_id=task_id, attempt=attempts)
                if error:
                    action = q.handle_failure(r, task_id, error, attempts, settings.max_attempts, settings.result_ttl_seconds)
                    vdu_metrics.TASKS_TOTAL.labels(outcome=action).inc()
                    log.error(f"Task {action}: {error}")
                    continue
                result_json = json.dumps({"markdown": markdown, "layout": layout})
                removed = q.finish_done(r, task_id, result_json, settings.result_ttl_seconds, warning)
                vdu_metrics.TASKS_TOTAL.labels(outcome="done").inc()
                if removed == 0:
                    log.warning("Task completed but was no longer on the in-progress list (recovered by the reaper meanwhile?)")
                log.info("Task done" + (" with warning" if warning else ""))

    except Exception as e:
        logger.error(f"Batch processing failed: {e}")
        for task_id, attempts in valid:
            action = q.handle_failure(r, task_id, e, attempts, settings.max_attempts, settings.result_ttl_seconds)
            vdu_metrics.TASKS_TOTAL.labels(outcome=action).inc()
            logger.bind(task_id=task_id, attempt=attempts).error(f"Task {action}: {e}")
    finally:
        for path in temp_paths:
            if os.path.exists(path):
                os.remove(path)


class _stage:
    def __init__(self, name):
        self.name = name

    def __enter__(self):
        self.t0 = time.perf_counter()

    def __exit__(self, *exc):
        vdu_metrics.STAGE_SECONDS.labels(stage=self.name).observe(time.perf_counter() - self.t0)
        return False


def touch(path):
    with open(path, "a"):
        os.utime(path, None)


async def heartbeat(path, interval_seconds=5):
    # Runs on the event loop, which stays responsive during a long parse because
    # the parse happens in a thread. So a fresh heartbeat means the process is
    # alive and not deadlocked, which is what the liveness probe checks.
    while True:
        try:
            touch(path)
        except OSError as e:
            logger.warning(f"Could not touch heartbeat file {path}: {e}")
        await asyncio.sleep(interval_seconds)


async def worker_loop(r, engine, settings):
    logger.info(
        f"Starting worker (max batch {settings.max_batch_size}, window {settings.window_ms}ms, "
        f"max attempts {settings.max_attempts}, result TTL {settings.result_ttl_seconds}s)"
    )
    # Keep the reference: asyncio may drop a task nothing points to.
    heartbeat_task = asyncio.create_task(heartbeat(settings.heartbeat_path))

    while True:
        try:
            # Blocks until a task arrives, so an idle worker does not spin.
            first = await asyncio.to_thread(q.claim_first, r, 2)
            if not first:
                continue
            batch = await collect_batch(r, first, settings.max_batch_size, settings.window_ms)
            # One batch at a time, so the T4's VRAM is never shared between batches.
            await process_batch(r, engine, batch, settings)
        except Exception as e:
            logger.error(f"Worker loop error: {e}")
            await asyncio.sleep(1)
            if heartbeat_task.done():
                heartbeat_task = asyncio.create_task(heartbeat(settings.heartbeat_path))


def main():
    configure_logging()
    settings = Settings()
    r = q.make_redis()
    engine = make_engine(prepare_config())
    port = vdu_metrics.serve()
    logger.info(f"Metrics on :{port}/metrics")
    asyncio.run(worker_loop(r, engine, settings))


if __name__ == "__main__":
    main()
