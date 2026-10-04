import asyncio
import base64
import json
import logging
import os

import fakeredis
import pytest

import reaper
import vdu_queue as q
import worker

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "fixtures")
PDF = open(os.path.join(FIXTURES, "sample.pdf"), "rb").read()
PNG = open(os.path.join(FIXTURES, "sample.png"), "rb").read()


class StubResult:
    def __init__(self, markdown, layout, error=None):
        self.markdown_result = markdown
        self.json_result = layout
        if error is not None:
            self._error = error


class StubEngine:
    """Stands in for the GLM-OCR SDK. Records what it was asked to parse."""

    def __init__(self, results=None, error=None):
        self.results = results
        self.error = error
        self.calls = []

    def parse(self, paths):
        self.calls.append(list(paths))
        if self.error:
            raise self.error
        if callable(self.results):
            return self.results(paths)
        return self.results


@pytest.fixture
def r():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def settings(tmp_path):
    s = worker.Settings()
    s.shm_dir = str(tmp_path)
    s.max_attempts = 3
    s.result_ttl_seconds = 3600
    return s


def enqueue(r, task_id, content=PDF, ext="pdf", cache_key=None, callback_url=None):
    """What the API writes: the task hash, the raw document, the queue entry."""
    fields = {"status": "queued", "filename": f"{task_id}.{ext}", "extension": ext, "attempts": "0"}
    if cache_key:
        fields["cache_key"] = cache_key
        r.set(cache_key, task_id, ex=172800)
    if callback_url:
        fields["callback_url"] = callback_url
    r.hset(q.task_key(task_id), mapping=fields)
    r.set(q.data_key(task_id), content)
    r.lpush(q.QUEUE_KEY, task_id)


def enqueue_legacy(r, task_id, content=PDF, ext="pdf"):
    """The older task format: the document base64-encoded inside the task hash."""
    r.hset(q.task_key(task_id), mapping={
        "status": "queued", "filename": f"{task_id}.{ext}", "extension": ext,
        "data": base64.b64encode(content).decode(), "attempts": "0",
    })
    r.lpush(q.QUEUE_KEY, task_id)


def claim(r, task_id):
    """Simulate what worker_loop does before process_batch: the task is on the in-progress list."""
    got = q.claim_first(r, 1)
    assert got == task_id
    return got


def run(coro):
    return asyncio.run(coro)


# --- claiming and the collector window -------------------------------------------

def test_claim_first_moves_oldest_task_to_processing(r):
    for i in range(3):
        enqueue(r, f"t{i}")           # t0 is oldest
    got = q.claim_first(r, 1)
    assert got == "t0"
    assert r.lrange(q.PROCESSING_KEY, 0, -1) == ["t0"]
    assert r.llen(q.QUEUE_KEY) == 2


def test_collect_batch_fills_oldest_first_and_moves_all_to_processing(r):
    for i in range(6):
        enqueue(r, f"t{i}")
    first = q.claim_first(r, 1)
    batch = run(worker.collect_batch(r, first, max_batch_size=4, window_ms=100))
    assert batch == ["t0", "t1", "t2", "t3"], "oldest first, consistently"
    assert sorted(r.lrange(q.PROCESSING_KEY, 0, -1)) == sorted(batch)
    assert r.lrange(q.QUEUE_KEY, 0, -1) == ["t5", "t4"]


def test_collect_batch_returns_partial_when_queue_drains(r):
    enqueue(r, "a"); enqueue(r, "b")
    first = q.claim_first(r, 1)
    batch = run(worker.collect_batch(r, first, max_batch_size=4, window_ms=50))
    assert batch == ["a", "b"]


def test_collect_batch_with_single_task_waits_out_the_window(r):
    batch = run(worker.collect_batch(r, "only", max_batch_size=4, window_ms=30))
    assert batch == ["only"]


# --- the happy path ---------------------------------------------------------------

def test_success_writes_result_sets_ttl_and_clears_claim(r, settings, tmp_path):
    enqueue(r, "t1"); claim(r, "t1")
    engine = StubEngine(results=[StubResult("# Hello", [{"label": "text"}])])

    run(worker.process_batch(r, engine, ["t1"], settings))

    task = r.hgetall(q.task_key("t1"))
    assert task["status"] == "done"
    assert "data" not in task
    assert not r.exists(q.data_key("t1")), "the document is deleted once the task is final"
    assert task["attempts"] == "1"
    assert json.loads(task["result"]) == {"markdown": "# Hello", "layout": [{"label": "text"}]}
    assert "warning" not in task
    assert 0 < r.ttl(q.task_key("t1")) <= 3600, "result must expire"
    assert r.llen(q.PROCESSING_KEY) == 0, "claim must be released"
    assert r.llen(q.DEAD_KEY) == 0
    assert not os.listdir(tmp_path), "temp file must be removed"


