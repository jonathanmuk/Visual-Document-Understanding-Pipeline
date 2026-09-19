import asyncio
import base64
import json
import os

import fakeredis
import pytest

import worker


class StubResult:
    def __init__(self, markdown, layout):
        self.markdown_result = markdown
        self.json_result = layout


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


def enqueue(r, task_id, content=b"%PDF-1.4 fake", ext="pdf"):
    r.hset(f"task:{task_id}", mapping={
        "status": "queued",
        "filename": f"{task_id}.{ext}",
        "extension": ext,
        "data": base64.b64encode(content).decode(),
    })
    r.lpush(worker.QUEUE_KEY, task_id)


def run(coro):
    return asyncio.run(coro)


# --- collect_batch -----------------------------------------------------------

def test_collect_batch_fills_up_to_max(r):
    for i in range(6):
        r.lpush(worker.QUEUE_KEY, f"t{i}")
    _, first = r.brpop(worker.QUEUE_KEY, timeout=1)
    batch = run(worker.collect_batch(r, first, max_batch_size=4, window_ms=100))
    assert len(batch) == 4
    assert batch[0] == first
    assert r.llen(worker.QUEUE_KEY) == 2


def test_collect_batch_returns_partial_when_queue_drains(r):
    r.lpush(worker.QUEUE_KEY, "a")
    r.lpush(worker.QUEUE_KEY, "b")
    _, first = r.brpop(worker.QUEUE_KEY, timeout=1)
    batch = run(worker.collect_batch(r, first, max_batch_size=4, window_ms=50))
    assert sorted(batch) == ["a", "b"]
    assert r.llen(worker.QUEUE_KEY) == 0


def test_collect_batch_with_single_task_waits_out_the_window(r):
    batch = run(worker.collect_batch(r, "only", max_batch_size=4, window_ms=30))
    assert batch == ["only"]


# --- process_batch: what works today -----------------------------------------

def test_process_batch_writes_result_and_clears_data(r, tmp_path):
    enqueue(r, "t1")
    engine = StubEngine(results=[StubResult("# Hello", [{"label": "text"}])])

    run(worker.process_batch(r, engine, ["t1"], shm_dir=str(tmp_path)))

    task = r.hgetall("task:t1")
    assert task["status"] == "done"
    assert task["data"] == ""
    assert json.loads(task["result"]) == {"markdown": "# Hello", "layout": [{"label": "text"}]}
    assert not os.listdir(tmp_path), "temp file must be removed after processing"


def test_process_batch_writes_temp_file_with_original_extension(r, tmp_path):
    enqueue(r, "img1", content=b"\x89PNG\r\n\x1a\n", ext="png")
    seen = {}

    def capture(paths):
        seen["path"] = paths[0]
        seen["existed"] = os.path.exists(paths[0])
        seen["bytes"] = open(paths[0], "rb").read()
        return [StubResult("", [])]

    run(worker.process_batch(r, StubEngine(results=capture), ["img1"], shm_dir=str(tmp_path)))

    assert seen["path"] == os.path.join(str(tmp_path), "img1.png")
    assert seen["existed"] is True
    assert seen["bytes"] == b"\x89PNG\r\n\x1a\n"


def test_process_batch_sets_processing_before_parsing(r, tmp_path):
    enqueue(r, "t1")
    statuses = {}

    def capture(paths):
        statuses["during"] = r.hget("task:t1", "status")
        return [StubResult("x", [])]

    run(worker.process_batch(r, StubEngine(results=capture), ["t1"], shm_dir=str(tmp_path)))
    assert statuses["during"] == "processing"


def test_process_batch_skips_unknown_task_and_processes_the_rest(r, tmp_path):
    enqueue(r, "real")
    engine = StubEngine(results=[StubResult("ok", [])])

    run(worker.process_batch(r, engine, ["ghost", "real"], shm_dir=str(tmp_path)))

    assert engine.calls == [[os.path.join(str(tmp_path), "real.pdf")]]
    assert r.hget("task:real", "status") == "done"
    assert not r.exists("task:ghost")


def test_process_batch_with_no_valid_tasks_never_calls_engine(r, tmp_path):
    engine = StubEngine(results=[])
    run(worker.process_batch(r, engine, ["ghost"], shm_dir=str(tmp_path)))
    assert engine.calls == []


def test_process_batch_marks_all_failed_when_engine_raises(r, tmp_path):
    enqueue(r, "t1")
    enqueue(r, "t2")
    engine = StubEngine(error=RuntimeError("GPU exploded"))

    run(worker.process_batch(r, engine, ["t1", "t2"], shm_dir=str(tmp_path)))

    for t in ("t1", "t2"):
        task = r.hgetall(f"task:{t}")
        assert task["status"] == "failed"
        assert task["error"] == "GPU exploded"
    assert not os.listdir(tmp_path), "temp files must be removed even on failure"


def test_process_batch_handles_single_result_object(r, tmp_path):
    enqueue(r, "t1")
    engine = StubEngine(results=StubResult("solo", []))  # not wrapped in a list
    run(worker.process_batch(r, engine, ["t1"], shm_dir=str(tmp_path)))
    assert r.hget("task:t1", "status") == "done"


# --- process_batch: known gaps, expected to fail until Phase 2 ----------------
# These are written against the behaviour the system should have. They are marked
# xfail(strict=True): today they fail, and the moment the fix lands they will
# start passing and pytest will demand the marker be removed.

@pytest.mark.xfail(reason="gap 20: SDK errors are hidden in _error and the worker never checks", strict=True)
def test_process_batch_reports_sdk_error_as_failed(r, tmp_path):
    enqueue(r, "t1")
    res = StubResult("", [])
    res._error = "MaaS API request failed with status 429"
    run(worker.process_batch(r, StubEngine(results=[res]), ["t1"], shm_dir=str(tmp_path)))
    task = r.hgetall("task:t1")
    assert task["status"] == "failed"
    assert "429" in task["error"]


@pytest.mark.xfail(reason="gap 20: empty output is recorded as done", strict=True)
def test_process_batch_treats_empty_result_as_failure(r, tmp_path):
    enqueue(r, "t1")
    run(worker.process_batch(r, StubEngine(results=[StubResult("", [])]), ["t1"], shm_dir=str(tmp_path)))
    assert r.hget("task:t1", "status") == "failed"


@pytest.mark.xfail(reason="gap 20: fewer results than tasks leaves the rest stuck at processing", strict=True)
def test_process_batch_never_leaves_a_task_at_processing(r, tmp_path):
    enqueue(r, "t1")
    enqueue(r, "t2")
    run(worker.process_batch(r, StubEngine(results=[StubResult("only one", [])]), ["t1", "t2"], shm_dir=str(tmp_path)))
    assert r.hget("task:t2", "status") in ("done", "failed")
