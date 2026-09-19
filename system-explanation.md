# Visual Understanding System: A Plain-Language Explanation

This document explains what this repository is, what every piece of it does, and
how the pieces fit together. It is written for someone who has never heard of
OCR or SLMs. No prior knowledge of Kubernetes, GPUs, or Rust is assumed.

Read it top to bottom the first time. After that, use the table of contents to
jump to the part you need.

## Table of Contents

1. [The One-Paragraph Version](#1-the-one-paragraph-version)
2. [Vocabulary: Every Term You Need](#2-vocabulary-every-term-you-need)
3. [The Core Idea, With an Analogy](#3-the-core-idea-with-an-analogy)
4. [The Five Components and What Each One Does](#4-the-five-components-and-what-each-one-does)
5. [The Life of a Single Document](#5-the-life-of-a-single-document)
6. [Folder-by-Folder Tour of the Repository](#6-folder-by-folder-tour-of-the-repository)
7. [Why It Was Built This Way: The Design Decisions](#7-why-it-was-built-this-way-the-design-decisions)
8. [What Domains This Project Cuts Across](#8-what-domains-this-project-cuts-across)
9. [What Problems It Solves and Where It Applies](#9-what-problems-it-solves-and-where-it-applies)
10. [The Cost Reality](#10-the-cost-reality)
11. [Turning This From a Course Into Your Own System](#11-turning-this-from-a-course-into-your-own-system)
12. [The LICENSE Question: Where It Came From and What It Requires](#12-the-license-question-where-it-came-from-and-what-it-requires)
13. [Honest Gaps and Things That Do Not Match](#13-honest-gaps-and-things-that-do-not-match)
14. [Where to Tweak It to Make It More Interesting](#14-where-to-tweak-it-to-make-it-more-interesting)

---

## 1. The One-Paragraph Version

You give this system a PDF or a photograph of a document. It gives you back
clean, structured text: paragraphs in order, tables as real tables, maths as
proper formulas, and written descriptions of the charts and pictures. It does
this not with old-fashioned character matching but with a small AI model that
actually looks at the page and reads it the way a person would. The whole thing
runs on rented cloud computers with graphics cards, it wakes up when work
arrives and goes back to sleep when there is none, and it is locked behind a
private front door so nobody on the open internet can run up your bill.

The repository as it stands today is a **teaching course** (six weeks of
material) wrapped around a **working system**. Your job is to strip away the
course and keep the system.

---

## 2. Vocabulary: Every Term You Need

Read this section once. Everything after it will make sense.

### OCR (Optical Character Recognition)

Turning a picture of text into text you can copy, search, and edit.

Think of a photograph of a page in a book. To your computer, that photo is just
millions of coloured dots. It has no idea that some of those dots form the word
"invoice". OCR is the process that looks at the dots and works out: those dots
spell the word "invoice".

Old OCR (the kind in a scanner from 2005) worked by shape matching. It had a
library of what every letter looks like and compared each blob of ink against
that library. It was fine for a clean typed page and terrible at everything
else: handwriting, rotated pages, columns, tables, receipts photographed on a
kitchen table.

### VDU (Visual Document Understanding)

The modern replacement for OCR. Instead of only asking "what letters are here",
it asks "what is this document, and what does it mean".

The difference matters enormously. Old OCR looking at an invoice returns a soup
of numbers and words in roughly reading order. A VDU system looking at the same
invoice can tell you that 4,200 is the grand total and 1,400 is a line item,
because it understands the *layout*: what sits under what, what is in a bold box
at the bottom right, what is in the table body versus the table footer.

The same applies to charts. Old OCR sees a bar chart and returns the axis labels
as loose words. A VDU system returns a sentence like "revenue rose steadily from
Q1 to Q3 then dipped in Q4".

This repository builds a VDU system. The word "OCR" in the folder and service
names is a leftover from the older, narrower name for the same job.

### LLM (Large Language Model)

The kind of AI you already know: ChatGPT, Claude, Gemini. A very large
statistical model trained on enormous amounts of text that can read, write,
summarise, and reason. "Large" here means hundreds of billions of internal
numbers (parameters). They are powerful, slow, and expensive to run.

### SLM (Small Language Model)

The same kind of model, deliberately made small. Instead of hundreds of billions
of parameters, an SLM has a few billion. The model this repository is configured
to use, **Qwen 3.5 4B**, has roughly 4 billion parameters.

Why would you want a smaller, less capable model? Because it fits on one
graphics card, it answers much faster, and you can run thousands of requests
through it for the price of a handful of requests to a big frontier model.

The key insight of this project: **reading a document is a narrow job**. You do
not need a model that can also write poetry, debug Rust, and discuss philosophy.
You need one that is excellent at one thing. A 4-billion-parameter model trained
specifically on document reading can beat a much larger generalist at this task
while costing a fraction as much to run.

**The analogy:** hiring a professional court stenographer instead of a
university professor to transcribe a meeting. The professor knows vastly more
about the world. The stenographer is faster, cheaper, and better at
transcribing.

### VLM (Vision Language Model)

A language model with eyes. Ordinary language models only take text as input. A
VLM also takes images. The model in this system is a VLM: you hand it a cropped
picture of a table plus a written instruction ("convert this table to Markdown")
and it replies with text.

### Layout Detection

Before the AI reads anything, a separate, simpler model draws boxes on the page
and labels them: "this rectangle is a paragraph", "this one is a table", "this
one is a chart", "this is a page header, ignore it".

The model doing this here is called **PP-DocLayoutV3**. It is not a language
model. It is a computer vision object detector, the same family of technology
that finds faces in photos or pedestrians in self-driving car footage. It does
not read anything. It only finds and labels regions.

**The analogy:** before a translator starts work on a magazine, an assistant
goes through with a highlighter and marks which blocks are articles, which are
advertisements, which are captions, and which are page numbers to skip. The
translator then works block by block instead of trying to make sense of the
whole cluttered spread at once.

This is the single most important design choice in the whole system, and
section 7 explains why.

### Tokens

The unit AI models count in. Roughly, a token is a word fragment.
"understanding" might be three tokens. An image gets converted into tokens too:
a high-resolution crop of a dense table might become 6,000 tokens.

Why you care: models charge by the token, run at a speed measured in tokens per
second, and have a maximum number of tokens they can hold in mind at once. Every
tuning number in this repository is ultimately about managing tokens.

### GPU (Graphics Processing Unit)

A graphics card. Originally built for video games, now the standard hardware for
AI because it can do thousands of simple maths operations simultaneously. AI is
almost entirely simple maths done a staggering number of times.

Two GPU models appear in this project:

- **NVIDIA T4**: older, small, cheap. 16 GB of onboard memory. Used here for the
  layout detection.
- **NVIDIA A100 80GB**: current-generation datacentre hardware. Extremely fast,
  extremely expensive (several dollars per hour to rent). Used here for the
  actual AI reading.

### VRAM

The graphics card's own private memory. Separate from, and much faster than,
your computer's normal RAM. A model has to fit entirely inside VRAM to run at
full speed. This is why a 4-billion-parameter model is attractive: it fits in a
few gigabytes, leaving the rest of the A100's 80 GB free for handling many
requests at once.

### Inference

Running a trained AI model to get an answer. Training is teaching the model
(done once, by whoever made it, at enormous cost). Inference is using it (done
millions of times, by you). This repository does inference only. Nothing here
trains anything.

### vLLM

The engine that runs the model. You could load an AI model with a hundred lines
of Python, but it would serve one request at a time and waste most of the GPU.
vLLM is specialised software that serves the same model to hundreds of
simultaneous users efficiently.

Its two headline tricks:

- **Continuous batching**: instead of waiting to collect a fixed group of
  requests, processing them together, and then starting over, vLLM slots new
  requests into the group the instant an old one finishes. Like a bus that never
  stops moving and lets people on and off while rolling.
- **PagedAttention**: a memory management trick borrowed from how operating
  systems handle RAM. It stops GPU memory from becoming fragmented and wasted,
  so you can fit far more simultaneous conversations on one card.

### Kubernetes (often written k8s)

The software that runs your containers across a fleet of machines. You describe
what you want ("one copy of the API, on a machine with a T4, with at least 8 GB
of memory") and Kubernetes finds a machine, starts it, restarts it if it
crashes, and moves it if the machine dies.

**The analogy:** Kubernetes is a building manager for a large office. You do not
say "put Sarah in room 412". You say "Sarah needs a quiet room with a window and
a good chair". The manager finds one, and if the ceiling leaks, moves her
without you being involved.

Terms you will meet:

- **Pod**: the smallest unit Kubernetes runs. In practice, one running container.
- **Deployment**: your instruction for how many copies of a pod should exist.
- **Service**: a stable internal address for a set of pods, so other parts of
  the system can find them even as individual pods come and go.
- **Node**: one actual machine in the cluster.
- **Node pool**: a group of identical machines. This project has four: cheap CPU
  machines for the API, high-memory machines for Redis, T4 machines for layout,
  A100 machines for the AI.
- **Taint and toleration**: a "keep out" sign on a node pool, plus a matching
  permission slip on the pods that are allowed in. This is how the project stops
  a cheap background job from accidentally landing on an expensive A100 machine.
- **PVC (PersistentVolumeClaim)**: a request for a shared disk that survives pods
  being destroyed. Used here to store the downloaded model files once, so every
  pod can read them instead of each downloading tens of gigabytes separately.

### AKS and GKE

Managed Kubernetes. AKS is Microsoft Azure's version, GKE is Google Cloud's.
Rather than installing and maintaining Kubernetes yourself, you rent it. This
repository supports both, with a near-identical setup in each.

### KEDA (Kubernetes Event-Driven Autoscaling)

The piece that watches for work and adds or removes machines automatically.

Standard Kubernetes autoscaling watches CPU usage: if the processors are busy,
add machines. That is useless for a GPU system, because a pod waiting on a GPU
looks idle to the CPU.

KEDA instead watches meaningful signals. In this project:

- "How many documents are waiting in the queue?" If more than zero, start a
  layout worker.
- "How many requests is the AI engine holding in its waiting room?" If more than
  zero, start another A100.
- "Is it a weekday between 8am and 6pm New York time?" If so, keep one of each
  running so the first request of the morning is not slow.

Crucially, KEDA can scale **to zero**. At 3am on a Sunday, the expensive GPU
machines are shut off entirely and you pay nothing for them.

### Redis

An extremely fast database that keeps everything in memory instead of on disk.
Here it plays two roles at once:

- **A queue**: a list of jobs waiting to be done.
- **A filing cabinet**: the actual file contents and the finished results.

**The analogy:** the ticket rail in a restaurant kitchen. Waiters clip orders
onto it, cooks pull them off. Nobody has to stand and wait for anybody else.

### Rust and Axum

Rust is a programming language known for being extremely fast and extremely
strict about memory safety. Axum is a web framework for Rust. The front door of
this system (the part that receives uploaded files) is written in Rust because
that job is pure plumbing at high volume: accept a 10 MB file, write it to
Redis, reply. Rust does that with tiny memory usage and none of the slowdowns
you get in garbage-collected languages under heavy load.

### Async, Producer, Consumer

**Synchronous** means you wait. You ask a question and stand there until the
answer comes.

**Asynchronous** means you do not wait. You drop off your dry cleaning, you get
a ticket, you leave, you come back later.

This system is asynchronous. You upload a document and immediately get a
`task_id` back. You come back later and ask "is task 4f2a done yet?".

- The **producer** is the part that creates work and puts it on the queue (the
  Rust API).
- The **consumer** is the part that takes work off the queue and does it (the
  Python worker).

They never talk to each other directly. They only talk through the queue.

### /dev/shm

On Linux, a folder that is secretly not a folder on a disk at all: it is a slice
of RAM pretending to be a disk. Writing a file to `/dev/shm` is far faster than
writing it to real storage, because nothing physically moves.

This project uses it to hand documents between the worker's Python code and the
OCR library without either of them waiting on storage.

### MCP (Model Context Protocol)

A standard way to give an AI assistant a new tool. If you wrap this pipeline in
an MCP server, then an assistant such as Claude Code can call it directly: "read
this PDF for me" becomes something the assistant can simply do, without you
writing any glue code.

The README promises this in Week 6. Note that **no MCP server code exists in the
repository**. See section 13.

### API Gateway (Azure APIM / GCP API Gateway)

A guarded front door in front of your service. It checks who you are, counts how
many requests you have made, blocks you if you make too many, and only then
passes the request through.

For a GPU system this is not merely security theatre. Without it, anyone who
finds your address can upload thousands of documents, KEDA will dutifully spin
up A100 machines to serve them, and you will get a bill for thousands of
dollars. The gateway is a financial safety device as much as a security one.

---

## 3. The Core Idea, With an Analogy

Picture a busy restaurant. That is this system.

| The restaurant | This system | Folder |
| :--- | :--- | :--- |
| The host at the door who takes your order and hands you a buzzer | Rust API (Producer) | `realtime_producer/` |
| The ticket rail where orders hang waiting | Redis | `k8s/*/apps/redis-deployment.yml` |
| The prep cook who portions ingredients onto plates | Python Worker + layout detection | `realtime_consumer/` |
| The head chef who actually cooks each portion | vLLM + the SLM | `server/` |
| The stainless steel counter right between the two cooks | `/dev/shm` shared memory | configured in both |
| The manager who calls in extra staff when the rail gets long | KEDA | `k8s/*/apps/keda-scaler.yml` |
| The building itself, with its separate stations | Kubernetes cluster | `k8s/` |
| The locked door with a bouncer checking reservations | API Gateway | `k8s/aks/networking/` |

The single most important structural fact: **the host never waits for the
kitchen**. You hand over your document, you get a buzzer (a `task_id`), you
walk away. This is why the system can accept a thousand uploads in a burst while
only two cooks are on shift. The queue absorbs the burst.

The second most important fact: **the prep cook and the head chef are separate
people on separate hardware**. Chopping vegetables does not need a Michelin-star
chef, and a Michelin-star chef should never be idle waiting for someone to chop.
That is exactly the T4 versus A100 split.

---

## 4. The Five Components and What Each One Does

### Component 1: The Rust Producer API

**Where:** `realtime_producer/src/main.rs`
**Runs on:** cheap CPU-only machines (node pool `apinp`)
**Job:** accept files, hand out tickets, report status

This is roughly 200 lines of Rust and it exposes exactly three endpoints:

| Endpoint | What it does |
| :--- | :--- |
| `POST /process` | You upload a file. It generates a unique ID, stores the file in Redis, adds the ID to the work queue, and immediately returns `{ task_id, status: "queued" }` with HTTP 202 Accepted. |
| `GET /status/{task_id}` | You ask about your ticket. It looks up the ID in Redis and returns the status, plus the result if it is finished, plus the error if it failed. |
| `GET /health` | Returns OK. Kubernetes pings this constantly to decide whether the pod is alive. |

Three details worth understanding:

**It accepts up to 10 MB.** Axum's default upload limit is around 2 MB, which
would reject most real PDFs. The code explicitly disables the default and sets a
10 MB ceiling. A ceiling still exists deliberately: without one, a single
attacker uploading a 5 GB file could exhaust the server's memory.

**It writes everything in one atomic operation.** All four fields (status,
filename, extension, file data) go into Redis in a single `HSET` command. This
matters because of a race condition: if the code wrote the status first and the
data second, a worker could grab the job in between and find an empty file. One
command means the worker either sees everything or nothing.

**It base64-encodes the file.** Binary file bytes get converted into a long
text string before being stored. This is done so the Python worker can reliably
read it back as text. The cost is that the stored data is about 33 percent
larger than the original file. This is a real inefficiency and a good candidate
for your improvements (see section 14).

**Why Rust for this?** Because this component does almost nothing intellectually
but must do it thousands of times a second without stumbling. Rust gives
predictable speed, tiny memory usage (the pod is limited to 256 MB of RAM), and
a final container image of only a few megabytes. Its resource request in the
Kubernetes manifest is 100 millicores of CPU, meaning one tenth of a single
processor core.

### Component 2: Redis, the State Store

**Where:** `k8s/aks/apps/redis-deployment.yml`
**Runs on:** high-memory CPU machines (node pool `redisnp`)
**Job:** hold the queue and hold the data

Redis stores exactly two kinds of thing:

1. A list called `ocr_tasks` containing task IDs waiting to be processed. This
   is the queue.
2. A hash per task, keyed `task:{id}`, holding status, filename, extension, the
   base64 file data, and eventually the result.

The queue is the shock absorber of the entire system. Uploads arrive in bursts
(someone drags in 500 invoices at once). GPUs process at a steady rate. Without
a buffer between them, either the API rejects uploads or the GPU is
alternately overwhelmed and idle. The queue smooths this out completely.

Redis also acts as the signal KEDA watches. "Queue is 40 items long" is a
directly meaningful statement about how much hardware you need right now, in a
way that "CPU is at 60 percent" never is.

One clever touch: when the worker finishes, it writes `"data": ""` back to
Redis, deliberately blanking the stored file. The 10 MB base64 blob is no longer
needed once the text has been extracted, and Redis lives entirely in RAM. Not
clearing it would fill memory with completed work.

### Component 3: The Python Consumer Worker

**Where:** `realtime_consumer/worker.py` and `realtime_consumer/config.yaml`
**Runs on:** T4 GPU machines (node pool `gpunpt4`)
**Job:** pull work from the queue, find the regions on each page, orchestrate the reading

This is the brain of the pipeline, and it is only about 130 lines of Python. It
runs an endless loop:

**Step 1: Wait for a job.** It calls `brpop` on the `ocr_tasks` list, which
blocks (sleeps) until something appears. This is important: it does not
repeatedly ask "anything yet? anything yet?", which would burn CPU. It sleeps
until Redis wakes it.

**Step 2: The collector window.** Once one job arrives, instead of processing it
immediately, the worker waits up to 100 milliseconds to see whether more jobs
turn up, collecting up to 4 in total.

**The analogy:** a lift that waits three seconds before closing its doors. You
lose three seconds on the first passenger and save an entire round trip when
four people get in. 100 milliseconds is imperceptible to a user and lets the
GPU process four pages in a single pass rather than four separate passes, each
with its own fixed setup cost.

**Step 3: Write the files to RAM.** Each file is decoded from base64 and written
to `/dev/shm/{task_id}.{ext}`, then given read permissions (`0o644`) so that any
sub-process the OCR library spawns can open it regardless of which user account
it runs as. This is a small but genuinely production-hardened detail: it is the
kind of thing that only shows up when you actually deploy.

**Step 4: Hand off to the OCR engine.** The worker calls
`ocr_engine.parse(temp_paths)` with the file paths, not the file contents. The
library decides how to handle each file by looking at its **name**: a file ending
in `.pdf` is treated as a PDF, anything else as an image. PDFs get rasterised into
images at 200 DPI using a library called pypdfium2. Images are loaded directly.

This means the file extension matters. The worker names each temporary file using
the extension from the original upload, so a PDF uploaded under the name
`scan.jpg` would be handed to the image loader and fail. (An earlier version of
this document, and the original README, said the library inspects the file's
opening bytes instead. Reading the SDK's source code shows that is only true in
the cloud MaaS mode, not in the self-hosted mode used in production.)

**Step 5: Layout detection runs on the local T4.** PP-DocLayoutV3 draws boxes on
each page and assigns each one of 25 possible labels: `text`, `table`,
`display_formula`, `chart`, `doc_title`, `header`, `footer`, `seal`, and so on.

**Step 6: Regions get sorted into buckets.** The config file maps each label to
one of four fates:

| Fate | Labels | Meaning |
| :--- | :--- | :--- |
| `text` | paragraphs, titles, abstracts, references | Send to the AI with a "transcribe this" prompt |
| `table` | tables | Send to the AI with a "convert to Markdown table" prompt |
| `formula` | display and inline formulas | Send to the AI with a "convert to LaTeX" prompt |
| `skip` | charts, images | Keep the region, do not transcribe it |
| `abandon` | headers, footers, page numbers, footnotes | Throw away entirely |

This bucketing is where a lot of the quality comes from. Page furniture (running
headers, page numbers) is noise that would pollute the extracted text, so it
never reaches the AI. Different content types get different instructions, so the
model knows a table should come back as a table.

**Step 7: Regions go to the AI, up to 512 at a time.** The `max_workers: 512`
setting means the worker fires up to 512 concurrent requests at the vLLM server.
This number is chosen deliberately to match vLLM's own `MAX_NUM_SEQS=512`: the
worker is sized to exactly fill the engine's capacity and no more.

**Step 8: Assemble and store the result.** The pieces come back, get stitched
into a single Markdown document plus a JSON structure describing the layout, and
both get written to Redis with `status: "done"`.

**Step 9: Clean up.** The temporary files in `/dev/shm` are deleted in a
`finally` block, so they get removed even if processing crashed. Forgetting this
would slowly fill the RAM disk (limited to 4 GB in the manifest) until the pod
died.

One deliberate constraint: the worker processes **one batch at a time** and
waits for it to finish before fetching more. This looks like it is throttling
itself, but it is preventing the T4's 16 GB of VRAM from being oversubscribed by
several overlapping batches, which would cause thrashing and make everything
slower.

### Component 4: The vLLM Inference Server

**Where:** `server/Dockerfile` and `server/entrypoint.sh`
**Runs on:** A100 80GB GPU machines (node pool `gpunpa100`)
**Job:** actually read the cropped regions

This component is almost entirely configuration. `entrypoint.sh` is a shell
script that launches `vllm serve` with a carefully chosen set of flags. Each
flag is a decision:

| Setting | Value | Why |
| :--- | :--- | :--- |
| `--gpu-memory-utilization` | 0.9 | Use 90 percent of the card's memory. The remaining 10 percent is safety margin against out-of-memory crashes. |
| `--max-model-len` | 16384 | The longest single conversation the model will handle, in tokens. Deliberately *reduced* from the default. A 6,000-token image plus 8,000 tokens of output fits comfortably in 16,000. Setting it higher would make vLLM reserve memory for conversations that never happen, leaving less room for concurrent requests. |
| `--max-num-batched-tokens` | 262144 | How many tokens can be processed in one forward pass. This is the big one. At the default, only about 5 image crops could be loaded at once. At 262,144, roughly 42 can. This directly removes the biggest bottleneck. |
| `--max-num-seqs` | 512 (via config) | How many conversations can be in flight simultaneously. |
| `--enable-chunked-prefill` | on | Splits the work of loading a large image into smaller pieces so it does not block requests that are already mid-answer. Without this, one big image causes a latency spike for everyone. |
| `--limit-mm-per-prompt` | 1 image, 0 video | One image per request, no video. Prevents a malformed request from consuming unbounded memory. |
| CUDA graphs (left on) | default | vLLM pre-compiles the sequence of GPU operations at startup instead of dispatching them one at a time. Makes startup slower and generation much faster. |

**The mental model for these numbers:** imagine a restaurant kitchen. `max-model-len`
is how big a plate you set aside per order (set it too big and you run out of
plates). `max-num-batched-tokens` is how many orders the prep station can lay
out at once. `max-num-seqs` is how many tables you will seat. All three have to
be balanced against the same fixed 80 GB of counter space.

### Component 5: KEDA, the Autoscaler

**Where:** `k8s/aks/apps/keda-scaler.yml`
**Job:** turn expensive machines on when needed and off when not

Three separate scaling rules, each watching a different signal:

**The Rust API** scales from 1 to 5 copies based on CPU usage crossing 70
percent. This is conventional scaling and it is appropriate here because the API
genuinely is CPU-bound.

**The T4 layout worker** scales from 0 to 10 copies based on the Redis queue
containing at least 1 item. That threshold is unusually aggressive: normally you
would wait for a queue of several items before adding hardware. The reasoning is
that the worker processes one batch at a time and blocks, so a second pending
task genuinely needs a second worker rather than waiting behind the first.

**The A100 inference server** scales from 0 to 4 copies based on a Prometheus
metric, `vllm:num_requests_waiting`, crossing 1. In plain terms: "if the AI
engine has even one request sitting in its waiting room, start another A100".

**All three also have a cron rule** keeping one copy alive on weekdays from 8am
to 6pm New York time. This is the "warm start". Loading a model onto a GPU and
compiling CUDA graphs takes minutes; without the warm start, the first person to
upload a document each morning would wait several minutes for the machine to
boot, the driver to load, and the model to initialise. The cron rule pays for a
few idle hours to avoid that.

The `cooldownPeriod: 300` means the system waits 5 minutes of quiet before
shutting a machine down, so it does not thrash on and off during a stream of
sporadic requests.

---

## 5. The Life of a Single Document

Follow one invoice through the whole system.

**Second 0.00.** You run `curl -X POST .../process -F "file=@invoice.pdf"`. The
request hits the API Gateway first. The gateway checks your API key or JWT
token, checks you have not exceeded 100 requests per minute, and forwards you to
the Internal Load Balancer, which forwards you to the Rust API pod.

**Second 0.01.** The Rust API reads the multipart form, finds the field named
`file`, and extracts the filename `invoice.pdf` and extension `pdf`. It
generates a UUID, say `4f2a...`, converts the PDF bytes to base64, and writes
one `HSET` to Redis creating `task:4f2a` with status `queued`. It then pushes
`4f2a` onto the `ocr_tasks` list.

**Second 0.02.** You receive `{"task_id": "4f2a...", "status": "queued"}` with
HTTP 202. As far as you are concerned, the job is submitted. You are free to go.

**Second 0.03.** KEDA's poll notices the queue is no longer empty. If no worker
is running, it tells Kubernetes to create one. Kubernetes asks the cluster
autoscaler for a T4 machine. (If a warm worker is already running, skip ahead.)

**Second 0.04.** A worker's `brpop` returns `4f2a`. The worker starts its 100 ms
collection window, checking for more tasks.

**Second 0.14.** The window closes. Say two other invoices arrived, so the batch
is 3 documents. The worker sets all three to `processing` in Redis, decodes each
from base64, and writes them into `/dev/shm/`.

**Second 0.15.** The worker calls `parse()` with the three paths. The library sees
the `.pdf` extension on each file name, recognises them as PDFs, and rasterises
the pages into images at 200 DPI.

**Second 0.4.** PP-DocLayoutV3 runs on the local T4, processing pages 4 at a
time. It produces boxes: a `doc_title` at the top, several `text` paragraphs, a
`table` in the middle, a `header` and a `footer` (both marked for discard), and
a company `seal` in the corner.

**Second 0.45.** The worker crops each keeper region out of the page image and
builds a request per region, attaching the right prompt for its type. The
table region gets "Convert this table image into a clean Markdown table format".
The paragraph regions get "OCR and recognize the text in this image".

**Second 0.5.** All those requests fly at the vLLM service over HTTP, as
OpenAI-compatible chat completions with an image attached. Up to 512 can be in
flight at once.

**Second 0.5 to 1.1.** vLLM's continuous batching scheduler slots each request
into the running batch as capacity opens. The model reads each crop and
generates text. The table comes back as pipe-delimited Markdown, the paragraphs
as clean prose.

**Second 1.2.** The worker collects all the pieces, reassembles them in reading
order, runs post-processing (merging split text blocks, attaching formula
numbers to their formulas, normalising bullet points), and produces both a
Markdown document and a JSON layout description.

**Second 1.25.** The worker writes the result to `task:4f2a` in Redis, sets
status to `done`, and blanks the `data` field. It deletes the temp files from
`/dev/shm`.

**Whenever you like.** You call `GET /status/4f2a`. The Rust API reads the hash
from Redis and returns your Markdown and JSON.

**Five minutes later.** The queue has been empty for the whole cooldown period.
KEDA scales the worker to zero and the A100 to zero. The cluster autoscaler
releases the machines. You stop paying for them.

---

## 6. Folder-by-Folder Tour of the Repository

### `/` (root)

| File | What it is |
| :--- | :--- |
| `README.md` | The course front page. Architecture explanation, the six-week syllabus, tuning tables, and the security model. This is the file you will rewrite most heavily. |
| `LICENSE` | Apache License 2.0, unmodified boilerplate. See section 12. |
| `.gitignore` | Standard Python ignore list from GitHub's template collection. Tells git not to track caches, virtual environments, and build artefacts. |
| `.gitattributes` | One line telling git to normalise line endings. Relevant to you because you are on Windows and the deployment targets Linux. |
| `system-explanation.md` | This file. |
| `NOTICE` | Attribution to the original Apache-2.0 work and your copyright. Added in Phase 0. |
| `docker-compose.test.yml` | Starts Redis and the built API image for the smoke test. Added in Phase 1. |
| `.github/workflows/ci.yml` | Four jobs that run on every push: Rust tests, Python tests, container smoke test, and a Kustomize build check. Added in Phase 1. |

### `/tests` (added in Phase 1)

| Path | What it is |
| :--- | :--- |
| `fixtures/sample.pdf`, `fixtures/sample.png` | Tiny, hand-generated documents for the API tests. |
| `fixtures/README.md` | What real OCR fixtures should look like, once a Track 1 run succeeds. |
| `integration/smoke.py` | 21 checks against the running containers: health, submit, status, exact bytes stored, queue membership, 404 for unknown IDs. |

Component tests live next to the code they test: `realtime_producer/tests/api.rs`
drives the Rust router in-process, and `realtime_consumer/tests/test_worker.py`
drives the worker against a fake Redis.

### `/realtime_producer` (the front door, Rust)

The "rt" stands for real-time. This is the producer half of the
producer/consumer pattern.

| File | What it is |
| :--- | :--- |
| `src/main.rs` | The entire API. Around 200 lines including generous comments. Three endpoints, one Redis client, one shared state struct. |
| `Cargo.toml` | Rust's dependency list. Axum for the web server, Tokio for async, Redis, UUID for IDs, base64, tracing for logs. |
| `Cargo.lock` | Exact pinned versions of every dependency including transitive ones. Checked in so builds are reproducible. Do not hand-edit. |
| `Dockerfile` | A four-stage build using `cargo-chef`. Stages 1 to 3 build dependencies separately from your code so that changing `main.rs` does not trigger a full rebuild of every library. Stage 4 copies just the compiled binary into a bare Alpine image, producing a container of a few megabytes rather than a few gigabytes. |

**What to know:** this is the only component that is externally reachable, so it
is the only one with an attack surface. It is also the only Rust in the project.

### `/realtime_consumer` (the orchestrator, Python)

| File | What it is |
| :--- | :--- |
| `worker.py` | The queue loop, the collector-window batching, the `/dev/shm` handoff, and the result writing. The most important file in the repository for understanding behaviour. |
| `config.yaml` | Around 250 lines configuring the GLM-OCR SDK. This is where the prompts live, where the label-to-task mapping lives, where the concurrency numbers live, and where the vLLM address is set. **This is the file you will tune most when adapting to a domain.** |
| `Dockerfile` | Built on NVIDIA's CUDA 12.1 base image because this container needs GPU access for layout detection. Installs the `glmocr` SDK plus PDF libraries (`poppler-utils`, `PyMuPDF`, `pdf2image`) and OpenCV. Note that the SDK renders PDFs with pypdfium2, which it installs itself, and neither the SDK nor `worker.py` imports PyMuPDF or pdf2image. Those two, and `poppler-utils` which pdf2image depends on, appear to be unused. |

**The parts of `config.yaml` worth knowing:**

- `pipeline.maas.enabled` (currently `false`): a switch. Set to `true` and the
  SDK stops doing local work and forwards everything to a paid cloud API
  instead. Useful for testing without a GPU.
- `pipeline.ocr_api`: where to find the vLLM server, how long to wait, how many
  times to retry, how big the HTTP connection pool is.
- `pipeline.page_loader.task_prompt_mapping`: the four prompts. Editing these is
  the cheapest, highest-leverage way to change the system's behaviour.
- `pipeline.page_loader.pdf_dpi` (200): the resolution PDFs are rasterised at.
  Raising it improves accuracy on small print and costs more tokens and time.
- `pipeline.layout.label_task_mapping`: which of the 25 region types get read,
  which get skipped, and which get thrown away.
- `pipeline.layout.threshold` (0.3): how confident the detector must be before
  it reports a region. Lower catches more, including false positives.
- `pipeline.layout.use_polygon` (false): whether to crop regions as precise
  polygons or simple rectangles. Turn this on for rotated or skewed documents.

### `/server` (the AI engine)

| File | What it is |
| :--- | :--- |
| `Dockerfile` | Starts from the official vLLM image, adds three extra Python packages, copies in the entrypoint. Very thin. |
| `entrypoint.sh` | The launch script with all the vLLM tuning flags. Also contains the logic that finds the model weights: it checks `/mnt/models`, then `/app/model-weights`, then `/app/models`. |
| `requirements.txt` | Three packages: `huggingface-hub` for model downloading, `instanttensor` for fast weight loading, `fire` for command-line parsing. |

**Note:** there is no application code here at all. This folder exists purely to
package and configure someone else's inference engine.

### `/k8s` (the deployment blueprints)

Everything here is YAML describing what should exist in the cluster. The
structure is mirrored for the two clouds.

```
k8s/
  aks/                                  Azure
    kustomization.yml                   Ties everything together, defines shared config values
    apps/
      deployment-api.yml                The Rust API AND the Python worker (two deployments in one file)
      deployment-vlm.yml                The vLLM server plus its internal Service
      redis-deployment.yml              Redis plus its internal Service
      keda-scaler.yml                   The three autoscaling rules
    networking/
      service.yml                       The internal-only load balancer for the API
      apim-policy.xml                   Azure gateway rules: JWT validation and rate limiting
    infra/
      gpu-operator-values.yaml          NVIDIA driver installation settings (Azure only)
      provisioning/
        pvc.yaml                        Request for 300 GB of shared storage
        ingest-job.yaml                 One-off job that downloads model weights into that storage
  gke/                                  Google Cloud, same structure
    ...                                 (no gpu-operator-values.yaml; GKE manages drivers itself)
```

**How the two clouds differ** (this is what `docs/cloud_comparison.md` is
entirely about):

| Thing | Azure | Google |
| :--- | :--- | :--- |
| Where node pools are labelled | `kubernetes.azure.com/agentpool` | `cloud.google.com/gke-nodepool` |
| GPU node taint | Custom: `sku=gpunpa100` | Automatic: `nvidia.com/gpu=present` |
| Container registry | `acrocrinference.azurecr.io` | `us-central1-docker.pkg.dev/<PROJECT_ID>/...` |
| GPU drivers | You install the NVIDIA GPU Operator via Helm | Managed for you |
| Shared storage | Azure Blob Fuse, 300 GB | Filestore, 1 TB minimum |
| Private load balancer annotation | `azure-load-balancer-internal: true` | `load-balancer-type: Internal` |

Everything else, including the entire application and all the KEDA rules, is
byte-identical between the two.

**`kustomization.yml` deserves a special mention.** It is the file you actually
apply (`kubectl apply -k k8s/aks/`). It lists which manifests to include and,
more importantly, generates a shared ConfigMap holding the environment variables
that both the worker and the vLLM server read: Redis hostname, batch size, batch
window, model name, and all the vLLM tuning numbers. Changing a number here
changes it everywhere, which is why a value in this file overrides the default
written in `entrypoint.sh`.

**`ingest-job.yaml` deserves one too.** It is a small Python script embedded in
YAML that downloads model weights straight from Hugging Face into the shared
cluster storage, in the datacentre, using nothing but Python's standard library.
The point: model weights are tens of gigabytes. Downloading them to your laptop
and re-uploading would waste hours and bandwidth. It also writes a marker file
after each model so re-running the job skips what is already there.

### `/docs` (the deployment manuals)

| File | Length | What it covers |
| :--- | :--- | :--- |
| `azure_onboarding.md` | 111 lines | Creating an Azure account, understanding the free trial, installing the `az` CLI. Pure browser clicking, no commands until the end. |
| `gcp_onboarding.md` | 99 lines | The same for Google Cloud, including creating a project. |
| `azure_gpu_prereqs.md` | 327 lines | **The most practically important doc.** Getting GPU quota. Explains the trap that free trial accounts are hard-capped at zero GPUs, how to upgrade to Pay-As-You-Go, how to request T4 and A100 quota per region, how to find a region that actually has capacity, and how to smoke-test with a single VM before committing to a cluster. |
| `gcp_gpu_prereqs.md` | 244 lines | The same for Google Cloud, plus an Azure-to-GCP terminology map. |
| `aks_deployment.md` | 576 lines | **The main build guide.** Every command from empty subscription to running system: create the registry, create the cluster, add four node pools, install the GPU operator, provision storage, ingest the models, build and push three images, install KEDA and Prometheus, deploy, test, then set up Azure API Management with JWT and rate limiting. |
| `gke_deployment.md` | 327 lines | The same for Google Cloud. Shorter because GKE handles GPU drivers itself. |
| `cloud_comparison.md` | 122 lines | A side-by-side matrix of every place the two clouds diverge, plus a verification audit of the GKE manifests. |

### `/images`

Eight files: one architecture diagram (`arch_overview.jpeg`), one screenshot of
the layout model's output (`PaddleOCR-VL-1.5.png`), and six weekly course
graphics (`week1_infra_overview.png` through `week6_apim_mcp.png`).

All eight are referenced from `README.md` and nowhere else. Since you are
replacing the course framing entirely, the six weekly graphics have no purpose
in your version. The architecture diagram is worth replacing with your own.

---

## 7. Why It Was Built This Way: The Design Decisions

This section is the "so what". Each decision here is the reason the system works
in production rather than only in a demo.

### Decision 1: Two stages instead of one

You could feed a whole page image to the AI model and ask it to transcribe
everything. Many systems do. This one deliberately does not.

**What the two-stage approach buys you:**

**Cost.** A full high-resolution page might be 20,000 tokens. The same page cut
into 12 regions, with the header, footer, and page number thrown away, might
total 8,000. You are paying for less than half the compute per page.

**Accuracy.** Generative AI models hallucinate: when uncertain, they invent
plausible-looking content. Handed an entire cluttered page, the model has an
enormous space of possible outputs and plenty of room to go wrong. Handed a
single cropped table with the instruction "convert this table to Markdown", the
space of reasonable answers is tiny. **Narrowing the question narrows the
opportunity to be wrong.**

**Structure.** Because a separate model has already labelled every region, the
output preserves document structure. You know which text was a title and which
was body. A single-stage model returns a flat blob and you have to guess.

**Robustness.** The layout detector handles skew, warping, and bad lighting
before the AI ever sees the content. A photograph taken at an angle gets
regions correctly identified and cropped, rather than the AI struggling with a
distorted full page.

**The analogy again:** it is the difference between handing a translator a whole
newspaper spread and saying "translate this", versus handing them one clipped
article at a time. The second produces better translations and you can skip the
adverts.

### Decision 2: Two different GPUs instead of one

Layout detection is a small, fast vision model. Reading is a large generative
model. They have completely different appetites.

| | Layout (PP-DocLayoutV3) | Reading (the SLM) |
| :--- | :--- | :--- |
| Model size | Small, fits easily in 16 GB | Needs headroom for many concurrent requests |
| Work pattern | Short bursts, one pass per page | Long generative sequences, token by token |
| Bottleneck | Often the CPU (decoding and resizing images) | Purely the GPU |
| Right hardware | Cheap T4 | Expensive A100 |

Running both on A100s would waste the expensive card on a job a T4 does fine.
Running both on T4s would make reading unbearably slow. Splitting them lets each
scale independently: a burst of many small documents needs more T4s, while a
burst of dense text-heavy pages needs more A100s.

There is a second benefit. While the A100 is busy reading batch N, the T4 is
already detecting layout for batch N+1. The two stages overlap, which is called
pipelining, and it is the same reason a factory has an assembly line rather than
one person building the whole car.

### Decision 3: A queue between the API and the GPUs

This is what makes the system survivable under load.

Without a queue, an upload spike either gets rejected or crashes the GPU pods.
With a queue, the API accepts everything instantly and the queue grows. The
queue length then becomes the autoscaling signal. Work is never lost, latency
degrades gracefully rather than falling off a cliff, and the API can be scaled
independently of the GPUs.

### Decision 4: `/dev/shm` instead of a disk or the network

Files could be passed between the worker and the OCR library over the network,
or through a temp file on disk. Both would work. Both would be slower.

`/dev/shm` is RAM dressed up as a folder. The worker writes a 10 MB PDF into it,
the library reads it back, and no disk head moves and no network packet is sent.
At high concurrency this is the difference between the GPU being fed
continuously and the GPU sitting idle waiting for I/O.

The manifest gives each worker pod 4 GB of this RAM disk
(`emptyDir: medium: Memory, sizeLimit: 4Gi`).

**The analogy:** a shared stainless-steel counter between two cooking stations,
instead of walking to the storeroom every time you need to hand something over.

### Decision 5: Scale to zero

The A100 nodes are the single largest cost in this system by a wide margin. The
architecture is built around never paying for one that is not working.

Three mechanisms combine:

1. KEDA sets the pod count to zero when there is no work.
2. The cluster autoscaler notices the machine has no pods and releases it.
3. The cron trigger reintroduces one warm copy during business hours so users
   are not punished by cold starts.

The tension being managed here: cold starts on GPU nodes are genuinely slow
(provisioning the machine, loading the driver, pulling a multi-gigabyte
container image, loading the model into VRAM, compiling CUDA graphs). Several
minutes is normal. The cron warm-start is a deliberate purchase of a few idle
hours to eliminate that pain during the times people actually use the system.

### Decision 6: Nothing is reachable from the internet

The Rust API's Kubernetes Service is annotated to get an **internal** load
balancer, which means a private IP inside the cloud network only. Redis, the
worker, and vLLM are `ClusterIP`, meaning they are reachable only from inside
the cluster. The only way in is through the API Gateway.

For most systems this is about data protection. Here it is also about money.
Autoscaling plus an open door equals an unbounded bill. The rate limiting in
`apim-policy.xml` (100 calls per minute per subscriber) is the circuit breaker.

---

## 8. What Domains This Project Cuts Across

This is a genuinely wide-ranging project. If you understand all of it, you have
touched most of what modern AI infrastructure involves.

**1. Computer Vision.** Object detection, region proposal, image
preprocessing, rasterisation, DPI and resolution tradeoffs, polygon versus
bounding-box cropping, non-maximum suppression for overlapping detections.

**2. Natural Language Processing and Generative AI.** Vision language models,
tokenisation, prompt engineering (the four prompts in `config.yaml` are prompt
engineering), sampling parameters (`temperature: 0.0` means "be deterministic,
never creative", which is exactly right for transcription), and hallucination
mitigation.

**3. Machine Learning Systems Engineering (MLOps).** Model weight distribution,
inference server tuning, batching strategies, GPU memory management, throughput
versus latency tradeoffs, warm starts.

**4. Distributed Systems.** Producer/consumer patterns, message queues,
asynchronous processing, eventual consistency, atomic writes to avoid race
conditions, idempotency concerns, backpressure.

**5. Cloud Infrastructure and DevOps.** Kubernetes, container orchestration,
node pools and scheduling, taints and tolerations, persistent volumes,
autoscaling, multi-cloud portability, infrastructure as code.

**6. Systems Programming.** Rust, memory safety, async runtimes, multi-stage
container builds, shared memory, Linux file permissions and magic bytes.

**7. Network Security and API Governance.** Zero-trust networking, internal load
balancers, JWT and OAuth token validation, API key management, rate limiting,
web application firewalls, VNet and VPC isolation.

**8. FinOps (Cloud Cost Engineering).** GPU cost optimisation, scale-to-zero,
right-sizing hardware to workload, quota management, and using rate limiting as
a cost control.

**9. Observability.** Prometheus metrics, Grafana dashboards, structured
logging, health and readiness probes, using application metrics as scaling
signals.

**10. Agentic AI.** The MCP framing, treating the pipeline as a tool an AI agent
can call rather than a service a human clicks.

That breadth is exactly why this repository is a good foundation to build on: it
gives you a real, working spine in every one of those areas, which you can then
deepen wherever your interest lies.

---

## 9. What Problems It Solves and Where It Applies

### The core problems

**Problem 1: Most business information is trapped in documents.** Invoices,
contracts, medical records, insurance claims, shipping manifests, forms. They
are PDFs and photographs. Software cannot use them. Historically, humans typed
them in.

**Problem 2: Traditional OCR loses the meaning.** It gives you words but not
structure. It cannot tell you which number is the total. It mangles tables. It
ignores charts entirely.

**Problem 3: Frontier AI models solve the accuracy problem but not the economics.**
Sending millions of pages to a large commercial model is prohibitively
expensive, often too slow, and frequently not allowed for confidential data
that must not leave your network.

**Problem 4: Naively self-hosting an AI model is inefficient.** A single
unoptimised model server uses a fraction of the GPU it occupies. Costs are
astronomical for the throughput achieved.

**Problem 5: GPU infrastructure is either idle-and-expensive or
overwhelmed-and-slow.** Document workloads are bursty. Fixed capacity is wrong
almost all the time.

### Where it applies

**Financial services.** Invoice processing and accounts payable automation, bank
statement analysis, loan application document review, KYC identity document
verification, receipt and expense management. This is the largest commercial
market for document AI by a wide margin.

**Healthcare.** Digitising handwritten clinical notes, extracting structured
data from lab reports, processing insurance claims and prior authorisation
forms, reading medication charts. Note that the on-premises capability matters
enormously here, because patient data often legally cannot be sent to a third
party.

**Legal.** Contract review and clause extraction, discovery document processing
at volume, court filing digitisation, due diligence in mergers.

**Insurance.** Claims processing, policy document analysis, damage assessment
reports that mix text with photographs.

**Logistics and supply chain.** Bills of lading, customs declarations, packing
lists, proof of delivery, all of which arrive as photographs from drivers'
phones and are full of stamps, handwriting, and skew.

**Government and public sector.** Records digitisation, form processing at
scale, historical archive conversion, census and registry data.

**Research and academia.** Converting scientific papers to structured text with
formulas preserved as LaTeX and figures described. The `formula` prompt in the
config exists specifically for this.

**Education.** Digitising textbooks, making printed material accessible to
screen readers, automated marking of scanned exam scripts.

**Accessibility.** Turning any printed material into something a blind or
low-vision reader can navigate, with charts and images described rather than
silently skipped.

**AI agent infrastructure.** The MCP angle. Any AI assistant that needs to read
documents becomes far more capable with this as a tool it can call.

### Why this architecture specifically

If you only had a handful of documents a day, none of this complexity is
justified. Call a commercial API and be done.

This architecture earns its complexity when at least one of these is true:

- You process a high volume (thousands of pages a day or more), so per-page cost
  dominates.
- Your data cannot leave your network for legal or contractual reasons.
- Your volume is bursty, so fixed capacity is wasteful and fixed rate limits are
  a bottleneck.
- You need document structure preserved, not just flat text.
- You need to tune the behaviour for a specific document type in ways a
  general-purpose API will not let you.

---

## 10. The Cost Reality

Worth stating plainly before you deploy anything, because this is where people
get hurt.

**A100 80GB machines cost several US dollars per hour.** Leaving one running by
accident over a weekend is a meaningful, unpleasant bill. Leaving four running
is much worse.

**Free trial accounts cannot run GPUs at all.** Both Azure and Google Cloud
hard-cap trial subscriptions at zero GPU quota, and the "request an increase"
button is disabled. You must upgrade to a paid account first. This is the single
step that stops most people, and it is why two of the seven docs exist purely to
walk you through it.

**GPU quota is requested per region and is not guaranteed.** You can be approved
for A100 quota in a region that has no actual A100 capacity available. Both
`*_gpu_prereqs.md` docs cover verifying real availability before you build.

**The mitigations already built into this repository:**

- Scale to zero on both GPU pools.
- Cron-based warm start limited to business hours.
- Rate limiting at the gateway so an attacker cannot trigger scaling.
- Zero public exposure, so an attacker cannot reach it at all.
- The cluster autoscaler `min-count 0` setting documented in the deployment
  guide.

**Set a billing alert before your first A100 boots.** Both prereq docs say this.
It is good advice.

---

## 11. Turning This From a Course Into Your Own System

You have already renamed the folder to `visual_understanding_system`. Here is
everything else that needs to change, organised by the kind of change.

### 11a. The git remote still points at the original repository

```
origin  https://github.com/neural-maze/production-ocr-course.git
```

Verify with `git remote -v`. Until you change this, `git push` targets someone
else's repository (it will fail, but change it anyway). Create your own
repository and run:

```
git remote set-url origin <your-new-repository-url>
```

### 11b. Links to the original author's site

| File | Line | What is there |
| :--- | :--- | :--- |
| `README.md` | 53 to 70 | The whole "Stay Updated" newsletter table plus the Subscribe badge. Delete this entire block. |
| `README.md` | 332 to 349 | The Contributors table with two names, photos pulled from GitHub avatars, and LinkedIn, YouTube, and newsletter links. Delete or replace with your own. |
| `docs/azure_onboarding.md` | 11 to 12 | A pointer to the author's Substack article for screenshots. Remove, and replace with your own screenshots. |
| `docs/azure_gpu_prereqs.md` | 9 to 10 | The same pointer. Same treatment. |
| `docs/cloud_comparison.md` | 121 to 122 | Two links of the form `file:///Users/hedrergudene/Documents/GitHub/aks-ocr-rt-dpl/docs/...`. These are absolute paths on the original author's laptop and are broken for everyone including him. Replace with relative links: `aks_deployment.md` and `gke_deployment.md`. |
| `docs/aks_deployment.md` | 171 | "At EMDI, we treat models as heavy data" references the author's employer. Rewrite in your own voice. |

### 11c. Course framing that should become product framing

| Location | Change |
| :--- | :--- |
| `README.md` title (line 2) | "Production-Grade SLM-Powered OCR Course" becomes your system name. |
| `README.md` sections "Course Overview", "Who is this course for?", "Course Breakdown: Week by Week" | Replace with "Overview", "Who this is for", and an architecture or quickstart section. |
| `README.md` weekly image grid (lines 95 to 104) | Delete along with the six weekly images. |
| `docs/gcp_onboarding.md` lines 50, 59 | Suggests naming your GCP project `slm-ocr-course`. Rename. |
| The word "course" | Appears 10 times in `README.md`, 3 in `azure_onboarding.md`, 4 in `gcp_onboarding.md`, 2 in `azure_gpu_prereqs.md`. |

### 11d. Identifiers hardcoded to the original author's cloud accounts

These will break your deployment if you do not change them.

| File | What is hardcoded |
| :--- | :--- |
| `k8s/aks/apps/deployment-api.yml` lines 26, 74 | `acrocrinference.azurecr.io/...` (the author's Azure Container Registry) |
| `k8s/aks/apps/deployment-vlm.yml` line 26 | The same registry |
| `k8s/gke/apps/*.yml` | `us-central1-docker.pkg.dev/<PROJECT_ID>/...` (at least this one has a placeholder) |
| `docs/aks_deployment.md` line 19 | `export ACR_NAME="acrocrinference"` |
| `k8s/aks/kustomization.yml` line 15 | Label `managed-by: gemini-cli-agent`, a leftover from the tool that generated these files. Also `system: aks-ocr-glmocr`. |
| `k8s/gke/kustomization.yml` line 15 | The same. |

Note that Azure Container Registry names are globally unique across all of
Azure, so `acrocrinference` is permanently taken by the original author. You
must pick your own.

**A caution on the Kustomize labels:** the `labels` block in `kustomization.yml`
has `includeSelectors: true`, which means these labels get baked into the pod
selectors of every Deployment. Changing them on a cluster that is already
running requires deleting and recreating the deployments, because selectors are
immutable in Kubernetes. Change them now, before your first deploy, and you will
have no trouble.

### 11e. Images

All eight files in `images/` are referenced only from `README.md`.

- `arch_overview.jpeg`: replace with your own architecture diagram.
- `PaddleOCR-VL-1.5.png`: a screenshot of layout detection output. Replace with
  a screenshot from your own run.
- `week1_*.png` through `week6_*.png`: course material with no purpose in a
  product repository. Delete these and the markdown block that displays them.

The two Substack article pointers in the docs exist because the original author
put his screenshots there rather than in the repository. When you take your own
screenshots, put them in `images/` and reference them locally, which is better
practice anyway since it keeps the documentation self-contained.

### 11f. Emojis

Emojis appear throughout: in every markdown heading, in the tech stack tables,
in the log messages in `worker.py` (the rocket, tick, and cross characters in
`logger.info` calls), in the `println!` in `main.rs`, and in `entrypoint.sh`
comments and echo statements.

To find every one:

```
grep -rP "[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}\x{2B00}-\x{2BFF}\x{FE0F}]" \
  --include="*.md" --include="*.py" --include="*.rs" --include="*.sh" \
  --include="*.yml" --include="*.yaml" .
```

The log-message emojis in `worker.py` are worth removing for a practical reason
beyond taste: emoji in logs render inconsistently across terminals and log
aggregation systems, and they make grepping logs harder.

### 11g. Em-dashes

Current counts, by file:

| File | Em-dashes |
| :--- | :--- |
| `docs/azure_gpu_prereqs.md` | 12 |
| `docs/gcp_gpu_prereqs.md` | 11 |
| `README.md` | 11 |
| `docs/azure_onboarding.md` | 5 |
| `docs/gcp_onboarding.md` | 5 |
| `docs/aks_deployment.md` | 1 |
| `docs/gke_deployment.md` | 1 |
| `docs/cloud_comparison.md` | 0 |

None appear in code or configuration files, only in markdown. Note that
`docs/aks_deployment.md` and `docs/gke_deployment.md` also contain a
**non-breaking hyphen** in the phrase "Datacenter-to-Datacenter", which looks
like a normal hyphen but is a different character. Search for it separately if
you are normalising punctuation.

A blanket replacement risks producing awkward sentences, since an em-dash often
carries grammatical weight. Better to replace each with a comma, a colon,
parentheses, or a full stop depending on what the sentence is doing.

### 11h. A summary checklist

```
[ ] git remote set-url origin <your repository>
[ ] README.md: rewrite title, remove course framing, remove newsletter block,
    remove contributors table, remove weekly image grid
[ ] README.md: fix the license statement (see section 12)
[ ] docs/: remove the two Substack pointers, fix the two file:/// links,
    remove the EMDI reference, rename slm-ocr-course
[ ] k8s/: replace acrocrinference with your registry (3 places on AKS),
    fill in <PROJECT_ID> on GKE, rename the gemini-cli-agent label (2 places)
[ ] images/: replace arch_overview and PaddleOCR-VL-1.5, delete week1 to week6
[ ] Remove emojis across markdown, worker.py, main.rs, entrypoint.sh
[ ] Replace em-dashes in the 7 markdown files that have them
[ ] Add your own copyright line to LICENSE and a NOTICE file (see section 12)
```

---

## 12. The LICENSE Question: Where It Came From and What It Requires

You asked where a file like `LICENSE` comes from and what the procedure is.

### What this particular file is

The `LICENSE` file in this repository is the **Apache License, Version 2.0**. It
is a standard, unmodified legal text published by the Apache Software Foundation
at `http://www.apache.org/licenses/`. Nobody wrote it for this project. It is
copied verbatim, character for character, into millions of repositories.

You can confirm it is unmodified: lines 178 to 201 are still the blank
**appendix template**, containing the placeholder `Copyright [yyyy] [name of
copyright owner]`. The original author never filled that in. That is extremely
common and does not invalidate anything, because copyright exists automatically
without being declared, but it does leave the ownership unstated in the file
itself.

### Where people get the text

Three normal routes:

1. **GitHub's license picker.** When you create a repository on GitHub there is
   an "Add a license" dropdown. Choose one and GitHub writes the file for you.
   On an existing repository, create a new file named exactly `LICENSE` and
   GitHub offers a template chooser.
2. **choosealicense.com.** GitHub's own guide. It asks what you want (do you
   require attribution? do you want to force derivative works to stay open?) and
   recommends a license, then gives you the text to copy.
3. **Straight from the source.** Download from `apache.org/licenses/LICENSE-2.0.txt`
   for Apache, or `opensource.org` for others.

Choosing a license is a **declaration, not a registration**. There is no
authority to file with, no fee, no approval. You put the file in your repository
and that constitutes the offer to everyone who receives your code.

### What Apache 2.0 actually permits and requires

**It permits** anyone to use, modify, distribute, sublicense, and sell your
software, including in closed-source commercial products, at no charge.

**It additionally grants a patent license**, which is the main thing
distinguishing it from MIT. Every contributor grants users a license to any
patents their contribution needs. And it contains a retaliation clause: if you
sue somebody over patents in this software, your own license terminates. This is
why large companies tend to prefer Apache 2.0 over MIT for anything substantial.

**It requires** four things of anyone who redistributes the work, spelled out in
Section 4 (lines 89 to 128 of the file):

| Requirement | In plain terms |
| :--- | :--- |
| (a) Include the license | Ship a copy of the Apache 2.0 text with your version. |
| (b) State your changes | Put prominent notices on files you modified saying you changed them. |
| (c) Retain existing notices | Keep the original copyright, patent, trademark, and attribution notices found in the source. |
| (d) Preserve NOTICE | If the original included a `NOTICE` file, your version must reproduce its attribution content. |

**It does not require** you to open-source your changes. That is the difference
between a permissive license like Apache and a copyleft one like GPL.

### What this means for you specifically

You have taken someone else's Apache-2.0-licensed repository and are modifying
it substantially. That is squarely permitted. The obligations that come with it:

**1. Keep the `LICENSE` file.** Do not delete it. Requirement (a).

**2. Add a `NOTICE` file.** There is none currently. Create one at the root
crediting the original work and stating yours. Something like:

```
Visual Understanding System
Copyright 2026 Jonathan Mukhobe

This product includes software originally developed as the
Production-Grade SLM-Powered OCR Course, licensed under the
Apache License, Version 2.0.
```

This is the cleanest way to satisfy requirements (c) and (d) at once, and it is
what most people do when forking. Do this even though the original has no
NOTICE, because it is how you honour the attribution obligation while making
your own ownership clear.

**3. State that you modified it.** A line in your `README.md` such as "This
project is derived from [original work], licensed under Apache 2.0, and has been
substantially modified" satisfies requirement (b) at the project level. If you
want to be rigorous, individual heavily-modified files can carry a header
comment too.

**4. Fill in the appendix, or add your own copyright.** You may add your own
copyright statement covering your modifications. Section 4 explicitly allows
this: "You may add Your own copyright statement to Your modifications". The
original author's rights in the original code do not go away, but your new work
is yours.

**5. Removing the contributors' names from the README is fine.** Deleting a
marketing bio section is not the same as stripping a legal attribution notice.
The README contributor table is promotional, not a copyright notice. Adding a
`NOTICE` file crediting the original project is both more correct legally and
more honest than keeping personal bios you did not write.

### A discrepancy you need to fix

`README.md` line 353 says:

> This project is licensed under the MIT License - see the [LICENSE](LICENSE)
> file for details.

**But `LICENSE` is Apache 2.0, not MIT.** These are different licenses with
different obligations (MIT has no patent grant and much lighter redistribution
requirements). Whether this was an oversight in the original or a deliberate
change that only got applied to one of the two files, it is a genuine
contradiction in the repository as it stands.

For your version, decide which you mean and make both files agree. Given that
the actual `LICENSE` file is Apache 2.0 and that is what you received the code
under, the safe path is to keep Apache 2.0 and correct the README sentence.

### If you want a different license instead

You are constrained here. You cannot relicense someone else's code. What you
*can* do:

- Keep Apache 2.0 for the whole thing. Simplest and safest.
- License your new original files under something else while the inherited files
  stay Apache 2.0. Legally workable but confusing to users, and you must be able
  to say clearly which files are which.
- If you want your version to be more restrictive (for example, requiring
  derivatives to stay open), you can apply GPL to your combined work, because
  Apache 2.0 is compatible with GPLv3 in that direction. This is a real decision
  with real consequences and worth thinking about before you publish rather than
  after.

**Nothing here is legal advice.** For a hobby or learning project, the checklist
above is proportionate. If this becomes a commercial product, have somebody
qualified look at it.

---

## 13. Honest Gaps and Things That Do Not Match

Things I found while reading the repository that you should know about before
you build on it. None of these are catastrophic. All of them are worth knowing.

**1. The MCP server does not exist.** Week 6 of the README promises "wrapping
the pipeline in an MCP server for Claude Code". There is no MCP code anywhere in
the repository. If you want that capability, you are writing it from scratch.
(Reasonably straightforward: an MCP server that calls `POST /process` and polls
`GET /status/{id}`.)

**2. Multi-Token Prediction is claimed but not configured.** The README
repeatedly credits MTP with a "~50% throughput increase" and the 1.86 pages per
second figure. There is no MTP flag in `server/entrypoint.sh`. Either the model
enables it implicitly or the claim is aspirational. Treat the performance
numbers as unverified until you measure them yourself.

**3. The README's license statement contradicts the LICENSE file.** Covered in
section 12.

**4. `MAX_NUM_SEQS` has two different values.** `entrypoint.sh` defaults it to
256; `kustomization.yml` sets it to 512; the README describes 512. The ConfigMap
wins at runtime, so the effective value is 512, but the script's default is
inconsistent with everything else and would confuse anyone running the container
outside Kubernetes.

**5. The file `deployment-api.yml` also contains the worker deployment.** Two
unrelated deployments in one file with a misleading name. Worth splitting into
`deployment-api.yml` and `deployment-worker.yml` while you are reorganising.

**6. Redis has no persistence, no password, and one replica.** If that pod dies,
every in-flight job and every unretrieved result is gone. For a production
system this is a real single point of failure. Redis persistence (AOF or RDB), a
password, and a replica are all straightforward additions.

**7. There are no automated tests anywhere.** No unit tests for the Rust API, no
tests for the worker logic, no integration test, no load test, no CI pipeline.
For a repository that describes itself as production-grade this is a notable
absence and an obvious place for you to add value.

**8. No dead-letter queue and no retry.** If the worker crashes mid-batch, the
tasks it had already popped off the queue are lost. They are marked `failed` if
the exception is caught, but if the pod is killed outright (out of memory, node
eviction) the tasks simply vanish. Redis has patterns for this
(`BRPOPLPUSH` into a processing list) that would make the system genuinely
crash-safe.

**9. Queue ordering is inconsistent.** The producer uses `LPUSH` (add to the
left). The worker's first fetch uses `BRPOP` (take from the right, so
first-in-first-out), but the collector window then uses `LPOP` (take from the
left, so last-in-first-out). Under load, tasks collected during the window are
processed newest-first while the first task of each batch is oldest-first. Not a
bug that breaks anything, but a subtle unfairness worth being aware of.

**10. Base64 costs you 33 percent.** Every file is stored roughly a third larger
than it needs to be, in RAM, on a machine you pay for by the gigabyte. Redis
handles binary data natively. This was presumably done for convenience across
the Rust and Python boundary.

**11. There is no result expiry.** Redis keys are never given a TTL. The `data`
field is blanked after processing, but the result text and all the metadata stay
forever. Over months this fills memory. A `EXPIRE` call after completion would
fix it in one line.

**12. The typo in the deployment guide.** `docs/aks_deployment.md` line 54 says
"Downlaod AKS credentials". Trivial, but you will want to catch things like this
while you are editing.

**13. The debug output in the deployment guide does not match the ingest job.**
The example `ls` output in `aks_deployment.md` shows a `Qwen3-VL-Embedding-2B`
model that the ingest job never downloads. Leftover from an earlier version of
the architecture.

---

## 14. Where to Tweak It to Make It More Interesting

You said you want to make this more complex, more interesting, and usable in a
specific domain. Here is a map of where the leverage is, roughly ordered from
cheapest to most ambitious.

### Tier 1: Cheap changes with real impact

**Rewrite the prompts.** `realtime_consumer/config.yaml`, under
`task_prompt_mapping`. Four strings. Changing "OCR and recognize the text in
this image" to something domain-specific ("This is a page from a medical lab
report. Transcribe it exactly, preserving units and reference ranges") measurably
changes the output. This is the single highest ratio of impact to effort in the
entire repository.

**Retune the label mapping.** Also in `config.yaml`, under
`label_task_mapping`. Right now charts and images are `skip`ped, meaning they are
detected but never described. Move `chart` from `skip` to a new task type with a
chart-specific prompt and suddenly the system understands graphs. Conversely, if
your documents have meaningful headers (a case number in a running header, for
instance), move `header` out of `abandon`.

**Add result expiry and a TTL.** One line in `worker.py`. Fixes gap 11.

**Add structured output.** Right now you get Markdown plus a layout JSON. Add a
third stage that takes the Markdown and asks the model to fill a JSON schema
(vendor, invoice number, line items, total). This turns a document reader into a
data extraction system, which is what most real applications actually want.

### Tier 2: Meaningful engineering

**Make it crash-safe.** Replace `BRPOP` with `BRPOPLPUSH` into a processing
list, add a reaper that returns abandoned tasks to the queue, add retry counts,
add a dead-letter queue for tasks that fail repeatedly. This is textbook
distributed systems work and it is the difference between a demo and something
you would trust.

**Add tests and CI.** Unit tests for the Rust handlers, a fake Redis for the
worker loop, an end-to-end test with a sample document, and a GitHub Actions
workflow. Gap 7.

**Add a webhook or streaming results.** Right now clients poll. Add a callback
URL to the submit request, or a Server-Sent Events endpoint, so results push to
the client the instant they are ready.

**Build the MCP server.** Gap 1. It is genuinely not much code and it makes the
whole pipeline callable by AI assistants, which is a compelling demo.

**Add a real evaluation harness.** Take a set of documents with known correct
output, run them through, and score accuracy. Without this you cannot tell
whether a prompt change helped or hurt. Every serious document AI project has
one.

**Add caching.** Hash the incoming file. If you have seen it before, return the
stored result instantly instead of spending GPU time. Document workflows have
enormous duplication (the same form template, resubmitted invoices) and this can
cut load dramatically.

### Tier 3: Domain specialisation

This is where you turn it into *your* system rather than a generic one. Pick a
domain and follow it all the way through:

**Medical records.** Add a de-identification stage that finds and redacts
patient names and identifiers before anything is stored. Add a medical
terminology validation pass. Change the storage model so nothing persists
unencrypted. This is a genuinely hard, genuinely valuable problem.

**Legal contracts.** Add clause classification, add cross-reference resolution
(clause 4.2 refers to clause 8.1), add a comparison mode that diffs two versions
of a contract at the clause level.

**Financial statements.** Add table validation (do the columns sum to the
stated total?), add multi-page table stitching (a table that spans pages 3 to
5), add a confidence score per extracted number so a human can review only the
uncertain ones.

**Historical archives.** Handwriting is the hard case. Add a preprocessing stage
for old paper (deskewing, contrast normalisation, bleed-through removal), add
period-appropriate language handling, add uncertainty markers where the model is
guessing.

**Multilingual or non-Latin script.** The layout detector already has a
`vertical_text` label. Building out proper handling for vertical scripts,
right-to-left languages, or mixed-script documents is substantial and
differentiating work.

### Tier 4: Architectural ambition

**Add a human-in-the-loop review interface.** A web UI that shows the page with
the detected boxes overlaid, the extracted text beside it, and lets a person
correct errors. Feed the corrections back as evaluation data. This is what
actually gets document AI adopted in businesses.

**Add a second model and route between them.** Use the small fast model by
default; when its confidence is low or the region is a complex chart, escalate
that region to a larger model. Cost-aware routing is a genuinely interesting
systems problem.

**Add fine-tuning.** Collect corrections from your review interface, fine-tune
the SLM on your specific document type, and measure the improvement against your
evaluation harness. This closes the loop from system to product.

**Make it multi-tenant.** Separate queues per customer, per-tenant rate limits,
per-tenant model configuration, usage metering and billing. This is what turns
the architecture into a business.

**Add full observability.** Traces that follow one document through all four
components, a Grafana dashboard showing queue depth against GPU utilisation
against cost per page, and alerting on quality regressions.

### A word on where to start

The temptation is to start with the ambitious things. Do not. Start by getting
the existing system running end to end, even on a single cheap GPU with the
`maas.enabled` flag or a locally-run small model. Feed it your own documents.
Look at what comes out. **The gaps you find in the output will tell you which of
the above matters for your domain far more reliably than any list I can write.**

The prompts in `config.yaml` and the label mapping beneath them are where you
should spend your first day. They are two screens of text and they control more
of the system's actual behaviour than any other part of the codebase.