def test_temp_file_uses_stored_extension_and_exact_bytes(r, settings, tmp_path):
    enqueue(r, "img1", content=PNG, ext="png"); claim(r, "img1")
    seen = {}

    def capture(paths):
        seen["path"] = paths[0]
        seen["bytes"] = open(paths[0], "rb").read()
        return [StubResult("x", [])]

    run(worker.process_batch(r, StubEngine(results=capture), ["img1"], settings))
    assert seen["path"] == os.path.join(str(tmp_path), "img1.png")
    assert seen["bytes"] == PNG, "binary bytes survive the round trip through Redis untouched"


def test_task_queued_by_an_older_api_is_still_processed(r, settings):
    enqueue_legacy(r, "old", content=PNG, ext="png"); claim(r, "old")
    seen = {}

    def capture(paths):
        seen["bytes"] = open(paths[0], "rb").read()
        return [StubResult("x", [])]

    run(worker.process_batch(r, StubEngine(results=capture), ["old"], settings))
    assert seen["bytes"] == PNG
    task = r.hgetall(q.task_key("old"))
    assert task["status"] == "done"
    assert "data" not in task, "the base64 copy is removed with the rest"


def test_expired_document_fails_once_with_a_clear_reason(r, settings):
    enqueue(r, "t1"); claim(r, "t1")
    r.delete(q.data_key("t1"))
    engine = StubEngine(results=[])
    run(worker.process_batch(r, engine, ["t1"], settings))
    task = r.hgetall(q.task_key("t1"))
    assert task["status"] == "failed"
    assert "no longer stored" in task["error"]
    assert engine.calls == [], "nothing to send to the model"
    assert r.llen(q.QUEUE_KEY) == 0, "not retried: the bytes will not come back"


def test_corrupt_document_is_rejected_alone_and_the_rest_of_the_batch_runs(r, settings, tmp_path):
    enqueue(r, "bad", content=b"%PDF-1.7\n" + b"\x00" * 300)
    enqueue(r, "good")
    q.claim_first(r, 1); q.claim_first(r, 1)
    engine = StubEngine(results=[StubResult("fine", [])])

    run(worker.process_batch(r, engine, ["bad", "good"], settings))

    bad = r.hgetall(q.task_key("bad"))
    assert bad["status"] == "failed"
    assert bad["error"].startswith("document rejected: the PDF could not be opened")
    assert bad["attempts"] == "1", "a corrupt file fails the same way every time, so it is not retried"
    assert r.lrange(q.DEAD_KEY, 0, -1) == ["bad"]
    assert engine.calls == [[os.path.join(str(tmp_path), "good.pdf")]], "only the good document reaches the model"
    assert r.hget(q.task_key("good"), "status") == "done"
    assert r.llen(q.PROCESSING_KEY) == 0


def test_pdf_over_the_page_limit_is_rejected_before_the_model(r, settings):
    settings.limits.max_pdf_pages = 0
    enqueue(r, "t1"); claim(r, "t1")
    engine = StubEngine(results=[])
    run(worker.process_batch(r, engine, ["t1"], settings))
    assert "pages; the limit is 0" in r.hget(q.task_key("t1"), "error")
    assert engine.calls == []


# --- the result cache pointer ---------------------------------------------------

def test_clean_success_keeps_the_cache_pointer_for_the_result_lifetime(r, settings):
    enqueue(r, "t1", cache_key="cache:1:default:abc"); claim(r, "t1")
    run(worker.process_batch(r, StubEngine(results=[StubResult("ok", [])]), ["t1"], settings))
    assert r.get("cache:1:default:abc") == "t1"
    assert 0 < r.ttl("cache:1:default:abc") <= settings.result_ttl_seconds, "never outlives the result"


def test_success_with_lost_regions_drops_the_cache_pointer(r, settings):
    enqueue(r, "t1", cache_key="cache:1:default:abc"); claim(r, "t1")

    def parse(paths):
        logging.getLogger("glmocr.ocr_client").warning("Received bad status code: 503, response: busy")
        return [StubResult("partial", [])]

    run(worker.process_batch(r, StubEngine(results=parse), ["t1"], settings))
    assert r.hget(q.task_key("t1"), "status") == "done"
    assert not r.exists("cache:1:default:abc"), "an incomplete answer must not be replayed to the next uploader"


