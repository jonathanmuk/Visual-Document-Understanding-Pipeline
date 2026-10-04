# Performance: What Has Been Measured, and How to Measure the Rest

Every number here says what it was measured on and when. A number without its
hardware and date is not published.

## Measured: the front door (the API and Redis)

Measured on 29 September 2026, on a Windows 11 laptop with 12 CPUs, using the
compose test stack with no worker running. This covers the Rust API and Redis
only: not reading speed, not GPUs.

| Measure | Result |
| :--- | :--- |
| Redis memory per waiting 9.5 MB document | 10.5 MB |
| Status check while that document waits, middle value | 2.2 ms (2.5 ms on a second run) |
| Upload of a 9.5 MB document, middle value | 91 ms (108 ms on a second run) |
| Small uploads accepted per second, 20 at a time | 225 (218 on a second run) |
| Repeat upload of an identical, finished document | answered from the cache, 50 of 50, in about 3 ms |
| Worker image size | 8.73 GB |

**To reproduce** on your own machine, with the test stack running and no worker
([testing-guide.md](../testing-guide.md) section 12 explains every field):

```bash
python tools/benchmark.py --label my-laptop
```

## Not yet measured: the numbers that need GPUs

These need the cluster, and they are the ones that decide what the system
costs. None has been measured yet.

| Measure | Why it matters | Result | Hardware and date |
| :--- | :--- | :--- | :--- |
| Pages per second, sustained | How much one set of GPUs can read | | |
| Time per document, typical and worst (p50, p95) | What a user waits | | |
| Cold start: first document after the GPUs were at zero | What the first user of the morning waits | | |
| Cost per 1,000 pages | Whether it is worth running | | |
| Best `MAX_BATCH_SIZE` and `BATCH_WINDOW_MS` | The worker's batching settings are starting guesses, never measured | | |
| Multi-token prediction on versus off | Whether to leave it on | | |

Fill this table in as you measure, and keep every run's JSON file in
`benchmarks/`, which git ignores.

## How to measure each one

All of these use `tools/throughput.py`, which sends the same document several
times (each marked "no cache", so every copy is really read), waits for all of
them, and reports speed and time per document. Point it at the cluster with a
port-forward, so it uses the same address as on your laptop:

```bash
kubectl port-forward svc/ocr-api-service 15000:80
```

(Stop the testing guide's compose stack first if it is running; it uses the same
port.) Then, in another terminal, from the repository folder with the tools'
environment active ([testing-guide.md](../testing-guide.md) section 3):

**Pages per second, and time per document.** Use a real document of the kind
you will process, ideally a few pages long:

```bash
python tools/throughput.py --file my-report.pdf --count 50 --concurrency 10 \
  --label aks-a100-t4 --hardware "AKS, 1 x A100 80GB, 1 x T4, <date>"
```

The report's `pages_per_second` and `seconds_per_document` go in the table. Run
it twice; if the two disagree by more than about 10 percent, run it a third time
and report all three.

Here is what the report looks like, from a practice run against the demo worker
(which pretends to take 2 seconds per document, so the numbers only show the
tool working, not any real reading speed):

```json
  "result": {
    "documents": 10,
    "done": 10,
    "failed": 0,
    "unfinished": 0,
    "with_warning": 0,
    "pages_per_document": 1,
    "wall_seconds": 20.39,
    "documents_per_minute": 29.43,
    "pages_per_second": 0.491,
    "seconds_per_document": {
      "p50": 9.09,
      "p95": 11.19,
      "max": 11.19,
      "mean": 8.24
    }
  }
```

One demo worker at 2 seconds per document can do at most 30 a minute; the tool
measured 29.4, which is how you know it counts correctly. `seconds_per_document`
is upload to result, so it includes waiting in the queue behind the others.

**Cold start.** Outside the warm hours (weekdays 8am to 6pm New York time,
unless you changed them), wait until `kubectl get pods` shows no worker and no
vLLM pod and the GPU pools have no machines, then send one document:

```bash
python tools/throughput.py --file my-report.pdf --count 1 --label cold-start \
  --hardware "AKS, GPU pools at zero, <date>"
```

`seconds_per_document.max` is the cold start: a new GPU machine, its driver,
the images, and the model loading, then the reading itself.

**Cost per 1,000 pages.** From the sustained run:

```
cost per 1,000 pages = (hourly price of every machine running during the test)
                       / (pages_per_second x 3600) x 1000
```

Take the hourly prices from the Azure or Google Cloud pricing pages for your
region (the A100 machine, the T4 machine, and the two CPU pools). This is the
cost while busy; idle hours cost nothing for the GPUs once they scale to zero.

**The batching settings.** Change `MAX_BATCH_SIZE` and `BATCH_WINDOW_MS` in the
kustomization, apply, and repeat the sustained run for each pair, for example
`2/50`, `4/100` (the default), `8/200`. Keep the one with the best pages per
second whose p95 time per document you can live with.

**Multi-token prediction.** Run the sustained test with `--concurrency 1` and
`--concurrency 20`, with it off and then on (the deployment guide's section 13
shows the switch). It tends to help most when few documents are read at once;
whether it helps here is exactly what this measures.
