"""Prometheus metrics for the worker and the reaper.

If prometheus_client is not installed, every metric becomes a no-op so the code
still runs. In the container it is installed and the metrics are served on
METRICS_PORT (default 9100) at /metrics.
"""
import os

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server
    AVAILABLE = True
except ImportError:  # pragma: no cover
    AVAILABLE = False

    class _Noop:
        def labels(self, *a, **k):
            return self

        def inc(self, *a, **k):
            pass

        def set(self, *a, **k):
            pass

        def observe(self, *a, **k):
            pass

    def Counter(*a, **k):
        return _Noop()

    def Gauge(*a, **k):
        return _Noop()

    def Histogram(*a, **k):
        return _Noop()

    def start_http_server(*a, **k):
        pass


# Shared by worker and reaper. The reaper is always running, so it is the
# reliable source for queue depths even when workers are scaled to zero.
QUEUE_DEPTH = Gauge("vdu_queue_depth", "Tasks on each queue", ["queue"])

# Worker.
BATCH_SIZE = Histogram("vdu_batch_size", "Documents per batch", buckets=(1, 2, 3, 4, 6, 8))
STAGE_SECONDS = Histogram(
    "vdu_stage_seconds", "Time spent per stage", ["stage"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)
TASKS_TOTAL = Counter("vdu_tasks_total", "Tasks by final outcome", ["outcome"])
REGIONS_FAILED_TOTAL = Counter("vdu_regions_failed_total", "Regions the model failed to transcribe")

# Reaper.
REAPER_ACTIONS_TOTAL = Counter("vdu_reaper_actions_total", "Recovery actions", ["action"])
WEBHOOKS_TOTAL = Counter("vdu_webhooks_total", "Callback deliveries by outcome", ["outcome"])


def serve():
    port = int(os.getenv("METRICS_PORT", "9100"))
    start_http_server(port)
    return port


def record_depths(depth_map):
    for queue, n in depth_map.items():
        QUEUE_DEPTH.labels(queue=queue).set(n)