def test_failure_drops_the_cache_pointer(r, settings):
    enqueue(r, "t1", cache_key="cache:1:default:abc"); claim(r, "t1")
    res = StubResult("", [], error='status 401: {"error":{"code":"1000"}}')
    run(worker.process_batch(r, StubEngine(results=[res]), ["t1"], settings))
    assert not r.exists("cache:1:default:abc")


def test_a_newer_tasks_cache_pointer_is_never_touched(r, settings):
    enqueue(r, "t1", cache_key="cache:1:default:abc"); claim(r, "t1")
    r.set("cache:1:default:abc", "t2", ex=500)   # a fresh re-run took over the key meanwhile
    res = StubResult("", [], error='status 401: {"error":{"code":"1000"}}')
    run(worker.process_batch(r, StubEngine(results=[res]), ["t1"], settings))
    assert r.get("cache:1:default:abc") == "t2"


def test_finishing_a_task_with_a_callback_queues_the_webhook(r, settings):
    enqueue(r, "t1", callback_url="https://hooks.example.com/x"); claim(r, "t1")
    enqueue(r, "t2"); claim(r, "t2")
    engine = StubEngine(results=[StubResult("ok", [])])
    run(worker.process_batch(r, engine, ["t1"], settings))
    run(worker.process_batch(r, engine, ["t2"], settings))
    assert r.lrange(q.WEBHOOK_KEY, 0, -1) == ["t1"], "only tasks that asked for a callback"
    assert r.hget(q.task_key("t1"), "callback_status") == "pending"
    assert r.hget(q.task_key("t2"), "callback_status") is None


def test_status_is_processing_and_claimed_at_set_during_parse(r, settings):
    enqueue(r, "t1"); claim(r, "t1")
    seen = {}

    def capture(paths):
        seen["status"] = r.hget(q.task_key("t1"), "status")
        seen["claimed_at"] = r.hget(q.task_key("t1"), "claimed_at")
        return [StubResult("x", [])]

    run(worker.process_batch(r, StubEngine(results=capture), ["t1"], settings))
    assert seen["status"] == "processing"
    assert float(seen["claimed_at"]) > 0


def test_unknown_task_claim_is_dropped_and_rest_processed(r, settings, tmp_path):
    enqueue(r, "real"); claim(r, "real")
    r.lpush(q.PROCESSING_KEY, "ghost")   # a claim with no task data
    engine = StubEngine(results=[StubResult("ok", [])])

    run(worker.process_batch(r, engine, ["ghost", "real"], settings))

    assert engine.calls == [[os.path.join(str(tmp_path), "real.pdf")]]
    assert r.hget(q.task_key("real"), "status") == "done"
    assert r.llen(q.PROCESSING_KEY) == 0, "the ghost claim must be removed too"


def test_single_result_object_is_accepted(r, settings):
    enqueue(r, "t1"); claim(r, "t1")
    run(worker.process_batch(r, StubEngine(results=StubResult("solo", [])), ["t1"], settings))
    assert r.hget(q.task_key("t1"), "status") == "done"


# --- failures are reported as failures --------------------------------------------

def test_sdk_error_attribute_is_reported_as_failure(r, settings):
    enqueue(r, "t1"); claim(r, "t1")
    res = StubResult("", [], error='MaaS API request failed with status 429: {"error":{"code":"1113"}}')
    run(worker.process_batch(r, StubEngine(results=[res]), ["t1"], settings))
    task = r.hgetall(q.task_key("t1"))
    assert task["status"] == "failed"
    assert "1113" in task["error"]
    assert "not retried" in task["error"], "billing errors must not be retried"
    assert r.lrange(q.DEAD_KEY, 0, -1) == ["t1"]
    assert r.llen(q.PROCESSING_KEY) == 0


def test_empty_result_is_a_failure_not_a_success(r, settings):
    enqueue(r, "t1"); claim(r, "t1")
    run(worker.process_batch(r, StubEngine(results=[StubResult("", [])]), ["t1"], settings))
    task = r.hgetall(q.task_key("t1"))
    assert task["status"] == "queued", "an empty result is retryable, so first attempt requeues"
    assert "empty result" in task["last_error"]
    assert r.lrange(q.QUEUE_KEY, 0, -1) == ["t1"]


