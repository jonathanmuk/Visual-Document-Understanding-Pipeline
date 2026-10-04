# Visual Document Understanding Pipeline: A Plain-Language Explanation

This document explains what this repository is, what every piece of it does, and
how the pieces fit together. It is written for someone who has never heard of
OCR or SLMs. No prior knowledge of Kubernetes, GPUs, or Rust is assumed.

Read it top to bottom the first time. After that, use the table of contents to
jump to the part you need.

## Table of Contents

1. [The One-Paragraph Version](#1-the-one-paragraph-version)
2. [Vocabulary: Every Term You Need](#2-vocabulary-every-term-you-need)
3. [The Core Idea, With an Analogy](#3-the-core-idea-with-an-analogy)
4. [The Components and What Each One Does](#4-the-components-and-what-each-one-does)
5. [The Life of a Single Document](#5-the-life-of-a-single-document)
6. [Folder-by-Folder Tour of the Repository](#6-folder-by-folder-tour-of-the-repository)
7. [Why It Was Built This Way: The Design Decisions](#7-why-it-was-built-this-way-the-design-decisions)
8. [What Domains This Project Cuts Across](#8-what-domains-this-project-cuts-across)
9. [What Problems It Solves and Where It Applies](#9-what-problems-it-solves-and-where-it-applies)
10. [The Cost Reality](#10-the-cost-reality)
11. [Known Limits](#11-known-limits)
12. [Ideas for Extending It](#12-ideas-for-extending-it)

---

## 1. The One-Paragraph Version

You give this system a PDF or a photograph of a document. It gives you back
clean, structured text: paragraphs in order, tables as real tables, maths as
proper formulas, and written descriptions of the charts. It does
this not with old-fashioned character matching but with a small AI model that
actually looks at the page and reads it the way a person would. The whole thing
runs on rented cloud computers with graphics cards, it wakes up when work
arrives and goes back to sleep when there is none, and it is locked behind a
private front door so nobody on the open internet can run up your bill.

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

This repository has one: see Component 7 in section 4, and
[docs/mcp_setup.md](docs/mcp_setup.md) to connect it to Claude Code or Claude
Desktop.

### API Gateway (Azure API Management)

A guarded front door in front of your service. It checks who you are, counts how
many requests you have made, blocks you if you make too many, and only then
passes the request through.

The Azure deployment guide sets one up. On Google Cloud the system stays
private, reachable only from inside your network, and the choice of gateway is
still open (`docs/gke_deployment.md`, section 12).

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

## 4. The Components and What Each One Does

The system has nine parts. The first five do the reading: the front door, the
queue, the worker, the model server, and the autoscaler. The other four keep it
reliable, visible, usable by AI assistants, and safe.

### Component 1: The Rust Producer API

**Where:** `realtime_producer/src/lib.rs` (`main.rs` only starts it)
**Runs on:** cheap CPU-only machines (node pool `apinp`)
**Job:** accept files, hand out tickets, report status

It never reads a document itself. It takes the file, puts the job in line, and
immediately hands back a ticket. It is about 560 lines of Rust, comments and its
own small tests included, and it exposes five endpoints:

| Endpoint | What it does |
| :--- | :--- |
| `POST /process` | You upload a file. The API checks it is really a PDF, PNG, or JPEG by reading its first bytes, generates a unique ID, stores the file in Redis, adds the ID to the waiting queue, and immediately returns `{ task_id, status: "queued" }` with HTTP 202 Accepted. If the identical file was read recently, it answers at once with 200 and `cached: true` instead; if it is being read right now, it hands back that same ticket with `deduplicated: true`. Text in the file field gets 400, an unsupported format gets 415, and anything over 10 MB gets 413. An optional `callback_url` field asks to be called when the document is done. |
| `GET /status/{task_id}` | You ask about your ticket. Returns `status` (queued, processing, done, or failed), `attempts`, the `result` once done, the `error` if it failed, a `warning` if it finished with parts missing, and `callback_status` if a callback was asked for. |
| `GET /health` | Answers 200 if the process is up. Kubernetes uses this to decide whether to restart the pod. |
| `GET /ready` | Answers 200 only if Redis answers. Kubernetes uses this to decide whether to send the pod traffic. |
| `GET /metrics` | Prometheus metrics: requests by route and status, uploads rejected by reason, upload sizes by type, and how often the cache helped. |

Six details worth understanding:

**It accepts up to 10 MB, exactly.** Axum's default upload limit is around 2 MB,
which would reject most real PDFs. The code disables the default and sets a
ceiling of 10 MiB (10,485,760 bytes): a file of exactly that size is accepted,
one byte more is refused. A ceiling exists deliberately: without one, a single
attacker uploading a 5 GB file could exhaust the server's memory.

**It checks what the file really is.** A PDF starts with `%PDF-`, a PNG with a
fixed eight-byte signature, a JPEG with the bytes `FF D8 FF`. Anything else is
refused before it is stored. The type the API records comes from these bytes,
never from the file's name, so a PDF uploaded as `scan.jpg` is still treated as
a PDF. (Without this check, a mistyped curl command could queue the text of a
file path as if it were a document, and send it for paid reading.)

**It writes everything in one atomic operation.** The file, the task's record
card (status, filename, type), its fingerprint, and its place in the queue go
into Redis in a single transaction. If the code wrote the record first and the
file second, a worker could grab the job in between and find no file. One
transaction means the worker either sees everything or nothing.

**It stores the file as it is.** The file's bytes go into Redis unchanged, in a
drawer of their own. Converting them to base64 text would make every document a
third bigger, and keeping the document inside the task record would drag it out
of Redis with every status check.

**It remembers what it has read.** It takes a fingerprint of every upload (a
SHA-256 hash: the same bytes always give the same fingerprint). If the same
document was read recently, the stored answer comes straight back and no GPU is
touched. A client that wants a new reading anyway sends
`Cache-Control: no-cache`, and a request that asks for a callback always gets
its own reading, so its callback fires. The fingerprint also includes the
pipeline version and the profile, so changing the prompts never serves an
answer made under the old ones, and an answer that came back with parts missing
is never reused.

**Why Rust for this?** Because this component does almost nothing intellectually
but must do it thousands of times a second without stumbling. Rust gives
predictable speed, tiny memory usage (the pod is limited to 256 MB of RAM), and
a small container image (about 18 MB). Its resource request in the Kubernetes
manifest is 100 millicores of CPU, meaning one tenth of a single processor core.

### Component 2: Redis, the State Store

**Where:** `k8s/aks/apps/redis-deployment.yml`
**Runs on:** high-memory CPU machines (node pool `redisnp`)
**Job:** hold the queue and hold the data

Redis holds seven structures:

1. `ocr_tasks`, the **waiting queue**. Task IDs that nobody has picked up yet.
   New ones go on at the head; workers take from the tail, so the oldest goes
   first.
2. `ocr_tasks:processing`, the **in-progress list**. A task is moved here in the
   same instant a worker claims it, and removed only when it reaches a final
   state. A task is never in limbo: it is on exactly one of these two lists, or
   it is finished.
3. `ocr_tasks:dead`, the **dead letter queue**. Tasks that failed for good, kept
   so an operator can see what went wrong.
4. One hash per task, keyed `task:{id}`, holding status, filename, the detected
   type, how many attempts it has had, when it was claimed, and eventually the
   result, error, or warning. Finished tasks expire after a day
   (`RESULT_TTL_SECONDS`), so memory does not grow forever.
5. The document itself, keyed `taskdata:{id}`, as raw bytes. Deleted the moment
   its task is finished.
6. The cache fingerprints, keyed `cache:{version}:{profile}:{hash}`, each
   pointing at the task that read that exact document.
7. `ocr_webhooks`, finished tasks whose client asked to be called back.

Redis requires a password (every component reads it from one Kubernetes
Secret), writes every change to a log on disk so a restart loses nothing (if
the whole machine fails, at most the last second of changes), and keeps that log
on a persistent volume. It is still a single copy: while it restarts, the API
refuses new uploads until it is back.

The queue is the shock absorber of the entire system. Uploads arrive in bursts
(someone drags in 500 invoices at once). GPUs process at a steady rate. Without
a buffer between them, either the API rejects uploads or the GPU is
alternately overwhelmed and idle. The queue smooths this out completely.

Redis also acts as the signal KEDA watches. "Queue is 40 items long" is a
directly meaningful statement about how much hardware you need right now, in a
way that "CPU is at 60 percent" never is.

One clever touch: when a task finishes, the stored document is deleted at once.
It is no longer needed once the text has been extracted, and Redis lives
entirely in RAM. Keeping it would fill memory with completed work.

### Component 3: The Python Consumer Worker

**Where:** `realtime_consumer/worker.py` and `realtime_consumer/config.yaml`
**Runs on:** T4 GPU machines (node pool `gpunpt4`)
**Job:** pull work from the queue, find the regions on each page, orchestrate the reading

This is the brain of the pipeline: about 300 lines of Python, with the queue
handling (`vdu_queue.py`) and the document checks (`vdu_inspect.py`) in two
small files beside it. It runs an endless loop:

**Step 1: Wait for a job.** It asks Redis to move the oldest waiting task onto
the in-progress list, and blocks (sleeps) until one exists. This is important
twice over: it does not repeatedly ask "anything yet? anything yet?", which
would burn CPU, and because the move is one atomic Redis command (`BLMOVE`),
there is no moment where the task has left the queue but not yet arrived
anywhere. If the worker dies a millisecond later, the task is still on the
in-progress list.

**Step 2: The collector window.** Once one job arrives, instead of processing it
immediately, the worker waits up to 100 milliseconds to see whether more jobs
turn up, collecting up to 4 in total. Each one is moved to the in-progress list
the same way, oldest first.

**The analogy:** a lift that waits three seconds before closing its doors. You
lose three seconds on the first passenger and save an entire round trip when
four people get in. 100 milliseconds is imperceptible to a user and lets the
GPU process four pages in a single pass rather than four separate passes, each
with its own fixed setup cost.

**Step 3: Check each file, then write it to RAM.** Each file is read back from
Redis as raw bytes and opened once on the CPU, with the same libraries the OCR
library uses. A PDF that will not open, has more than 200 pages, or a picture
that will not decode or is absurdly large, fails right here, alone, with a
reason, and is never retried: the same bad bytes would fail the same way every
time. Without this check a bad file would reach the GPU inside a batch and could
take the other documents in that batch down with it. The good files are written
to `/dev/shm/{task_id}.{ext}`, then given read permissions (`0o644`) so that any
sub-process the OCR library spawns can open it regardless of which user account
it runs as.

**Step 4: Hand off to the OCR engine.** The worker calls
`ocr_engine.parse(temp_paths)` with the file paths, not the file contents. The
library decides how to handle each file by looking at its **name**: a file ending
in `.pdf` is treated as a PDF, anything else as an image. PDFs get rasterised into
images at 200 DPI using a library called pypdfium2. Images are loaded directly.

This is why the worker names each temporary file with the type the API detected
from the file's first bytes. (The SDK only looks at a file's opening bytes in
its cloud mode; in the self-hosted mode used in production it goes by the name.)

**Step 5: Layout detection runs on the local T4.** PP-DocLayoutV3 draws boxes on
each page and assigns each one of 25 possible labels: `text`, `table`,
`display_formula`, `chart`, `doc_title`, `header`, `footer`, `seal`, and so on.

**Step 6: Regions get sorted into buckets.** The config file maps each label to
one of these fates:

| Fate | Labels | Meaning |
| :--- | :--- | :--- |
| `text` | paragraphs, titles, abstracts, references | Send to the AI with a "transcribe this" prompt |
| `table` | tables | Send to the AI with a "convert to Markdown table" prompt |
| `formula` | display and inline formulas | Send to the AI with a "convert to LaTeX" prompt |
| `chart` | charts and graphs | Send to the AI with a "describe this chart" prompt; the description, starting "Chart:", goes into the text |
| `skip` | photos, logos, other images | Keep the region's position, do not transcribe it |
| `abandon` | headers, footers, page numbers, footnotes | Throw away entirely |

**Profiles** change these rules and prompts for a kind of document, without
editing `config.yaml`. The `finance` profile keeps page headers and footers,
where invoice and registration numbers live, and asks for every amount to be
copied character for character. The `academic` profile keeps footnotes and
writes inline maths as LaTeX. Choose one with `VDU_PROFILE`. The worker refuses
to start on a profile that would silently lose a kind of region.

This bucketing is where a lot of the quality comes from. Page furniture (running
headers, page numbers) is noise that would pollute the extracted text, so it
never reaches the AI. Different content types get different instructions, so the
model knows a table should come back as a table.

**Step 7: Regions go to the AI, up to 512 at a time.** The `max_workers: 512`
setting means the worker fires up to 512 concurrent requests at the vLLM server.
This number is chosen deliberately to match vLLM's own `MAX_NUM_SEQS=512`: the
worker is sized to exactly fill the engine's capacity and no more.

**Step 8: Check the result, then store it.** The pieces come back, get stitched
into a single Markdown document plus a JSON structure describing the layout. But
before anything is written, the worker checks the result is real: if the SDK
recorded an error, returned nothing, or returned an empty document, the task is
**not** marked done. A failure that could succeed next time (a network blip, an
overloaded model) puts the task back on the waiting queue for another attempt, up
to `MAX_ATTEMPTS` (3). A failure that cannot succeed on retry (no credit on the
account, a bad API key) fails immediately. Either way the real reason is stored
in the `error` field and the task goes to the dead letter queue. Only a genuine
result is written with `status: "done"`, along with an expiry time.

One more honesty check. In self-hosted mode the SDK quietly drops any region the
model failed to read, so a page can come back looking complete when it is not.
The worker listens to the SDK's own log stream during the parse and counts those
failures. If any happened, the result is still delivered, but with a `warning`
saying how many regions were lost. The count covers the whole batch, not each
document: see section 11.

**Step 9: Clean up.** The temporary files in `/dev/shm` are deleted in a
`finally` block, so they get removed even if processing crashed. Forgetting this
would slowly fill the RAM disk (limited to 4 GB in the manifest) until the pod
died.

One deliberate constraint: the worker processes **one batch at a time** and
waits for it to finish before fetching more. This looks like it is throttling
itself, but it is preventing the T4's 16 GB of VRAM from being oversubscribed by
several overlapping batches, which would cause thrashing and make everything
slower.

**In Z.ai mode** (`maas.enabled: true`, used for testing without a GPU), steps 5
to 7 happen on Z.ai's computers instead: the SDK sends the whole document to
Z.ai's service. Everything else, the queue, the checks, and the result handling,
is the same. Profiles have no effect there, because Z.ai uses its own prompts.

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
| `--max-num-seqs` | 512 | How many conversations can be in flight simultaneously. |
| `--enable-chunked-prefill` | on | Splits the work of loading a large image into smaller pieces so it does not block requests that are already mid-answer. Without this, one big image causes a latency spike for everyone. |
| `--limit-mm-per-prompt` | 1 image, 0 video | One image per request, no video. Prevents a malformed request from consuming unbounded memory. |
| CUDA graphs (left on) | default | vLLM pre-compiles the sequence of GPU operations at startup instead of dispatching them one at a time. Makes startup slower and generation much faster. |

**One switch is off by default: multi-token prediction.** Setting
`SPECULATIVE_CONFIG` on the vLLM deployment (the model card suggests
`{"method":"qwen3_next_mtp","num_speculative_tokens":2}`) lets the model guess
several words ahead and check them in one step. It usually helps most when few
requests are running at once, so measure it at your real load before leaving it
on.

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

**The A100 inference server** scales from 0 to 4 copies on two signals. The
first gets it from zero to one: if any document is waiting or in progress, vLLM
must exist. That comes straight from the Redis lists. The second decides whether
one is enough: a Prometheus metric, `vllm:num_requests_waiting`, crossing 1. In
plain terms: "if the AI engine has even one request sitting in its waiting room,
start another A100". The metric alone could never start the first A100, because
with no vLLM running there is nothing to measure.

**The worker and the A100 server also have a cron rule** keeping one copy alive
on weekdays from 8am to 6pm New York time. (The API never goes below one copy,
so it needs none.) This is the "warm start". Loading a model onto a GPU and
compiling CUDA graphs takes minutes; without the warm start, the first person to
upload a document each morning would wait several minutes for the machine to
boot, the driver to load, and the model to initialise. The cron rule pays for a
few idle hours to avoid that.

KEDA checks the worker's signal every 15 seconds and vLLM's every 10. The
`cooldownPeriod: 300` means the system waits 5 minutes of quiet before shutting
a machine down, so it does not thrash on and off during a stream of sporadic
requests.

### Component 6: The Reaper

**Where:** `realtime_consumer/reaper.py`
**Runs on:** the cheap CPU pool, always, one copy
**Job:** put back tasks whose worker died

Every 30 seconds it looks at the in-progress list. Any task that was claimed
longer ago than `STALE_AFTER_SECONDS` (15 minutes by default) belongs to a worker
that is no longer coming back: it ran out of memory, its node was taken away, or
it was scaled down mid-document. The reaper moves that task back to the front of
the waiting queue so the next worker picks it up first. If a task has already
used up its attempts, the reaper sends it to the dead letter queue instead, so a
document that reliably crashes workers cannot loop forever.

**The analogy:** the difference between a waiter taking your order and
immediately tearing up the ticket, versus keeping it clipped to the rail until
the food is actually served. If the waiter goes home mid-shift, the second
arrangement means someone else can pick up the order.

Because it is always running, the reaper is also the one that publishes the
depth of each queue as a metric. The workers cannot do that reliably, since they
are scaled to zero when there is no work.

For the same reason it makes the **webhook calls**. When a client handed in a
document with a `callback_url`, the reaper calls that address with the result
once the task is finished, so the client does not have to keep asking. The calls
run on threads of their own, so one goes out moments after the task finishes,
not on the 30-second cycle, and a failed call is tried up to three times. Each
call is signed with a shared secret (like a wax seal), so the client can check
it really came from this system and was not replayed later. Callbacks are off
until the operator lists which hosts may be called, which stops anyone using the
system to reach addresses it should not. Doing this in the reaper, not the
worker, means a slow client can never hold up a GPU.

### Component 7: The MCP Server

**Where:** `mcp_server/`
**Runs on:** the cheap CPU pool, or on your own computer next to an assistant
**Job:** let an AI assistant use the pipeline as a tool

The Model Context Protocol is the standard way to give an AI assistant a new
capability: the assistant is the *host*, it runs an MCP *client*, and our
program is an MCP *server* that says "here is what I can do". Ours says it can
read documents. Any assistant that speaks MCP, such as Claude Code or Claude
Desktop, then gets that ability without anyone writing glue code.

The server is deliberately thin. It knows nothing about models or GPUs. Every
document still goes through the Rust API, the queue, the worker, and vLLM; the
MCP server only translates between an assistant's tool calls and the API's
HTTP. It offers the three kinds of thing an MCP server can offer:

| Kind | Who decides to use it | What ours provides |
| :--- | :--- | :--- |
| **Tools** | The model | `read_document` (submit, wait, return text and layout), `submit_document` and `get_document_status` (for large documents, so the assistant can keep working), `extract_structured_data` (text plus a schema of fields to fill) |
| **Resources** | The application | The result schema, the list of layout labels, and any finished document's Markdown or layout by task ID |
| **Prompts** | The user | `/extract_invoice`, `/summarise_document`, `/compare_documents` |

Six things worth knowing about the design:

**It asks when it needs to.** `extract_structured_data` needs to know what kind
of document it is looking at. If the assistant did not say, the server asks the
user, through the protocol's *elicitation* feature, rather than guessing.

**It reports progress.** A long document does not leave the assistant staring
at silence. The server sends progress notifications as the task moves from
queued to processing to done.

**It uses the cache.** A document the system read recently comes back at once,
marked `cached`. Every tool accepts `fresh: true` for a new reading.

**It never assumes dollars.** Invoices come in every currency and number
format. The reading is asked to copy every amount exactly as printed, so
`1.046,01 €` stays `1.046,01 €` (the `finance` profile insists on it), and the
evaluation set includes a euro invoice to check that it does. Extraction then
asks for the document's own currency, never a converted amount: the assistant
is told to read `1.046,01` as 1046.01 euros, and to leave a currency the
document does not make clear empty rather than guess it.

**It is careful with addresses.** A document an assistant reads could contain
text written to trick it into fetching something internal. So the server itself
refuses any web address that is not https or that leads to a private address
(Redis, the model server, the cloud's own metadata service), and checks every
redirect again. Locally, it reads files only from the folders you allow.

**It runs in two places.** Locally it speaks over stdio, the assistant launching
it as a subprocess. In the cluster it speaks Streamable HTTP behind a bearer
token, on an internal load balancer of its own: a private address inside your
cloud network. Local file paths only work in the local mode; the cluster's
server is given web addresses. The gateway publishes only the REST API, so an
assistant outside the private network runs the server locally and points it at
the gateway with a key. [docs/mcp_setup.md](docs/mcp_setup.md) covers every way
to connect, and [docs/adr/0003-mcp-server.md](docs/adr/0003-mcp-server.md)
records why the server exists.

### Component 8: Observability

**Where:** `k8s/*/observability/`

Prometheus does not discover things by magic; it scrapes what it is told to. The
`ServiceMonitor` objects tell it to scrape vLLM, the worker, the reaper, and the
API. Without them, none of the application metrics exist, and the A100 scaling
rule that watches vLLM's queue would silently never fire. A ServiceMonitor finds
its targets by the labels on the Service itself, not on the pods, so every
Service it watches carries an `app` label, and
`tests/manifests/check_references.py` checks on every push that each monitor
matches a real Service.

A Grafana dashboard, **Visual Document Understanding Pipeline**, shows the queues, tasks per
minute by outcome, vLLM's waiting and running requests, GPU utilisation, stage
timings, replica counts, and rejected uploads. (On Google Cloud the GPU panel
stays empty: GKE keeps GPU numbers in its own Cloud Monitoring.) Five alerts
fire when documents are failing permanently, when work is waiting but nothing
completes, when claimed tasks stop finishing, when vLLM is missing while work
waits, and when the model starts failing on many regions.

Every component logs JSON, one object per line, with the `task_id` on every line
that concerns a task, so one document can be followed across all of them.

### Component 9: The Locks

**Where:** `k8s/*/networking/network-policies.yml` and the `securityContext` in
every deployment

Security here is a set of plain rules, each enforced by something:

- **Only the right parts can talk to each other.** Nothing may connect to
  anything unless a rule allows it. Redis accepts only the API, the worker, the
  reaper, and KEDA (which reads the queue's length); the model server accepts
  only the worker, and Prometheus collecting its numbers. The cluster's network
  enforces this, and the deployment guides create the cluster with the engine
  that does it.
- **No part runs as the all-powerful user.** Every serving container runs as an
  ordinary user, on a disk it cannot write to, with no special powers, so a
  break-in cannot change its programs. The one exception is the one-off job that
  downloads the model, which runs once and is then deleted: on Google Cloud the
  shared disk it writes the model to belongs to root, so an ordinary user could
  not write there.
- **No passwords in the code.** Every password, token, and key is a Kubernetes
  Secret made by hand. Every file in the repository has been scanned for leaked
  secrets (with gitleaks), and none were found.
- **Known-vulnerable libraries are caught.** Every change is checked against
  public vulnerability lists, and updates are proposed weekly.

Section 11 lists the known limits.

---

## 5. The Life of a Single Document

Follow one invoice through the whole system, on a weekday morning with a warm
worker and a warm A100 already running.

**Second 0.00.** You run `curl -X POST .../process -F "file=@invoice.pdf"`. On
Azure the request hits the API gateway first (API Management). It checks your
subscription key, and your sign-in token if you send one, checks you have not
exceeded 100 requests per minute, and forwards you to the internal load
balancer, which forwards you to a Rust API pod. (On Google Cloud, where no
gateway is set up yet, you are already inside the private network and go
straight to the load balancer.)

**Second 0.01.** The Rust API reads the multipart form, finds the field named
`file`, and reads the file's first bytes: `%PDF-`, so it is a PDF, whatever it
was called. It takes the file's fingerprint and checks the cache: this exact
invoice has not been read in the last day. It generates a UUID, say `4f2a...`,
and in one transaction stores the PDF bytes as they are under `taskdata:4f2a`,
creates the record card `task:4f2a` with status `queued`, records the
fingerprint, and pushes `4f2a` onto the `ocr_tasks` list.

**Second 0.02.** You receive `{"task_id": "4f2a...", "status": "queued"}` with
HTTP 202. As far as you are concerned, the job is submitted. You are free to go.

**Second 0.03.** The warm worker has been waiting on the queue all along, so it
hears about `4f2a` at once. (With no worker running, KEDA would notice the
waiting document at its next check, within 15 seconds, and ask Kubernetes for
one; if a T4 machine had to start, that takes minutes.)

**Second 0.04.** The worker's `BLMOVE` returns `4f2a`, moving it from the waiting
queue to the in-progress list in the same instant. The worker notes when it
claimed it and starts its 100 ms collection window.

**Second 0.14.** The window closes. Say two other invoices arrived, so the batch
is 3 documents. The worker sets all three to `processing`, reads each one's
bytes, opens each once to check it is a real, readable PDF of at most 200 pages,
and writes them into `/dev/shm/`.

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

**Second 1.25.** The worker checks the result is real: not empty, no error hidden
in it, no regions lost. Then, in one step, it writes the result to `task:4f2a`
with status `done` and an expiry a day away, deletes the stored document,
and takes `4f2a` off the in-progress list. It deletes the temp files from
`/dev/shm`. If you had asked for a callback, the task would also join
`ocr_webhooks`, and the reaper would post the result to your address moments
later, signed.

**Whenever you like.** You call `GET /status/4f2a`. The Rust API reads the
record card from Redis and returns your Markdown and JSON.

**If someone sends the same invoice again today,** the API finds its
fingerprint, sees the task is done, and answers at once with the stored result,
marked `cached`. The queue, the worker, and both GPUs are never involved.

**If the worker had died at second 0.5,** `4f2a` would still be on the
in-progress list. Fifteen minutes later the reaper would put it back at the
front of the waiting queue, and the next worker would read it, as attempt 2.

**Five minutes after the last document**, outside the warm hours, the queue has
been empty for the whole cooldown period. KEDA scales the worker to zero and the
A100 to zero. The cluster autoscaler releases the machines. You stop paying for
them.

---

## 6. Folder-by-Folder Tour of the Repository

### `/` (root)

| File | What it is |
| :--- | :--- |
| `README.md` | The front page: what the system is, how each part works, the life of a document, the repository layout, how to run the tests, and where the project stands. |
| `LICENSE` | Apache License 2.0, unmodified boilerplate. See the README's licence section. |
| `.gitignore` | Standard Python ignore list from GitHub's template collection. Tells git not to track caches, virtual environments, and build artefacts, and keeps `realtime_consumer/config.local.yaml`, which holds your Z.ai key, out of git. |
| `.gitattributes` | Tells git to normalise line endings. Relevant if you work on Windows, because the deployment targets Linux. |
| `system-explanation.md` | This file. |
| `NOTICE` | Attribution to the original Apache 2.0 work this project is derived from, and the project's copyright. |
| `docker-compose.test.yml` | Starts Redis, the API, the reaper, the MCP server, and a small webhook receiver for the smoke test, locked down the same way as the cluster. The real worker can be added in Z.ai mode. |
| `.github/workflows/ci.yml` | Seven jobs that run on every push: Rust tests, worker and tools tests, MCP server tests, the container smoke test, a worker image build, a check of both Kubernetes folders (against the Kubernetes rules, and that every reference between objects resolves), and a scan of every dependency for known vulnerabilities. `.github/dependabot.yml` proposes dependency updates weekly. |

The guides, the tools, and the MCP server are listed in the README's repository
layout.

### `/tests`

| Path | What it is |
| :--- | :--- |
| `fixtures/sample.pdf`, `fixtures/sample.png` | Tiny, hand-generated documents for the tests, the tools, and the testing guide. |
| `fixtures/README.md` | What each fixture is for, and how to add your own documents to the evaluation set. |
| `integration/smoke.py` | 84 checks against the running containers: the API and Redis, the result cache, hostile uploads, webhooks, the reaper, and a real MCP session. |
| `fixtures/eval/` | Three pages whose correct reading is known exactly (an invoice in dollars, a German invoice in euros, and a letter), for scoring reading quality with `tools/evaluate.py`. |
| `manifests/check_references.py` | Reads the Kubernetes objects and checks that every reference between them resolves: a scaler names a real deployment, a monitor matches a real service, a policy selects real pods. |

Component tests live next to the code they test: `realtime_producer/tests/api.rs`
drives the Rust router in-process, `realtime_consumer/tests/` drives the worker,
the reaper, and the webhooks against a fake Redis, `mcp_server/tests/` drives
the MCP server through the SDK's own client, and `tools/tests/` checks the
quality scoring and the throughput arithmetic.

### `/realtime_producer` (the front door, Rust)

This is the producer half of the producer/consumer pattern: it takes documents
in and hands out tickets at once.

| File | What it is |
| :--- | :--- |
| `src/lib.rs` | The whole API: five endpoints, the upload checks, the cache, and the metrics. About 560 lines including comments and its own small tests. (It is a library so the tests can drive it directly.) |
| `src/main.rs` | Starts the API. 27 lines. |
| `tests/api.rs` | Tests that drive the API in-process, against a real Redis when one is available. |
| `Cargo.toml` | Rust's dependency list. Axum for the web server, Tokio for async, Redis, UUID for IDs, SHA-256 for fingerprints, Prometheus for metrics, tracing for logs. |
| `Cargo.lock` | Exact pinned versions of every dependency including transitive ones. Checked in so builds are reproducible. Do not hand-edit. |
| `Dockerfile` | A four-stage build using `cargo-chef`. Stages 1 to 3 build dependencies separately from your code so that changing `main.rs` does not trigger a full rebuild of every library. Stage 4 copies just the compiled binary into a bare Alpine image, producing a container of a few megabytes rather than a few gigabytes. |

**What to know:** this and the MCP server are the only components with a load
balancer of their own (both private), so they are where requests come in from
outside the cluster. This is also the only Rust in the project.

### `/realtime_consumer` (the orchestrator, Python)

| File | What it is |
| :--- | :--- |
| `worker.py` | The queue loop, the collector-window batching, the document checks, the `/dev/shm` handoff, the result checks, and the result writing. The most important file in the repository for understanding behaviour. |
| `vdu_queue.py` | Every Redis operation on the queue, in one place, shared by the worker and the reaper. |
| `vdu_inspect.py` | The check that opens each document on the CPU before it can reach a GPU. |
| `reaper.py` | The reaper: puts back tasks whose worker died, publishes the queue lengths, and delivers callbacks. |
| `vdu_webhook.py` | Signing and sending callbacks, and the list of hosts that may be called. |
| `vdu_profiles.py` and `profiles/` | The finance and academic profiles, laid over `config.yaml`. |
| `vdu_metrics.py` | The numbers the worker publishes for Prometheus. |
| `config.yaml` | About 300 lines configuring the GLM-OCR SDK. This is where the prompts live, where the label-to-task mapping lives, where the concurrency numbers live, and where the vLLM address is set. **This is the file you will tune most when adapting to a domain.** |
| `config.local.yaml` | Your own copy for Z.ai mode, with your API key. Git ignores it; it never leaves your computer. |
| `Dockerfile` | Built on NVIDIA's CUDA 12.1 base image because this container needs GPU access for layout detection. Installs the `glmocr` SDK with its self-hosted and layout extras, the layout model's runtime, OpenCV (the layout model's post-processing uses it), and the queue libraries, and runs as an ordinary user. |
| `Dockerfile.reaper` | A small image for the reaper: Python and three libraries, no CUDA. |
| `tests/` | 70 tests of the worker, the reaper, the profiles, the document checks, and the callbacks, against a fake Redis. |

**The parts of `config.yaml` worth knowing:**

- `pipeline.maas.enabled` (currently `false`): a switch. Set to `true` and the
  SDK stops doing local work and forwards everything to a paid cloud API
  instead. Useful for testing without a GPU.
- `pipeline.ocr_api`: where to find the vLLM server, how long to wait, how many
  times to retry, how big the HTTP connection pool is. In the cluster,
  `GLMOCR_OCR_API_HOST` and `GLMOCR_OCR_API_PORT` in the kustomization take
  precedence over the address written here.
- `pipeline.page_loader.task_prompt_mapping`: the prompts, one each for text,
  tables, formulas, and charts. Editing these is the cheapest,
  highest-leverage way to change the system's behaviour.
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
| `Dockerfile` | Starts from the official vLLM image (v0.21.0), adds three extra Python packages, copies in the entrypoint, and runs as an ordinary user with its caches in `/tmp`. Very thin. |
| `entrypoint.sh` | The launch script with all the vLLM tuning flags, and the switch for multi-token prediction (`SPECULATIVE_CONFIG`, off unless set). Also contains the logic that finds the model weights: it checks `/mnt/models`, then `/app/model-weights`, then `/app/models`. |
| `requirements.txt` | Three packages: `huggingface-hub` for model downloading, `instanttensor` for fast weight loading, `fire` for command-line parsing. |

**Note:** there is no application code here at all. This folder exists purely to
package and configure someone else's inference engine.

### `/k8s` (the deployment blueprints)

Everything here is YAML describing what should exist in the cluster. The
structure is mirrored for the two clouds.

```
k8s/
  aks/                                  Azure
    kustomization.yml                   Ties everything together: shared settings, and your registry, once
    apps/
      deployment-api.yml                The Rust API
      deployment-worker.yml             The Python worker
      deployment-reaper.yml             The reaper and its metrics Service
      deployment-mcp.yml                The MCP server and its private load balancer
      deployment-vlm.yml                The vLLM server plus its internal Service
      redis-deployment.yml              Redis, its disk, and its internal Service
      keda-scaler.yml                   The three autoscaling rules
    networking/
      service.yml                       The internal-only load balancer for the API
      network-policies.yml              Which part may talk to which
      apim-policy.xml                   Azure gateway rules: sign-in tokens and the rate limit
    observability/
      servicemonitors.yml               Tells Prometheus what to scrape
      alerts.yml                        The five alerts
      grafana-dashboard.yml             The dashboard
    infra/
      gpu-operator-values.yaml          NVIDIA driver installation settings (Azure only)
      provisioning/
        pvc.yaml                        Request for 300 GB of shared storage
        ingest-job.yaml                 One-off job that downloads model weights into that storage
  gke/                                  Google Cloud, same structure
    ...                                 (no gpu-operator-values.yaml, GKE manages drivers itself;
                                         no apim-policy.xml, there is no gateway yet)
```

**How the two clouds differ** (this is what `docs/cloud_comparison.md` is
entirely about):

| Thing | Azure | Google |
| :--- | :--- | :--- |
| Where node pools are labelled | `kubernetes.azure.com/agentpool` | `cloud.google.com/gke-nodepool` |
| GPU node taint | Custom: `sku=gpunpa100` | Automatic: `nvidia.com/gpu=present` |
| Container registry, set once in `kustomization.yml` | `<YOUR_ACR_NAME>.azurecr.io/...` | `us-central1-docker.pkg.dev/<YOUR_PROJECT_ID>/ocr-repository/...` |
| GPU drivers | You install the NVIDIA GPU Operator via Helm | Managed for you |
| Gateway | Azure API Management (`apim-policy.xml`) | None yet; the system stays private |
| Shared storage | Azure Blob Fuse, 300 GB | Filestore, 1 TB minimum |
| Private load balancer annotation | `azure-load-balancer-internal: true` | `load-balancer-type: Internal` |

Everything else, including the entire application, all the KEDA rules, the
network policies, and the monitoring, is byte-identical between the two.

**`kustomization.yml` deserves a special mention.** It is the file you actually
apply (`kubectl apply -k k8s/aks/`). It lists which manifests to include and,
more importantly, generates a shared ConfigMap holding the environment variables
that both the worker and the vLLM server read: Redis hostname, batch size, batch
window, model name, and all the vLLM tuning numbers. Changing a number here
changes it everywhere, which is why a value in this file overrides the default
written in `entrypoint.sh`. Its `images` block is where you name your container
registry, once, for every image.

**`ingest-job.yaml` deserves one too.** It is a small Python script embedded in
YAML that downloads model weights straight from Hugging Face into the shared
cluster storage, in the datacentre, using nothing but Python's standard library.
The point: model weights are tens of gigabytes. Downloading them to your laptop
and re-uploading would waste hours and bandwidth. It also writes a marker file
after each model so re-running the job skips what is already there. It checks
the download's certificates, so the weights cannot be swapped in transit. It is
also the one container that runs as root, on purpose: on Google Cloud the shared
disk it writes to belongs to root.

### `/docs` (the deployment manuals)

| File | Length | What it covers |
| :--- | :--- | :--- |
| `azure_onboarding.md` | about 110 lines | Creating an Azure account, understanding the free trial, installing the `az` CLI. Pure browser clicking, no commands until the end. |
| `gcp_onboarding.md` | about 100 lines | The same for Google Cloud, including creating a project. |
| `azure_gpu_prereqs.md` | about 330 lines | **The most practically important doc.** Getting GPU quota. Explains the trap that free trial accounts are hard-capped at zero GPUs, how to upgrade to Pay-As-You-Go, how to request T4 and A100 quota per region, how to find a region that actually has capacity, and how to smoke-test with a single VM before committing to a cluster. |
| `gcp_gpu_prereqs.md` | about 240 lines | The same for Google Cloud, plus an Azure-to-GCP terminology map. |
| `aks_deployment.md` | about 1,000 lines | **The main build guide.** Every command from an empty subscription to a checked, running system: the registry and the cluster (with the network policy engine), the four node pools, the GPU operator, the model weights, the five images, the secrets and pod security, KEDA and Prometheus, a check for every part, Azure API Management with keys and a rate limit, the optional features, running it day to day, and what to do when something goes wrong. |
| `gke_deployment.md` | about 500 lines | The same for Google Cloud. Shorter because GKE handles GPU drivers itself and there is no gateway yet. |
| `cloud_comparison.md` | about 70 lines | What is identical between the two clouds, what differs, and where each difference lives. |
| `mcp_setup.md` | about 420 lines | Connecting Claude Code and Claude Desktop, to your own computer or to a deployed system. |
| `performance.md` | about 140 lines | What has been measured, on what hardware and when, and how to measure the numbers that need GPUs. |
| `adr/` | 9 short files | The architecture decision records: why the system is built the way it is, what each choice costs, and what else was considered. |

### `/images`

One file: `VDU.jpg`, the architecture diagram, drawn by the owner.

---

## 7. Why It Was Built This Way: The Design Decisions

This section is the "so what". Each decision here is the reason the system works
in production rather than only in a demo.

These six shape everything else. They, and the other significant decisions (the
reliable queue, the MCP server, the cache, keeping no archive, callbacks from
the reaper, the MCP server's tokens, and leaving field extraction to the calling
assistant), are written up as architecture decision records in `docs/adr/`: the
situation, the decision, what it costs, and what else was considered.

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

There is a second benefit. With several workers running, one worker's T4 can be
finding the regions on its pages while the A100 reads the regions another worker
sent. The two stages overlap, which is called pipelining, and it is the same
reason a factory has an assembly line rather than one person building the whole
car.

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
balancer, which means a private IP inside the cloud network only; so is the MCP
server's. Redis, the worker, and vLLM are `ClusterIP`, meaning they are
reachable only from inside the cluster. On Azure, the only way in from outside
is through the API gateway; on Google Cloud there is no gateway yet, so only
people inside the private network can reach the system at all. Network
policies also mean that inside the cluster each part can reach only the parts
it needs.

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
tokenisation, prompt engineering (the prompts in `config.yaml` and the profiles
are prompt engineering), sampling parameters (`temperature: 0.0` means "be deterministic,
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
formulas preserved as LaTeX and charts described. The `formula` prompt in the
config exists specifically for this, and the `academic` profile builds on it.

**Education.** Digitising textbooks, making printed material accessible to
screen readers, automated marking of scanned exam scripts.

**Accessibility.** Turning any printed material into something a blind or
low-vision reader can navigate, with charts described rather than silently
skipped. (Photos and logos are skipped; describing them is a natural next step:
see section 12.)

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
step that stops most people, and it is why two of the docs
(`azure_gpu_prereqs.md` and `gcp_gpu_prereqs.md`) exist purely to walk you
through it.

**GPU quota is requested per region and is not guaranteed.** You can be approved
for A100 quota in a region that has no actual A100 capacity available. Both
`*_gpu_prereqs.md` docs cover verifying real availability before you build.

**The mitigations already built into this repository:**

- Scale to zero on both GPU pools.
- Cron-based warm start limited to business hours.
- Rate limiting at the gateway on Azure, so a caller cannot trigger unlimited
  scaling.
- Zero public exposure, so an attacker cannot reach it at all.
- The cluster autoscaler `min-count 0` setting documented in the deployment
  guide.
- The result cache, so a resubmitted document costs nothing.
- The check before the GPU, so a 10,000-page PDF cannot hold a GPU for hours.

What it costs per page on your hardware is not known until you measure it;
`docs/performance.md` shows how.

**Set a billing alert before your first A100 boots.** Both prereq docs say this.
It is good advice.

---

## 11. Known Limits

What the system does not do yet, or does only partly, so nobody assumes more
than it delivers.

**Not yet run on GPUs.** The worker's self-hosted mode and the vLLM server have
not been run on real T4 and A100 machines. Pages per second, the cold start, and
the cost per page are unmeasured; `docs/performance.md` explains how to measure
them. The GPU containers are set up to run as an ordinary user, but that has not
been confirmed on real GPUs: if one fails to start, its log names the path it
could not write, and the fix is an `emptyDir` mounted there, not removing the
restriction.

**Redis is a single copy.** It writes every change to a log on disk, so a
restart loses nothing, but while it restarts the API refuses new uploads.

**Google Cloud has no gateway yet.** The API there is private, but anyone who
can reach its address can send documents without a key or a rate limit
(`docs/gke_deployment.md`, section 12).

**The MCP server's tokens are static.** Anyone holding one can use the server
until it is removed from the Secret. That is fine for a team on a private
network; if people outside the team will connect, OAuth through the MCP SDK is
the upgrade path (`docs/adr/0007-static-bearer-tokens.md`).

**Redis traffic is not encrypted.** It stays inside the cluster network and
network policies limit who can reach it, but it is plain TCP.

**The model download job runs as root**, because on Google Cloud the shared disk
it writes to belongs to root. It runs once and is then deleted.

**Callbacks are not guaranteed.** Each one is tried up to three times; if the
reaper restarts in the middle of a delivery, that callback is lost. The result
is still available by asking for the status, and the task's `callback_status`
says what happened.

**There is no archive of documents.** A document lives in Redis until it is
read (at most two days) and is then deleted
(`docs/adr/0005-no-object-storage-yet.md`).

**The cache reveals recent reads.** Getting `cached: true` back reveals that
someone sent the identical file within the last day. Within one team that is
harmless; between separate customers it is not. Set `RESULT_CACHE=false` on the
API, or add the caller to the cache key, before serving customers who must not
learn about each other (`docs/adr/0004-result-cache.md`).

**Lost regions are counted per batch.** In self-hosted mode the OCR library
quietly drops a region the model failed to read. The worker counts those
failures from the library's own log, but the count covers the whole batch (up
to four documents), so the warning appears on every document in that batch,
even one whose regions were all read. The proper fix belongs in the library.

**An oversized upload from a client that declares no length gets 400, not
413.** Only streaming clients that send no `Content-Length` see this; ordinary
clients get 413. The upload is refused either way.

---

## 12. Ideas for Extending It

For anyone who wants to take the system further, or fit it to a specific
domain, here is a map of where the leverage is, roughly ordered from cheapest to
most ambitious.

The starting point is already in place: domain prompts and label rules (the
`finance` and `academic` profiles), chart descriptions, result expiry,
structured output (the MCP server's `extract_structured_data`), crash safety
(the reaper, retries, and the dead letter queue), tests and CI, callbacks, the
MCP server, an evaluation harness (`tools/evaluate.py` with
`tests/fixtures/eval/`), the result cache, and a Grafana dashboard with alerts.
None of the ideas below is built yet.

### Tier 1: Cheap changes with real impact

**Describe photos and logos.** Charts are described in words, but photos and
logos are `skip`ped: their position is kept and nothing describes them. In
`config.yaml`, giving the `image` label a task and a prompt of its own, the way
`chart` has one, is where to start. For blind and low-vision readers
(section 9), it is the natural next step after charts.

### Tier 2: Meaningful engineering

**Stream results to the client.** Today a client either asks for the status or
has the reaper call it back. A Server-Sent Events endpoint, as an alternative to
callbacks, would push each result to the client the instant it is ready, over a
connection the client keeps open.

**Extract fields on the server.** The MCP server's `extract_structured_data`
returns the text together with a schema, and the calling assistant, itself a
language model, fills in the fields. A client that is not a language model (a
script, a business system) gets the schema and the text, not filled fields. A
step on the server that takes the Markdown and asks a model to fill a JSON
schema (vendor, invoice number, line items, total) would serve those clients
too (`docs/adr/0008-extraction-by-the-calling-model.md`).

**Add OAuth to the MCP server.** Its tokens are static (section 11), which suits
a team on a private network. When people outside the team need access, or
requests must be tied to a person, OAuth through the MCP SDK is the upgrade path
(`docs/adr/0007-static-bearer-tokens.md`).

**Replicate Redis.** Redis is a single copy, so while it restarts the API
refuses new uploads (section 11). A replicated Redis is the next step if that
pause matters.

**Keep an archive copy of documents.** Documents are deleted once they are read
and results expire after a day, so once a result has expired nothing shows what
was read. Having the API also write each upload to object storage (Azure Blob
Storage or Google Cloud Storage), with the result stored next to it, would give
an audit trail. An archive of documents is itself sensitive data, so decide how
long to keep it and who may read it first
(`docs/adr/0005-no-object-storage-yet.md`).

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
per-tenant model configuration, the caller in the cache key (section 11), usage
metering and billing. This is what turns the architecture into a business.

**Add traces and cost per page.** The Grafana dashboard and its alerts exist,
and every log line about a task carries its `task_id`. Still missing are traces
that follow one document through every component, and cost per page on the
dashboard beside queue depth and GPU utilisation. Cost per page needs
measurements on real GPUs first (`docs/performance.md` shows how).

### A word on where to start

The temptation is to start with the ambitious things. Do not. Start by getting
the system running end to end, feed it your own documents, and look at what
comes out. **What the output gets wrong will show which of the ideas above
matters for your documents far more reliably than any list.** Measure each
change with the evaluation harness (`tools/evaluate.py`, with your own pages
added to `tests/fixtures/eval/`), so you know whether it helped or hurt.

The prompts and the region rules, in `config.yaml` or in a profile, are where to
spend the first day. They are two screens of text and they control more of the
system's actual behaviour than any other part of the codebase. They apply in
self-hosted mode; in Z.ai mode, Z.ai uses its own prompts.
