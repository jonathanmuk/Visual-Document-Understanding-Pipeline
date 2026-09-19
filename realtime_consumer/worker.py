import os
import asyncio
import json
import base64
import time
import redis
from loguru import logger

QUEUE_KEY = "ocr_tasks"
DEFAULT_SHM_DIR = "/dev/shm"


def make_redis():
    host = os.getenv("REDIS_HOST", "ocr-redis-service")
    port = int(os.getenv("REDIS_PORT", 6379))
    return redis.Redis(host=host, port=port, db=0, decode_responses=True)


def make_engine():
    # Imported here so the module can be loaded, and tested, without the SDK.
    from glmocr import GlmOcr
    config_path = os.getenv("GLMOCR_CONFIG_PATH", "config.yaml")
    return GlmOcr(config_path=config_path, enable_layout=True)


async def collect_batch(r, first_task_id, max_batch_size, window_ms):
    # Collector window: after the first task, wait briefly for more so the GPU
    # processes several pages in one pass instead of one at a time.
    batch = [first_task_id]
    deadline = time.time() + (window_ms / 1000.0)
    while len(batch) < max_batch_size:
        remaining = deadline - time.time()
        next_task = r.lpop(QUEUE_KEY)
        if next_task:
            batch.append(next_task)
        elif remaining > 0:
            await asyncio.sleep(0.01)
        else:
            break
    return batch


async def process_batch(r, engine, task_ids, shm_dir=DEFAULT_SHM_DIR):
    temp_paths = []
    valid_task_ids = []

    try:
        for task_id in task_ids:
            task_data = r.hgetall(f"task:{task_id}")
            if not task_data:
                logger.error(f"Task {task_id} data not found in Redis.")
                continue

            r.hset(f"task:{task_id}", "status", "processing")

            # /dev/shm is RAM, so the SDK reads the file without touching disk.
            file_bytes = base64.b64decode(task_data['data'])
            ext = task_data.get('extension', 'jpg')
            temp_path = os.path.join(shm_dir, f"{task_id}.{ext}")

            with open(temp_path, "wb") as f:
                f.write(file_bytes)
            # The SDK spawns sub-processes that may run as a different user.
            os.chmod(temp_path, 0o644)

            temp_paths.append(temp_path)
            valid_task_ids.append(task_id)

        if not temp_paths:
            return

        logger.info(f"Dispatching Batch of {len(temp_paths)} to SDK Engine")

        results = await asyncio.to_thread(engine.parse, temp_paths)
        if not isinstance(results, list):
            results = [results]

        for i, task_id in enumerate(valid_task_ids):
            if i >= len(results):
                break

            res_obj = results[i]
            markdown = getattr(res_obj, "markdown_result", "")
            layout = getattr(res_obj, "json_result", {})

            final_result = {"markdown": markdown, "layout": layout}
            r.hset(f"task:{task_id}", mapping={
                "status": "done",
                "result": json.dumps(final_result),
                "data": ""  # the source file is no longer needed; free the memory
            })
            logger.info(f"Task {task_id} completed (Batch Member)")

    except Exception as e:
        logger.error(f"Batch processing failed: {e}")
        for task_id in valid_task_ids:
            r.hset(f"task:{task_id}", mapping={"status": "failed", "error": str(e)})
    finally:
        for path in temp_paths:
            if os.path.exists(path):
                os.remove(path)


async def worker_loop(r, engine, max_batch_size, window_ms, shm_dir=DEFAULT_SHM_DIR):
    logger.info(f"Starting Dynamic Batching Worker (Max Batch: {max_batch_size}, Window: {window_ms}ms)...")

    while True:
        try:
            # brpop blocks until a task arrives, so an idle worker does not spin.
            task_info = r.brpop(QUEUE_KEY, timeout=2)
            if not task_info:
                continue

            _, first_task_id = task_info
            batch = await collect_batch(r, first_task_id, max_batch_size, window_ms)

            # One batch at a time, so the T4's VRAM is never shared between batches.
            await process_batch(r, engine, batch, shm_dir)

        except Exception as e:
            logger.error(f"Worker loop error: {e}")
            await asyncio.sleep(1)


def main():
    r = make_redis()
    engine = make_engine()
    max_batch_size = int(os.getenv("MAX_BATCH_SIZE", "4"))
    window_ms = int(os.getenv("BATCH_WINDOW_MS", "100"))
    asyncio.run(worker_loop(r, engine, max_batch_size, window_ms))


if __name__ == "__main__":
    main()