def test_fewer_results_than_tasks_never_leaves_a_task_at_processing(r, settings):
    enqueue(r, "t1"); enqueue(r, "t2")
    q.claim_first(r, 1); q.claim_first(r, 1)
    run(worker.process_batch(r, StubEngine(results=[StubResult("only one", [])]), ["t1", "t2"], settings))
    assert r.hget(q.task_key("t1"), "status") == "done"
    assert r.hget(q.task_key("t2"), "status") in ("queued", "failed")
    assert "no result" in r.hget(q.task_key("t2"), "last_error")
    assert r.llen(q.PROCESSING_KEY) == 0


def test_engine_exception_requeues_then_dead_letters_after_max_attempts(r, settings):
    enqueue(r, "t1")
    engine = StubEngine(error=RuntimeError("GPU exploded"))

    # Attempts 1 and 2: requeued.
    for expected_attempt in (1, 2):
        claim(r, "t1")
        run(worker.process_batch(r, engine, ["t1"], settings))
        task = r.hgetall(q.task_key("t1"))
        assert task["status"] == "queued", f"attempt {expected_attempt} should requeue"
        assert task["attempts"] == str(expected_attempt)
        assert r.lrange(q.QUEUE_KEY, 0, -1) == ["t1"]
        assert r.llen(q.PROCESSING_KEY) == 0

    # Attempt 3: gives up.
    claim(r, "t1")
    run(worker.process_batch(r, engine, ["t1"], settings))
    task = r.hgetall(q.task_key("t1"))
    assert task["status"] == "failed"
    assert "gave up after 3 attempts" in task["error"]
    assert r.lrange(q.DEAD_KEY, 0, -1) == ["t1"]
    assert r.llen(q.QUEUE_KEY) == 0
    assert r.llen(q.PROCESSING_KEY) == 0


def test_auth_error_is_never_retried(r, settings):
    enqueue(r, "t1"); claim(r, "t1")
    engine = StubEngine(error=ValueError('status 401: {"error":{"code":"1000","message":"Authentication Failed"}}'))
    run(worker.process_batch(r, engine, ["t1"], settings))
    task = r.hgetall(q.task_key("t1"))
    assert task["status"] == "failed"
    assert task["attempts"] == "1"
    assert r.lrange(q.DEAD_KEY, 0, -1) == ["t1"]


def test_failed_regions_in_self_hosted_mode_produce_a_warning(r, settings):
    enqueue(r, "t1"); claim(r, "t1")
    sdk_log = logging.getLogger("glmocr.ocr_client")

    def parse_with_failures(paths):
        # What the SDK logs when two regions fail for good, and one retry that must not count.
        sdk_log.warning("Received status 503 from OCR API (attempt 1/3). Retrying...")
        sdk_log.warning("Received bad status code: 503, response: overloaded")
        sdk_log.error("Error during recognition: connection reset")
        return [StubResult("partial text", [{"label": "text"}])]

    run(worker.process_batch(r, StubEngine(results=parse_with_failures), ["t1"], settings))
    task = r.hgetall(q.task_key("t1"))
    assert task["status"] == "done", "partial output is still delivered"
    assert task["warning"].startswith("2 region(s) in this batch")


def test_failed_regions_are_counted_even_when_sdk_logger_is_quiet(r, settings):
    enqueue(r, "t1"); claim(r, "t1")
    sdk = logging.getLogger("glmocr")
    sdk.setLevel(logging.ERROR)          # as if config.yaml said logging.level: ERROR
    try:
        def parse(paths):
            logging.getLogger("glmocr.ocr_client").warning("Received bad status code: 500, response: x")
            return [StubResult("text", [])]
        run(worker.process_batch(r, StubEngine(results=parse), ["t1"], settings))
        assert r.hget(q.task_key("t1"), "warning").startswith("1 region(s)")
        assert sdk.level == logging.ERROR, "the SDK logger level must be restored"
    finally:
        sdk.setLevel(logging.NOTSET)


def test_dead_letter_queue_is_bounded(r):
    for i in range(q.DEAD_KEEP + 50):
        r.rpush(q.DEAD_KEY, f"old{i}")
    q.finish_failed(r, "newest", "boom", 60)
    assert r.llen(q.DEAD_KEY) == q.DEAD_KEEP
    assert r.lrange(q.DEAD_KEY, -1, -1) == ["newest"], "newest entry kept, oldest dropped"


def test_evaluate_result_cases():
    assert worker.evaluate_result(None)[0].startswith("SDK returned no result")
    assert worker.evaluate_result(StubResult("", [], error="boom"))[0] == "boom"
    assert worker.evaluate_result(StubResult("   ", []))[0].startswith("SDK returned an empty result")
    assert worker.evaluate_result(StubResult("text", []))[0] is None
    assert worker.evaluate_result(StubResult("", [{"label": "image"}]))[0] is None


# --- the reaper -----------------------------------------------------------------------

def test_reaper_leaves_fresh_claims_alone(r):
    enqueue(r, "t1"); claim(r, "t1"); q.mark_claimed(r, "t1")
    s = reaper.Settings(); s.stale_after_seconds = 900
    summary = reaper.sweep(r, s)
    assert summary == {"requeued": 0, "dead_lettered": 0, "orphan_removed": 0, "healthy": 1}
    assert r.lrange(q.PROCESSING_KEY, 0, -1) == ["t1"]


def test_reaper_requeues_a_stale_claim(r):
    enqueue(r, "t1"); claim(r, "t1"); q.mark_claimed(r, "t1")
    s = reaper.Settings(); s.stale_after_seconds = 900; s.max_attempts = 3
    far_future = float(r.hget(q.task_key("t1"), "claimed_at")) + 1000
    summary = reaper.sweep(r, s, now=far_future)
    assert summary["requeued"] == 1
    task = r.hgetall(q.task_key("t1"))
    assert task["status"] == "queued"
    assert "abandoned" in task["last_error"]
    assert "claimed_at" not in task
    assert r.lrange(q.QUEUE_KEY, 0, -1) == ["t1"]
    assert r.llen(q.PROCESSING_KEY) == 0


def test_reaper_dead_letters_after_max_attempts(r):
    enqueue(r, "t1"); claim(r, "t1")
    for _ in range(3):
        q.mark_claimed(r, "t1")          # attempts -> 3
    s = reaper.Settings(); s.stale_after_seconds = 900; s.max_attempts = 3
    far_future = float(r.hget(q.task_key("t1"), "claimed_at")) + 1000
    summary = reaper.sweep(r, s, now=far_future)
    assert summary["dead_lettered"] == 1
    task = r.hgetall(q.task_key("t1"))
    assert task["status"] == "failed"
    assert "gave up after 3 attempts" in task["error"]
    assert r.lrange(q.DEAD_KEY, 0, -1) == ["t1"]
    assert 0 < r.ttl(q.task_key("t1"))


def test_reaper_dead_letter_cleans_up_document_and_cache_pointer(r):
    enqueue(r, "t1", cache_key="cache:1:default:abc"); claim(r, "t1")
    for _ in range(3):
        q.mark_claimed(r, "t1")
    s = reaper.Settings(); s.stale_after_seconds = 900; s.max_attempts = 3
    reaper.sweep(r, s, now=float(r.hget(q.task_key("t1"), "claimed_at")) + 1000)
    assert not r.exists(q.data_key("t1"))
    assert not r.exists("cache:1:default:abc"), "the next identical upload must get a fresh try"


def test_reaper_treats_missing_claimed_at_as_stale(r):
    # Worker died between claiming and stamping. Age is effectively infinite.
    enqueue(r, "t1"); claim(r, "t1")
    s = reaper.Settings(); s.stale_after_seconds = 900
    assert reaper.sweep(r, s)["requeued"] == 1


def test_reaper_removes_orphan_claims(r):
    r.lpush(q.PROCESSING_KEY, "ghost")
    s = reaper.Settings()
    assert reaper.sweep(r, s)["orphan_removed"] == 1
    assert r.llen(q.PROCESSING_KEY) == 0


# --- kill a worker mid-batch: the recovery acceptance test ----------------------------

def test_worker_killed_mid_batch_task_still_completes(r, settings):
    """The plan's 'done when': a worker dies holding a task, and the task still completes."""
    enqueue(r, "t1")
    claim(r, "t1")
    q.mark_claimed(r, "t1")
    # Worker dies here. Nothing else happens to the task.
    assert r.hget(q.task_key("t1"), "status") == "processing"

    # Reaper notices, after the stale threshold.
    s = reaper.Settings(); s.stale_after_seconds = 900
    reaper.sweep(r, s, now=float(r.hget(q.task_key("t1"), "claimed_at")) + 1000)
    assert r.hget(q.task_key("t1"), "status") == "queued"

    # A new worker picks it up and finishes it.
    got = q.claim_first(r, 1)
    assert got == "t1"
    run(worker.process_batch(r, StubEngine(results=[StubResult("recovered", [])]), ["t1"], settings))
    task = r.hgetall(q.task_key("t1"))
    assert task["status"] == "done"
    assert task["attempts"] == "2"
    assert json.loads(task["result"])["markdown"] == "recovered"
