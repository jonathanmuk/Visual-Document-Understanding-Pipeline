# Next Steps: Getting the Pipeline Running

This is a practical guide for someone who has just cloned this repository and
wants to see it actually work. It assumes no prior Kubernetes, cloud, or GPU
experience.

It is organised as four tracks that get progressively more expensive and more
real. Do them in order. Do not jump to Track 3 first, because Track 3 costs real
money per hour and the earlier tracks catch most mistakes for free.

| Track | What it proves | Cost | Time |
| :--- | :--- | :--- | :--- |
| 0. Local plumbing | The API, queue, and status round trip work | Free | 1 hour |
| 1. Local end to end | Real document understanding, no GPU | Small API fee | 2 hours |
| 2. Single cloud GPU | The models actually load and run | A few dollars | 3 hours |
| 3. Full cluster | The whole production system | Tens to hundreds | 1 to 2 days |

---

## Table of Contents

1. [Before You Start: What Is Verified and What Is Not](#1-before-you-start-what-is-verified-and-what-is-not)
2. [Accounts You Will Need](#2-accounts-you-will-need)
3. [Tools to Install on Your Machine](#3-tools-to-install-on-your-machine)
4. [A Windows-Specific Warning You Must Read](#4-a-windows-specific-warning-you-must-read)
5. [Track 0: Local Plumbing Test](#5-track-0-local-plumbing-test)
6. [Track 1: Local End to End Without a GPU](#6-track-1-local-end-to-end-without-a-gpu)
   - [6b. Track 1b: Talk to It From an AI Assistant](#6b-track-1b-talk-to-it-from-an-ai-assistant)
7. [Setting Up Azure, Step by Step](#7-setting-up-azure-step-by-step)
8. [Setting Up Google Cloud Instead](#8-setting-up-google-cloud-instead)
9. [Track 2: One Cloud GPU Machine](#9-track-2-one-cloud-gpu-machine)
10. [Track 3: The Full Kubernetes Deployment](#10-track-3-the-full-kubernetes-deployment)
11. [Cost Safety: Read Before Any GPU Boots](#11-cost-safety-read-before-any-gpu-boots)
12. [Things That Will Break, and What To Do](#12-things-that-will-break-and-what-to-do)
13. [What To Record While Testing](#13-what-to-record-while-testing)

---

## 1. Before You Start: What Is Verified and What Is Not

I checked the external dependencies this repository depends on, because a setup
guide that points you at things that do not exist wastes days. Here is the
status of each.

**Verified to exist as the repository specifies:**

| Dependency | Where the repo pins it | Status |
| :--- | :--- | :--- |
| `glmocr` Python package | `realtime_consumer/Dockerfile`, version `0.1.4` | Exists on PyPI. Versions 0.1.1 through 0.1.5 are published. Version 0.1.4 is real. The extras the Dockerfile requests (`selfhosted`, `layout`) are both declared by the package. Requires Python 3.10 or higher. |
| `Qwen/Qwen3.5-4B` | `k8s/*/kustomization.yml`, ingest job | Exists on Hugging Face. Tagged as an image-text-to-text model, which confirms it takes images as well as text. |
| `PaddlePaddle/PP-DocLayoutV3_safetensors` | `realtime_consumer/config.yaml`, ingest job | Exists on Hugging Face. |
| `vllm/vllm-openai:v0.21.0` | `server/Dockerfile` | Exists on Docker Hub as a multi-architecture tag. |
| `--load-format instanttensor` | `server/entrypoint.sh` | A real vLLM flag. Loads safetensors weights on CUDA using pipelined prefetching and direct I/O. |
| `--mm-encoder-tp-mode data` | `server/entrypoint.sh` | A real vLLM flag. Switches the vision encoder to batch-level data parallelism. See the note below. |

**Two things worth knowing about the model server:**

**Multi-token prediction is off unless you turn it on.** It is an opt-in
switch: set `SPECULATIVE_CONFIG` on the vLLM deployment, for example to
`{"method":"qwen3_next_mtp","num_speculative_tokens":2}`, the value the
Qwen3.5-4B model card recommends. Whether it helps must be measured on your own
hardware. Nothing about reading speed on GPUs has been measured yet:
[docs/performance.md](docs/performance.md) records what has been measured (the
API and Redis) and how to measure the rest.

**`--mm-encoder-tp-mode data` currently does nothing.** That flag distributes
the vision encoder across tensor-parallel ranks. The deployment requests exactly
one GPU per pod and never sets `--tensor-parallel-size`, so tensor parallelism
is 1 and there is nothing to distribute. It is harmless, just inert.

**The GLM-OCR cloud API used in Track 1 is real and cheap.** Its documentation
lists the model as `glm-ocr`, served from `https://api.z.ai/api/paas/v4/layout_parsing`
with bearer token authentication, priced at 0.03 US dollars per million tokens
for both input and output. Section 6.1 covers signing up. Confirm current pricing
yourself before running a large batch, since published prices change.

---

## 2. Accounts You Will Need

You do not need all of these on day one. The track that first requires each is
noted.

| Account | Needed for | Cost | Notes |
| :--- | :--- | :--- | :--- |
| **GitHub** | Track 0 | Free | You already have the code, but you will want your own repository to push to. |
| **Docker Hub** | Track 0 | Free | Only needed to pull base images. You can pull anonymously but you will hit rate limits, so signing in is worth it. |
| **Hugging Face** | Track 2 | Free | Where the model weights live. A token is optional here because neither model this project uses is gated, but create one anyway so you are not blocked if that changes. Settings, then Access Tokens, then create a read token. |
| **GLM-OCR cloud API** | Track 1 only | Paid, small | Only if you want the no-GPU shortcut. Skip if you go straight to Track 2. |
| **Microsoft Azure** | Track 2 and 3 | Paid | The primary cloud for this project. Read the warning below. |
| **Google Cloud** | Alternative to Azure | Paid | Only if you prefer GCP. The repository supports both equally. |

### The single most important thing about the cloud accounts

**A free trial account cannot run GPUs.** This is not a soft limit you can work
around. Both Azure and Google Cloud hard-cap trial subscriptions at zero GPU
quota, and the button to request an increase is disabled on a trial account. You
must upgrade to Pay-As-You-Go before you can request any GPU at all.

You keep whatever free credit you have not spent when you upgrade. But the
upgrade is a required step, not an optional one, and it is where most people
following this project get stuck.

**Section 7 walks through the whole Azure path from signup to approved GPU
quota, click by click.** Section 8 does the same for Google Cloud. Both are
written for someone who has never opened either console before, and both check
off against the repository's own reference documents
([azure_onboarding.md](docs/azure_onboarding.md),
[azure_gpu_prereqs.md](docs/azure_gpu_prereqs.md),
[gcp_onboarding.md](docs/gcp_onboarding.md),
[gcp_gpu_prereqs.md](docs/gcp_gpu_prereqs.md)) with the portal navigation
brought up to date.

**None of that is needed for Track 1.** Track 1 runs entirely on your own
machine and needs only the GLM-OCR API key covered in section 6.1.

**Approved quota is not the same as available capacity.** You can be granted
A100 quota in a region that has no A100 machines free. Both prerequisite
documents cover how to check real availability before you build a cluster. Do
that check.

---

## 3. Tools to Install on Your Machine

Install these in order. Each command below assumes you are in a terminal.

| Tool | What it does | Needed from |
| :--- | :--- | :--- |
| **Git** | Version control. You have it if you cloned the repo. | Track 0 |
| **Docker Desktop** | Builds and runs containers on your machine | Track 0 |
| **curl** | Sends test requests to the API | Track 0 |
| **Python 3.10 or later** | Runs the test scripts and the tools in `tools/`, inside the project's own environment ([testing-guide.md](testing-guide.md) section 3) | Track 0 |
| **Azure CLI (`az`)** | Controls your Azure account from the terminal | Track 2 |
| **kubectl** | Controls a Kubernetes cluster | Track 3 |
| **Helm** | Installs packaged Kubernetes software (KEDA, Prometheus, GPU drivers) | Track 3 |

Installation on Windows, in PowerShell:

```powershell
winget install --id Git.Git -e
winget install --id Docker.DockerDesktop -e
winget install --id Python.Python.3.12 -e
winget install --id Microsoft.AzureCLI -e
winget install --id Kubernetes.kubectl -e
winget install --id Helm.Helm -e
```

Then close and reopen your terminal so the new commands are on your PATH, and
verify:

```powershell
git --version
docker --version
python --version
az version
kubectl version --client
helm version
```

If you plan to use Google Cloud instead of Azure, install the gcloud CLI
following [docs/gcp_gpu_prereqs.md](docs/gcp_gpu_prereqs.md) section 3 instead
of the Azure CLI.

---

## 4. A Windows-Specific Warning You Must Read

If you are on Windows, read this first. Every command in this repository's deployment guides is
written for a Unix shell. They use `export VAR="value"` for environment
variables and `$VAR` to read them back. PowerShell uses `$env:VAR = "value"`
instead, and it does not understand `export` at all.

If you paste the deployment guide commands into PowerShell, they will fail.

**The fix, and my recommendation: install WSL2 and work inside it.** WSL2 gives
you a real Ubuntu environment on Windows. Every command in
[docs/aks_deployment.md](docs/aks_deployment.md) then works exactly as written,
with no translation.

```powershell
wsl --install -d Ubuntu
```

Restart when prompted. Then open the Ubuntu terminal and install the tools again
inside it (the Windows copies do not carry over, except Docker Desktop, which
integrates with WSL2 automatically if you enable it in Docker Desktop settings
under Resources, then WSL Integration).

Inside Ubuntu:

```bash
sudo apt update && sudo apt install -y curl git
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
curl -LO "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

Your Windows files are visible inside WSL at `/mnt/c/`. For example, a copy of
this repository in the `Projects` folder on your Desktop is at:

```bash
cd /mnt/c/Users/<you>/Desktop/Projects/visual_document_understanding
```

For better performance you may prefer to clone a second copy inside the Linux
filesystem itself (under `~/`), because cross-filesystem access is slow.

There is one more Windows detail. This repository has a `.gitattributes` file
setting `* text=auto`, which converts line endings when you check files out.
Shell scripts such as `server/entrypoint.sh` must have Unix line endings or the
container will fail to start with a confusing `bad interpreter` error. Working
inside WSL avoids this entirely.

---

## 5. Track 0: Local Plumbing Test

**Goal:** prove the Rust API, Redis, and the queue mechanics work. No AI, no GPU,
no cloud account, no cost.

This is worth doing because it isolates roughly half the system. If the round
trip works here, any later failure is in the AI half, not the plumbing.

### The one-command version

This whole track is automated. From the repository root:

```bash
docker compose -f docker-compose.test.yml up --build -d
python tests/integration/smoke.py
docker compose -f docker-compose.test.yml down
```

`smoke.py` runs 84 checks and prints one line per check. If every line says
`ok`, Track 0 is done and you can skip to Track 1. The compose file starts Redis
(with a password and persistence, as in the cluster), the API, the reaper, the
MCP server, and a small webhook receiver, on unusual host ports (15000, 16379,
19100, 18080, 19000) so they never collide with anything else on your machine.
The script needs a few Python packages; [testing-guide.md](testing-guide.md)
section 3 sets them up, and its section 5 explains every line the script
prints. The manual steps below are still worth reading once, because they show
you what the automation is checking.

### 5.1 Start Redis

```bash
docker network create vdu-net
docker run -d --name vdu-redis --network vdu-net -p 6379:6379 redis:7-alpine
```

### 5.2 Build and run the Rust API

```bash
cd realtime_producer
docker build -t vdu-api:local .
docker run -d --name vdu-api --network vdu-net -p 5000:5000 \
  -e REDIS_HOST=vdu-redis \
  -e REDIS_PORT=6379 \
  vdu-api:local
```

The first build takes several minutes because it compiles Rust from source. Later
builds are fast because the Dockerfile uses `cargo-chef` to cache dependencies
separately from your code.

Check it started:

```bash
docker logs vdu-api
```

You should see a line saying the producer API is listening on `0.0.0.0:5000`.

### 5.3 Test the endpoints

```bash
# Health check. Should return HTTP 200 with an empty body.
curl -i http://localhost:5000/health

# Submit any PDF or image you have. Use your own file.
curl -X POST http://localhost:5000/process \
  -F "file=@/path/to/your/document.pdf"
```

You should get back something like:

```json
{"task_id":"3f8c1a2e-...","status":"queued"}
```

Copy that `task_id` and check its status:

```bash
curl http://localhost:5000/status/3f8c1a2e-...
```

Because no worker is running, the status stays `queued` forever. That is the
correct result for this track.

### 5.4 Confirm the data actually landed in Redis

This is the part that proves the plumbing:

```bash
docker exec vdu-redis redis-cli LRANGE ocr_tasks 0 -1          # should list your task_id
docker exec vdu-redis redis-cli HKEYS task:3f8c1a2e-...        # six fields: status, filename, extension, attempts, submitted_at, cache_key
docker exec vdu-redis redis-cli HGET task:3f8c1a2e-... status  # should print: queued
docker exec vdu-redis redis-cli STRLEN taskdata:3f8c1a2e-...   # the document's size in bytes
```

Everything after a `#` on a line is a note for you; the terminal ignores it.

**What you have proved:** file upload works, the 10 MB limit works, the atomic
write works, the queue push works, and the status endpoint reads back
correctly.

**A thing to observe while you are here.** Compare the number `STRLEN` printed
with your file's size: they are the same, because the document is stored as it
is, in a key of its own (`taskdata:<id>`). Storing it inside the task record as
base64 text would make it about a third bigger, and every status check would
drag it along. [testing-guide.md](testing-guide.md) section 6 walks through
every field.

### 5.5 Clean up

```bash
docker rm -f vdu-api vdu-redis
docker network rm vdu-net
```

---

## 6. Track 1: Local End to End Without a GPU

**Goal:** get real document understanding output, on your own machine, with no
GPU and no Kubernetes.

> **You do not need Azure or Google Cloud for this track.** No subscription, no
> subscription ID, no `az login`, no GPU quota. Those belong to Tracks 2 and 3
> and are covered in sections 7 and 8. The only credential Track 1 needs is one
> API key from the GLM-OCR cloud service, and this section tells you exactly
> where to get it.

This works because of a switch in `realtime_consumer/config.yaml`:

```yaml
pipeline:
  maas:
    enabled: false     # change to true
```

When this is `true`, the SDK stops doing local layout detection and local
inference, and forwards the whole document to a hosted cloud service instead.
That means no GPU is required at all. The comments in the config file describe
this as the mode for people who do not have a GPU or want the simplest setup.

### 6.1 Get your GLM-OCR API key, and put money on it

The model behind this pipeline is made by Zhipu AI, and they run **two separate
platforms** for it:

| Platform | Website | API address |
| :--- | :--- | :--- |
| **Z.ai**, the international one | https://z.ai/model-api | `https://api.z.ai/api/paas/v4/layout_parsing` |
| **BigModel**, the mainland China one | https://open.bigmodel.cn | `https://open.bigmodel.cn/api/paas/v4/layout_parsing` |

**Use Z.ai** unless you are in mainland China. But be aware of something the SDK
does not tell you: **its default address is BigModel, not Z.ai.** Section 6.2
shows the one line that points it at the right platform. Skip that line and your
Z.ai key gets sent to the China platform.

**Step 1: create the key.**

1. Go to **https://z.ai/model-api**.
2. Create an account or sign in.
3. Find the API keys section in your account dashboard and create a new key.
4. **Copy it immediately and save it somewhere safe.** These platforms typically
   show a key once and never again.

**Step 2: add credit to the account.** This is the step that is easy to miss. A
key on its own does nothing. A brand new account has a balance of zero, and every
request will be refused until you add money.

1. Go to **https://z.ai/manage-apikey/billing**.
2. Top up a small amount. For testing a handful of documents, the smallest amount
   the page allows is plenty.

**If your card is refused at top up:** Z.ai's own FAQ states that 3DS
verification is not currently supported. 3DS is the extra security step where
your bank sends you a code or asks you to approve the payment in its app. Many
cards require it, and those cards will fail here. If that happens, try a
different card. If none work, skip to section 7 and get real output from Track 2
instead.

**What it costs.** The GLM-OCR documentation lists pricing at **0.03 US dollars
per million tokens**, applied uniformly to input and output. For testing a
handful of documents this is a rounding error, well under a dollar. Check the
current pricing page yourself before running a large batch, since published
prices change. Also note that Z.ai's billing history shows yesterday's usage, not
today's, so do not panic if a test run does not appear straight away.

**Useful facts about this API**, verified from the Z.ai developer documentation,
in case you want to test the key directly before wiring it into the pipeline:

| Thing | Value |
| :--- | :--- |
| Model identifier | `glm-ocr` |
| Endpoint | `https://api.z.ai/api/paas/v4/layout_parsing` |
| Authentication header | `Authorization: Bearer your-api-key` |

### 6.2 Prepare the config

Copy the config so you do not edit the original:

```bash
cd realtime_consumer
cp config.yaml config.local.yaml
```

In `config.local.yaml`, edit the `maas` block. The repository's config file only
contains the `enabled` line, so **you have to add the other two lines
yourself**:

```yaml
pipeline:
  maas:
    enabled: true
    api_key: your-api-key-here
    api_url: https://api.z.ai/api/paas/v4/layout_parsing
```

**Why `api_url` matters.** Without it, the SDK sends your request to BigModel,
the mainland China platform, because that is its built-in default. If your key
came from Z.ai, you want the request to go to Z.ai. This field is real and
documented in the SDK's own configuration code, not a guess. If you are genuinely
using a BigModel key, leave this line out.

**The part that catches people out.** There is a second `api_key` field further
down the file, under `pipeline.ocr_api`. That one belongs to the self-hosted path
and is **ignored when MaaS mode is on**. The key must go under `pipeline.maas`.

You can tell straight away whether you got this right. If the SDK cannot find a
key, the worker refuses to start at all and prints a missing API key error. If
the worker starts and logs `GLM-OCR initialized in MaaS mode`, the key was found.

**Check which address it is actually using.** When the worker starts, one of the
first lines in its log is:

```
[DEBUG] glmocr.maas_client: MaaS client initialized for https://...
```

That address should be `api.z.ai`. If it says `open.bigmodel.cn`, your `api_url`
line is missing or in the wrong place.

Leave `logging.level` at `DEBUG`, which is already the default. The config
comment notes that DEBUG turns on timing output, and you want that on your first
run.

**Never commit this file.** `config.local.yaml` now contains a live credential.
The repository's `.gitignore` already lists it. Check that git agrees:

```bash
git check-ignore -v config.local.yaml
```

It prints the `.gitignore` line that ignores it:
`.gitignore:184:realtime_consumer/config.local.yaml	config.local.yaml`. If it
prints nothing, the file is not ignored: fix that before your next commit.

### 6.3 Build and run the worker

**The shorter way.** The test stack's compose file can start the
real worker for you, next to the API and Redis, reading this same
`config.local.yaml`:

```bash
docker compose -f ../docker-compose.test.yml up --build -d
docker compose -f ../docker-compose.test.yml --profile maas up -d --build worker
```

The API is then on port 15000 instead of 5000, so use `http://localhost:15000`
in the commands below. [testing-guide.md](testing-guide.md) section 14 walks
through it with real output. The manual steps that follow do the same thing by
hand, and are worth doing once.

The manual stack uses ports 5000 and 6379, so it does not clash with the test
stack. If the test stack is still running and you do not need it, stop it to
free memory:

```bash
docker compose -f ../docker-compose.test.yml down
```

Then build the worker:

```bash
docker build -t vdu-worker:local .
```

This image is large (it starts from an NVIDIA CUDA base) and will take a while
to build the first time.

Then run the whole stack together:

```bash
docker network create vdu-net
docker run -d --name vdu-redis --network vdu-net -p 6379:6379 redis:7-alpine

docker run -d --name vdu-api --network vdu-net -p 5000:5000 \
  -e REDIS_HOST=vdu-redis \
  vdu-api:local

docker run -d --name vdu-worker --network vdu-net \
  --shm-size=2g \
  -e REDIS_HOST=vdu-redis \
  -e GLMOCR_CONFIG_PATH=/app/config.yaml \
  -v "$(pwd)/config.local.yaml:/app/config.yaml:ro" \
  vdu-worker:local
```

The API key is not passed as an environment variable here, because in MaaS mode
it lives inside the config file you just mounted.

**If you change `config.local.yaml` later, restart the worker.** The worker reads
its config once, when it starts. Editing the file while it is running changes
nothing until you run:

```bash
docker restart vdu-worker
```

You do not need to rebuild the image. The config is mounted from your disk, not
baked into the image.

**Note the `--shm-size=2g`.** The worker writes documents into `/dev/shm`, and
Docker's default shared memory allocation is only 64 MB. Without this flag the
worker will fail on anything but tiny files. In Kubernetes this is handled by the
`dshm` volume in the deployment manifest, which requests 4 GB.

### 6.4 Run a document through

**The single most important character in this command is `@`.** In curl,
`file=@something.pdf` means "upload the file at this path". Without the `@`,
`file=something.pdf` means "send the words `something.pdf` as text". The API will
accept either one without complaint, and the second one sends no document at
all.

**The easy way:** copy a test document to a short path with no spaces, such as
`C:\test\sample.pdf`. This sidesteps every quoting problem below.

**In Git Bash**, use forward slashes and keep the quotes:

```bash
curl -s -X POST http://localhost:5000/process \
  -F "file=@C:/test/sample.pdf"
```

A path with spaces also works, as long as the whole thing stays inside the
quotes and on one line:

```bash
curl -s -X POST http://localhost:5000/process \
  -F "file=@C:/Users/<you>/Documents/Signed Contracts/Lease Agreement.pdf"
```

**In PowerShell**, type `curl.exe`, not `curl`. In Windows PowerShell, plain
`curl` is a shortcut for a different command called `Invoke-WebRequest`, which
does not understand `-X` or `-F` and fails with an error about a parameter it
cannot find. Typing `curl.exe` runs the real curl that ships with Windows:

```powershell
curl.exe -s -X POST http://localhost:5000/process -F "file=@C:\test\sample.pdf"
```

Either way you get back a `task_id`.

**Sending the same file twice?** The second time comes straight back as `done`
with `cached: true`, without the worker or Z.ai being involved, so it costs
nothing. To force a new reading, for example after changing the config, add
`-H "Cache-Control: no-cache"` to the curl command.

**If you forget the `@`, the API tells you.** A text value in the `file` field
is rejected with HTTP 400 and the message
`the 'file' field must be a file upload, not text (with curl, use file=@path)`.
Nothing is queued. Likewise a file that is not a PDF, PNG, or JPEG gets HTTP 415,
and an empty file gets 400. Only a real document ever reaches the queue.

You can still confirm what was stored:

```bash
docker exec vdu-redis redis-cli HGET task:<task_id> extension
```

That prints `pdf`, `png`, or `jpg`, decided from the file's content rather than
its name, which is what the worker needs to be right.

Then watch the worker process it:

```bash
docker logs -f vdu-worker
```

Press `Ctrl+C` to stop following the log. This stops the log view only, not the
worker.

### 6.5 Check whether it genuinely worked

**`done` means done.** The worker checks every result before recording it. A
refused cloud request, an empty result, or a missing result is
recorded as `failed` with the real reason in the `error` field, and the task
goes to the dead letter queue. A retryable failure is put back on the queue up to
`MAX_ATTEMPTS` times first, and `attempts` in the status response shows how many
tries it took. A document that came back with some regions missing is still
`done`, but carries a `warning` explaining how many regions were lost.

So the status response tells you the truth. Still worth looking at what came
back:

**1. Read the result:**

```bash
curl -s http://localhost:5000/status/<task_id> | python -m json.tool
```

Note there is nothing after `json.tool`. A stray character there, such as
`json.tool~`, makes Python look for a module that does not exist.

**2. Look at what came back:**

| What you see | What it means |
| :--- | :--- |
| `status: "done"` and `"markdown"` contains real text | **It worked.** |
| `status: "done"` with a `"warning"` | It worked, but some regions could not be transcribed. The text is there; parts may be missing. |
| `status: "failed"` with an `"error"` | It did not work, and the error says why. Section 12 explains the common ones. |
| `status: "failed"` with an `"error"` starting `document rejected:` | The file itself is the problem: corrupt, password protected, over 200 pages, or an enormous picture. It is not retried, because it would fail the same way again. |
| `status: "queued"` with `attempts` above 0 | A retryable failure happened and the task is waiting for another go. |

**3. Look for `[ERROR]` lines in the worker log.** Run this in Git Bash, since
`grep` does not exist in PowerShell:

```bash
docker logs vdu-worker 2>&1 | grep -i "error"
```

The `2>&1` is not optional. The worker writes its log lines to the error stream,
so without it `grep` sees almost nothing.

Any `[ERROR]` line mentioning your task's file means the output is not real,
whatever the status says. Section 12 explains the common ones.

**Things in the log that look alarming but are not problems:**

| Log line | Why it is fine |
| :--- | :--- |
| `WARNING: The NVIDIA Driver was not detected. GPU functionality will not be available.` | The worker image is built on an NVIDIA base image, which prints this banner whenever it starts on a machine without a GPU. In MaaS mode the cloud does all the work, so no local GPU is needed. |
| Two different timestamps on each line, a few hours apart | Docker Desktop adds your local time to the front of each line. The worker's own logger writes the container's clock, which is UTC because no time zone is set inside the container. Same moment, written two ways. |

### 6.6 What to actually look at

This is the most valuable half hour in the whole project. Take documents you
care about and study the output:

- Did the tables come back as real Markdown tables, or as mangled text?
- Did it get the reading order right on a multi-column page?
- Are headers and page numbers correctly absent from the output?
- What happened to charts? In Z.ai mode that is decided by Z.ai's service, not
  by this repository. On your own GPUs, a chart comes back as a written
  description starting "Chart:".
- Take a photo of a document at an angle with your phone and try that.

Whatever disappoints you here tells you which improvements matter for your
domain. That is more useful than any generic recommendation.

---

## 6b. Track 1b: Talk to It From an AI Assistant

Once Track 1 works, the same running stack can be driven by Claude Code or
Claude Desktop through the MCP server. This takes ten minutes and needs no
cloud account. [docs/mcp_setup.md](docs/mcp_setup.md) walks through it in full.
In short, from the repository folder in Git Bash:

```bash
python -m venv ~/.vdu-mcp
~/.vdu-mcp/Scripts/python -m pip install ./mcp_server
claude mcp add visual-document-understanding \
  -e VDU_API_URL=http://localhost:5000 \
  -e "VDU_ALLOWED_DIRS=C:\test" \
  -- "C:/Users/<you>/.vdu-mcp/Scripts/vdu-mcp.exe"
claude mcp list
```

The first two lines install the server once, into an environment of its own, so
it never disturbs any other Python program. The third registers it with Claude
Code: `localhost:5000` is the API from Track 1 (the testing guide's stack uses
port 15000 instead), and `C:\test` is the only folder it may read. Put your own
user name in the path. After pulling new code, update it with
`~/.vdu-mcp/Scripts/python -m pip install --upgrade ./mcp_server` and restart
Claude Code.

Then, in Claude Code: *"Read C:\test\sample.pdf and tell me what it says."*
You should see it call `read_document`, wait a moment, and answer from the text.
Try `/summarise_document` to see a prompt, and *"extract the fields from
C:\test\sample.pdf"* without saying what kind of document it is, to see the
server ask you.

[docs/mcp_setup.md](docs/mcp_setup.md) also covers Claude Desktop and connecting
to a deployed system. Section 12 below covers what to do if the assistant cannot
connect.

**If Track 1 is not working yet** (no Z.ai balance, no GPU), you can still see
everything the MCP server does. Route A of [testing-guide.md](testing-guide.md)
uses a demo worker in place of the real one, so every workflow is exercisable
with no API key, and it lists the exact things to ask Claude and what to expect
back.

---

## 7. Setting Up Azure, Step by Step

Everything from here on can cost money, so read section 11 on cost safety before
you start. Nothing in this section spends anything by itself, but it ends with
you holding the ability to spend.

If you would rather use Google Cloud, skip to section 8. You need one or the
other, not both.

### 7.1 The words Azure uses, in plain English

Azure's vocabulary is the main reason its interface feels overwhelming. There are
only six words you actually need.

| Word | What it means | Everyday comparison |
| :--- | :--- | :--- |
| **Directory** (also called a tenant) | The organisation your account belongs to. A personal signup creates one automatically, usually named something like `yourname.onmicrosoft.com`. | The company you work for. |
| **Subscription** | The billing container. Everything you create lives inside one, and everything it costs is charged to it. | Your bank account. |
| **Subscription ID** | A 32-character identifier for that subscription, written as five groups of letters and numbers separated by hyphens. | Your account number. |
| **Resource group** | A named folder holding related things, so you can delete them all at once. | A project folder on your desktop. |
| **Region** | The physical datacentre your machines run in, such as `eastus2` or `francecentral`. | Which warehouse your order ships from. |
| **Quota** | A cap on how much of a given resource you are allowed to run. New accounts have a GPU quota of zero. | A credit limit. |

**About that last one.** Azure does not measure GPU quota in GPUs. It measures it
in **vCPUs per VM family**. A VM family is a group of related machine sizes. So
you do not ask for "4 GPUs", you ask for the number of vCPUs that 4 of those
machines add up to. That is why the quota rows have names ending in
`Family vCPUs`.

For this project:

| What you want | The quota row to request | Amount | The arithmetic |
| :--- | :--- | :--- | :--- |
| 4 T4 GPUs | `Standard NCASv3_T4 Family vCPUs` | 64 | 4 machines of 16 vCPU each |
| 4 A100 GPUs | `Standard NCADS_A100_v4 Family vCPUs` | 96 | 4 machines of 24 vCPU each |

**One trap worth naming now.** Several Azure VM families have "A100" in the name.
You want the **NC** family, `NCADS_A100_v4`, which is built for inference. You do
**not** want the ND families such as `NDAMSv4_A100` or `NDASv4_A100`, which are
for large distributed training and cost considerably more. Requesting the wrong
one means waiting days for approval on quota you cannot use.

### 7.2 Create the account

1. Go to **https://azure.microsoft.com/free**.
2. Click **Start free**.
3. Sign in with a Microsoft account, or create one. Use an email address you will
   still control in a year, because this becomes your billing identity.
4. Fill in your profile and verify your phone number.
5. Add a credit or debit card. **This does not charge you.** Azure uses it only
   to confirm you are a real person. Prepaid and virtual cards are usually
   rejected, so use an ordinary card.
6. Accept the agreement and finish.

You now have roughly 200 US dollars of credit, valid for **30 days**, plus twelve
months of selected free services.

Three things to know immediately:

- **The 30-day clock starts now**, whether you use the credit or not. Do not
  create this account weeks before you are ready to build.
- **One free account per person.** The credit is tied to your identity and card.
- **This account cannot run GPUs yet.** That is section 7.5.

### 7.3 Find your subscription ID

This is the value the deployment guide wants when it says
`az account set --subscription "<YOUR_SUBSCRIPTION_ID>"`.

**Through the portal:**

1. Sign in at **https://portal.azure.com**.
2. Under the **Azure services** heading on the home page, select
   **Subscriptions**. If you do not see it there, type "Subscriptions" into the
   search box at the top of the page.
3. Your subscription is listed, usually named **Azure subscription 1**. The
   **Subscription ID** is shown in the second column.
4. To copy it cleanly, click the subscription name to open it, then use the copy
   icon next to **Subscription ID** in the **Essentials** section at the top.

It looks like this:

```
2f9a4c81-7b3e-4d15-9a62-c8e0f1a37b54
```

**If no subscription appears at all**, you are probably looking at the wrong
directory. Use **Switch directory** from the account menu in the top right and
pick the directory your account created.

**Through the CLI**, which is faster once you are logged in:

```bash
az login
az account list --output table
```

That prints a table with a `SubscriptionId` column. To get just the ID of the
currently active subscription:

```bash
az account show --query id --output tsv
```

### 7.4 Point the CLI at your subscription

This is what `az account set` does: it tells the Azure CLI which
billing container to create things in. If you only have one subscription, the CLI
already defaults to it and this command changes nothing. It matters once you have
more than one, and the deployment guide includes it so that people with several
subscriptions do not accidentally build in the wrong one.

```bash
az login
az account set --subscription "2f9a4c81-7b3e-4d15-9a62-c8e0f1a37b54"
az account show --output table
```

Substitute your own ID. The last command should show your subscription with
`IsDefault` set to `True`.

**On Windows:** if you are following the WSL2 advice from section 4, run these
inside Ubuntu. If you are in PowerShell instead, these three commands work
unchanged, because they contain no shell variables. It is the later deployment
commands, full of `export` and `$VAR`, that need WSL2.

Install `kubectl` through the CLI while you are here, which fetches the version
matching AKS:

```bash
az aks install-cli
```

### 7.5 Upgrade to Pay-As-You-Go

**This is the step that unlocks GPUs.** On a free trial your GPU quota is capped
at zero and the request button is disabled. No amount of asking helps until you
upgrade.

1. Sign in to **https://portal.azure.com**.
2. Search for **Subscriptions** and select the subscription created at signup.
3. On the subscription overview, select **Upgrade subscription** in the command
   bar along the top. If that button is not visible, click the upgrade banner
   across the top of the page instead.
4. Add a payment method if you are prompted for one.
5. You may need to verify your phone number again.
6. Give the subscription a name. Something like `visual-document-understanding` is
   more useful than the default.
7. Choose a support plan. **Basic is free** and is what you want unless you have
   a specific reason to pay for support.
8. Select **Upgrade**.

**What happens to your credit.** You keep any unused credit for the full 30 days
from when you originally signed up, not 30 days from the upgrade. If you signed
up on the 1st and upgrade on the 5th, the credit still expires on the 30th. You
also keep the twelve months of free services.

**What changes.** Usage beyond your credit now bills to your card. This is the
moment the account becomes capable of costing you money.

If the portal still behaves like a trial afterwards, sign out and back in to
force a refresh.

### 7.6 Register the Compute resource provider

Azure hides quota rows for services your subscription has never used. Before GPU
quota is even visible, `Microsoft.Compute` must be registered.

The CLI is the reliable way:

```bash
az provider register --namespace Microsoft.Compute
az provider show --namespace Microsoft.Compute --query registrationState --output tsv
```

Wait until that prints `Registered`, which takes a minute or two. Rerun the second
command to check.

The portal equivalent is Subscriptions, then your subscription, then
**Resource providers** in the left menu under Settings, then filter for
`Microsoft.Compute` and click **Register**.

### 7.7 Request the GPU quota

1. In the portal, type **quotas** into the search box at the top and select the
   **Quotas** service. This is a dedicated service in its own right, not a page
   buried inside your subscription.
2. In the left pane, select **My quotas**.
3. Use the filters along the top to narrow the list. Set the **Provider** to
   **Compute**, pick your **Subscription**, and set the **Region** to the one you
   intend to build in. Section 7.9 covers choosing a region, so if you have not
   decided yet, read that first and come back.
4. In the search box, type `NCASv3_T4`.
5. You should see **Standard NCASv3_T4 Family vCPUs** showing a limit of 0.
   Select its checkbox, then use the edit control to open the request dialog.
6. Enter a **New limit** of **64** and submit.
7. Clear the search, type `NCADS_A100_v4`, and repeat with a new limit of **96**.

**Submit these as two separate requests.** T4 quota is often granted within
hours. A100 quota commonly takes longer, sometimes a couple of days. Bundling
them means waiting for the slower one.

**Once approved, verify from the CLI** rather than trusting the portal display:

```bash
az vm list-usage --location eastus2 \
  --query "[?contains(localName,'A100') || contains(localName,'T4')].{Family:localName, Current:currentValue, Limit:limit}" \
  --output table
```

Substitute your region. You are looking for a `Limit` of 64 and 96 on the two
relevant rows.

### 7.8 If it says you cannot adjust the quota

GPU quota is rarely granted automatically. Being told to open a support ticket is
the normal path, not an error.

Click through to the support request and paste a short, specific justification.
Vague requests get rejected, concrete ones usually do not:

> Deploying an event-driven document understanding and vision-language inference
> pipeline on AKS. NVIDIA T4 (NC16as_T4_v3) nodes handle document layout
> detection and orchestration. NVIDIA A100 (NC24ads_A100_v4) nodes handle model
> inference. Both node pools use cluster autoscaling with scale-to-zero.
> Requesting 64 vCPU for NCASv3_T4 and 96 vCPU for NCADS_A100_v4 in East US 2.

Adjust the region to match your request. Keep it to a paragraph.

If you are told your subscription is not eligible for adjustment at all, you are
still on the trial. Go back to section 7.5.

### 7.9 Pick a region that actually has the hardware

Quota and capacity are two different things. Being approved for A100 quota in a
region does not mean that region has a free A100 for you today.

Check several regions at once before committing. Run this in a bash shell, which
means WSL2 on Windows:

```bash
for LOC in eastus2 francecentral swedencentral southcentralus japaneast southeastasia; do
  echo "=== $LOC ==="
  az vm list-skus --location $LOC --all \
    --resource-type virtualMachines \
    --query "[?name=='Standard_NC24ads_A100_v4' || name=='Standard_NC16as_T4_v3'].{Name:name, Restriction:restrictions[0].reasonCode}" \
    --output table
done
```

Pick the first region where **both** machine sizes come back with an empty
`Restriction` column. A value of `NotAvailableForSubscription` means that region
will not serve you that size.

An empty restriction means the size is offered to your subscription. It does not
read live inventory, so it is a strong signal rather than a guarantee. The real
proof is Track 2, which boots an actual machine.

**Pick one region and use it everywhere.** Quota is per region, so switching later
means requesting quota again from scratch.

### 7.10 Set a budget alert before you go further

Do this now, while it costs nothing, rather than after something has gone wrong.

1. In the portal, search for **Cost Management** and open it.
2. Select **Budgets** in the left menu, then **Add**.
3. Set a monthly amount you would genuinely be comfortable losing.
4. Add alert thresholds at 50 and 90 percent, with your email address.

A budget alert does not stop spending. It tells you it is happening. That is still
the difference between noticing on day one and noticing on the invoice.

### 7.11 Azure checklist

Before moving to Track 2, all of these should be true:

```
[ ] Account created and card verified
[ ] Subscription ID found and recorded
[ ] az login works, and az account show lists the right subscription
[ ] Upgraded to Pay-As-You-Go, confirmation seen
[ ] Microsoft.Compute shows Registered
[ ] Region chosen, both machine sizes show an empty restriction there
[ ] T4 quota of 64 vCPU approved
[ ] A100 quota of 96 vCPU approved
[ ] az vm list-usage confirms both limits
[ ] Budget alert set with your email on it
```

If a quota is still pending, you can go no further. That wait is normal. Use the
time to do Track 1 if you have not already.

---

## 8. Setting Up Google Cloud Instead

Only read this if you are choosing Google Cloud over Azure. The repository
supports both equally, with the same architecture on each.

**Which should you pick?** Azure if you want to follow the repository's primary
path, since its deployment guide is more detailed and includes the API gateway
setup. Google Cloud if you want simpler GPU handling, because GKE installs the
NVIDIA drivers for you where AKS makes you install an operator. The trial credit
is also more generous: 300 dollars over 90 days rather than 200 over 30.

### 8.1 The words Google Cloud uses

Fewer than Azure, with one important difference.

| Word | What it means | Azure equivalent |
| :--- | :--- | :--- |
| **Project** | The container for everything you build. Named by you. | Roughly a resource group. |
| **Project ID** | A globally unique text identifier for that project, chosen at creation and never changeable afterwards. | Part of what the subscription ID does. |
| **Billing account** | What pays for the projects linked to it. Separate from projects. | Subscription. |
| **Region** | A geographic area, such as `europe-west4`. | Region. |
| **Zone** | A specific datacentre within a region, such as `europe-west4-a`. | Availability zone. |

**The difference that matters:** on Google Cloud, **GPU availability varies by
zone, not just by region**. One zone in a region may have both T4 and A100 while
its neighbour has neither. You must check at zone level.

**The other difference:** GCP measures GPU quota in **GPU count**, not vCPUs. This
is much simpler than Azure. You ask for 4 T4 GPUs and 4 A100 GPUs, and that is
exactly what the quota rows are called.

### 8.2 Create the account and a project

1. Go to **https://cloud.google.com/free** and click **Get started for free**.
2. Sign in with a Google account or create one.
3. Fill in your country and accept the terms.
4. Add a credit or debit card for verification. You are not billed during the
   trial unless you manually upgrade.
5. Finish. You now have **300 US dollars of credit, valid for 90 days**.

Then create a project, because everything lives inside one:

1. Go to **https://console.cloud.google.com**.
2. Use the project dropdown in the top bar and choose **New Project**.
3. Name it something like `vdu-pipeline`.
4. Create it, then make sure it is the selected project in the top bar before
   doing anything else.

### 8.3 Find your project ID

The project **name** is what you typed. The project **ID** is what the CLI wants,
and they are often different, because IDs must be globally unique. Google usually
appends digits, so `vdu-pipeline` may become
`vdu-pipeline-481203`.

To find it, open the project dropdown in the top bar of the console. The ID is
shown beside each project name. It also appears on the project's dashboard page.

From the CLI:

```bash
gcloud projects list
```

### 8.4 Install and point the CLI

Download the installer for Windows from
**https://cloud.google.com/sdk/docs/install**, or inside WSL2 Ubuntu:

```bash
curl https://sdk.cloud.google.com | bash && exec -l $SHELL
```

Then add the Kubernetes pieces and log in:

```bash
gcloud components install kubectl gke-gcloud-auth-plugin
gcloud auth login
gcloud config set project YOUR-PROJECT-ID
gcloud config get-value project
```

The `gke-gcloud-auth-plugin` is not optional. Without it, `kubectl` cannot
authenticate to a GKE cluster and fails with a confusing credential error.

### 8.5 Upgrade to a paid account

Same trap as Azure: the free trial cannot run GPUs.

1. Go to the Google Cloud console welcome page.
2. Click **Upgrade** in the toolbar.
3. Confirm in the dialog.

If no Upgrade button appears, check that you are on a Free Trial billing account
and that you are a Billing Account Administrator on it.

**What happens.** You move to pay-as-you-go billing. You keep any unused credit
until it expires 90 days from when you first signed up, and you keep access to
the free tier. **This is irreversible.** You cannot return to trial status.

**A warning specific to Google Cloud.** Even after upgrading, a brand new account
with no spending history is sometimes still refused GPU quota as an anti-fraud
measure. If that happens to you, it is not a configuration mistake on your part.
Generate some ordinary CPU usage first and retry in a few days, or use the Sales
contact link shown in the quota dialog to have it unlocked manually.

### 8.6 Link billing and enable the APIs

Google Cloud disables most services by default. You must turn on the ones you
need.

```bash
gcloud billing accounts list

gcloud billing projects link YOUR-PROJECT-ID \
  --billing-account=XXXXXX-XXXXXX-XXXXXX

gcloud billing projects describe YOUR-PROJECT-ID
```

The last command should show `billingEnabled: true`.

Then enable the three services this project needs:

```bash
gcloud services enable \
  container.googleapis.com \
  compute.googleapis.com \
  artifactregistry.googleapis.com
```

Those are Kubernetes Engine, Compute Engine, and Artifact Registry, in that
order. If this fails with `UREQ_PROJECT_BILLING_NOT_FOUND`, billing is not
actually linked yet. Fix the step above first.

### 8.7 Request the GPU quota

1. In the console, open the navigation menu and go to **IAM and Admin**, then
   **Quotas and System Limits**.
2. Use the filter and the search box to find the metric you want. Search for
   `GPUs` and narrow by service and region.
3. Tick the checkbox next to the quota row you want.
4. Click **Edit** to open the quota changes dialog.
5. Enter your desired value in the **New value** field.
6. If your request exceeds what is offered directly, select
   **Apply for higher quota**.
7. Add a short **Request description**.
8. Click **Submit request**.

The two rows you need:

| Metric | Request |
| :--- | :--- |
| `NVIDIA T4 GPUs` | 4 |
| `NVIDIA A100 80GB GPUs` | 4 |

Note the 80GB in the second one. Plain `NVIDIA A100 GPUs` is the 40GB card, which
is not what the deployment expects.

Submit these as separate requests, same reasoning as Azure. A suggested
description:

> Deploying a document understanding and vision-language inference pipeline on
> GKE. The T4 node pool handles layout extraction with cluster autoscaling and
> scale-to-zero. Requesting 4 T4 GPUs in europe-west4.

You will get email confirmation that the request was received, and again when it
is decided.

### 8.8 Find a zone that has both GPUs

This is the zone-level check that has no Azure equivalent.

```bash
gcloud compute accelerator-types list \
  --filter="zone ~ europe-west4" \
  --format="table(name, zone)"
```

Change the region filter to whichever region you are considering. You are looking
for a single zone that lists **both** `nvidia-tesla-t4` and `nvidia-a100-80gb`.

In `europe-west4`, for example, the repository's own notes say only
`europe-west4-a` has both, while `-b` has the 40GB A100 only and `-c` has no A100
at all. Verify this yourself for your chosen region rather than assuming, because
availability changes.

Same caveat as Azure: a type appearing here means it exists in that zone, not that
one is free right now.

### 8.9 Set a budget alert

1. In the console, go to **Billing**, then **Budgets and alerts**.
2. Create a budget with a monthly amount and alert thresholds at 50 and 90
   percent.

### 8.10 Google Cloud checklist

```
[ ] Account created and card verified
[ ] Project created, project ID recorded
[ ] gcloud auth login works, correct project set
[ ] gke-gcloud-auth-plugin installed
[ ] Upgraded to a paid account
[ ] Billing linked, billingEnabled shows true
[ ] container, compute, and artifactregistry APIs enabled
[ ] Zone chosen where both T4 and A100 80GB are listed
[ ] T4 quota of 4 approved
[ ] A100 80GB quota of 4 approved
[ ] Budget alert set
```

---

## 9. Track 2: One Cloud GPU Machine

**Goal:** prove the models load and run on real hardware, without paying for a
four-node-pool Kubernetes cluster.

**Prerequisite: finish section 7 (Azure) or section 8 (Google Cloud) first.**
You need an upgraded account, approved GPU quota, and a chosen region before any
of this works. If your quota request is still pending, stop here and wait.

This track is a single smoke test: boot one GPU machine, confirm it starts, and
delete it. That proves the capacity is genuinely there, which no amount of quota
checking can tell you.

### 9.1 The Azure smoke test

Run this in a bash shell (WSL2 on Windows). Set `LOC` to the region you chose in
section 7.9.

```bash
LOC=eastus2
RG=gpu-smoketest-rg

az group create --name $RG --location $LOC

# Swap the size for Standard_NC16as_T4_v3 to test the T4 instead
az vm create \
  --resource-group $RG \
  --name gpu-smoketest \
  --location $LOC \
  --size Standard_NC24ads_A100_v4 \
  --image Ubuntu2204 \
  --admin-username azureuser \
  --generate-ssh-keys \
  --public-ip-sku Standard

az vm get-instance-view \
  --resource-group $RG --name gpu-smoketest \
  --query "instanceView.statuses[?starts_with(code,'PowerState')].displayStatus" \
  --output tsv
```

**Reading the result:**

| What you see | What it means |
| :--- | :--- |
| `VM running` | Capacity is real. Proceed to Track 3. |
| `AllocationFailed`, `SkuNotAvailable`, `ZonalAllocationFailed` | No free GPU in that region right now. Not your fault. Try a fallback region from your section 7.9 scan. |
| `QuotaExceeded`, and it fails instantly | Your quota is not approved yet. Different problem. Go back to section 7.7. |

A successful deploy takes two to five minutes. Capacity failures usually fail
within one or two.

### 9.2 Delete it immediately

**Do this the same day, ideally the same hour.** An A100 bills by the second, and
a forgotten smoke-test VM is the single most common way people following a
project like this get an unpleasant bill.

```bash
az group delete --name $RG --yes --no-wait
az group exists --name $RG        # should eventually print: false
```

Keep running `az group exists` until it prints `false`. The `--no-wait` flag
means the command returns before deletion finishes, so do not assume it is gone
just because the prompt came back.

### 9.3 The Google Cloud equivalent

If you are on GCP, the same test is a single node in a throwaway cluster. Use the
zone you identified in section 8.8.

```bash
ZONE=europe-west4-a
CLUSTER=gpu-smoketest

gcloud container clusters create $CLUSTER \
  --zone $ZONE --num-nodes=1 --machine-type=e2-standard-4 \
  --release-channel=regular

gcloud container node-pools create a100-test \
  --cluster=$CLUSTER --zone=$ZONE \
  --machine-type=a2-ultragpu-1g \
  --accelerator=type=nvidia-a100-80gb,count=1,gpu-driver-version=default \
  --num-nodes=1

gcloud container clusters get-credentials $CLUSTER --zone $ZONE
kubectl get nodes
```

If a node appears and becomes `Ready`, capacity is real. Then delete it:

```bash
gcloud container clusters delete $CLUSTER --zone $ZONE --quiet
```

Note that `gpu-driver-version=default` makes GKE install the NVIDIA drivers for
you. This is the step that AKS makes you do manually with the GPU Operator, and
it is the main reason the GKE path is shorter.

### 9.4 What this does not prove

The smoke test proves the hardware is obtainable. It does not prove the pipeline
works, because you have not deployed anything to it. That is Track 3. Do not skip
the smoke test on the grounds that Track 3 would catch the same failure, because
Track 3 takes a day and this takes ten minutes.

---

## 10. Track 3: The Full Kubernetes Deployment

**Goal:** the real system.

Follow [docs/aks_deployment.md](docs/aks_deployment.md) end to end, or
[docs/gke_deployment.md](docs/gke_deployment.md) on Google Cloud, which has the
same sections. They are long and they are complete. Do not improvise around
them.

Here is the shape of what the Azure guide does, so you know where you are while
working through it:

| Guide section | What happens | Roughly how long |
| :--- | :--- | :--- |
| 0 to 1 | Set the names you will use, sign in, create the resource group | 5 min |
| 2 | Create the container registry and the AKS cluster, with its network policy engine | 15 min |
| 3 | Add the four node pools | 15 min |
| 4 | Install the NVIDIA GPU Operator, check the GPUs are usable | 15 min |
| 5 | Create the shared storage, download the model weights into the cluster | 45 min, mostly downloading |
| 6 | Build the five container images in your registry (two are tiny) | 20 min |
| 7 to 8 | Name your registry once, create the secrets, turn on pod security | 10 min |
| 9 | Install KEDA and Prometheus, deploy the system | 15 min |
| 10 | Check that every part works | 30 min |
| 11 | Send documents, connect assistants | 15 min |
| 12 | Put Azure API Management in front of it | 45 min, plus 30 to 45 min while Azure creates API Management |

Then [testing-guide.md](testing-guide.md) section 22 tests the deployed system
from your computer: a first document, the MCP server, speed on the GPUs, and
watching it scale.

### Changes you must make before section 6

Set your own container registry in one place: the `images:` block of
`k8s/aks/kustomization.yml` (or `k8s/gke/kustomization.yml`), where every image
points at a placeholder such as `<YOUR_ACR_NAME>.azurecr.io`. Also set
`ACR_NAME` in section 0 of the deployment guide. If you skip this, every pod
fails with `ImagePullBackOff`.

Azure Container Registry names are globally unique across all of Azure, so pick
a name nobody else has.

### Things in the deployment guide worth knowing

**The guides match the manifests**, and the half that needs no GPU was
rehearsed on a local Kubernetes cluster; the outputs they show are from that
run.

**Create the cluster exactly as shown.** The cluster command includes network
settings (Azure CNI powered by Cilium on AKS, Dataplane V2 on GKE). They are
what make the network rules in `k8s/*/networking/` do anything. On GKE they
cannot be added to an existing cluster.

### The A100 autoscaler: not yet seen on real GPUs

The A100 pool starts from zero when documents are waiting (it watches the Redis
queues) and grows when vLLM has requests waiting (a Prometheus metric, collected
through the ServiceMonitors). The configuration for both has been checked, and
the metric collection was seen working on a local cluster for the API's own
metrics, but neither has been seen on real GPUs yet, so watch it the first time
with `kubectl describe scaledobject ocr-vlm-scaler`.

---

## 11. Cost Safety: Read Before Any GPU Boots

Do these three things before you create your first GPU node pool. Not after.

**1. Set a budget alert.** In the Azure portal, search for Cost Management, then
Budgets, then Add. Set a monthly amount you are genuinely willing to lose and an
alert at 50 percent. Google Cloud has the same feature under Billing, then
Budgets and alerts.

**2. Know the shutdown command.** The deployment guide's last section covers
scaling a node pool to zero:

```bash
az aks nodepool update \
  --resource-group $RESOURCE_GROUP \
  --cluster-name $AKS_NAME \
  --name gpunpa100 \
  --update-cluster-autoscaler \
  --min-count 0 \
  --max-count 4
```

Run it once for each GPU pool, `gpunpa100` and `gpunpt4`.

**3. Know the nuclear option.** If anything goes wrong and you want everything
gone:

```bash
az group delete --name $RESOURCE_GROUP --yes --no-wait
```

This deletes the entire resource group and everything in it. Irreversible.
Keep it handy anyway, because the ability to stop the bleeding quickly is worth
more than tidiness.

**A warning specific to this architecture.** The KEDA rules in this repository
are deliberately aggressive: the T4 pool scales up when the queue has a single
item, and the A100 pool is configured to scale when a single request is waiting.
Combined with an API that is reachable, that is an unbounded cost surface. The
API Management layer in section 12 of the deployment guide, with its limit of
100 calls a minute per subscription, is not optional polish. It is the brake.
Do not leave the system reachable without it.

---

## 12. Things That Will Break, and What To Do

### Track 1 problems

These are the ones you meet first, in roughly the order you meet them.

**The task says `failed`.** Read the `error` field in the status response; it
holds the real reason. Every entry below matches one of those messages.

**`document rejected: ...`** The worker opened the file before reading it and
could not use it: a corrupt or password-protected PDF, a PDF over 200 pages
(`MAX_PDF_PAGES`), or a picture that is truncated or enormous. It is not retried,
because the same file fails the same way every time. Fix the file and send it
again.

**The answer comes back at once and the worker log shows nothing.** That is the
result cache: the same file was read in the last day. Add
`-H "Cache-Control: no-cache"` to force a new reading.

**HTTP 400: `the 'file' field must be a file upload, not text`.** The curl
command was missing the `@` before the path, so it sent the path as text instead
of sending the file. See section 6.4.

**HTTP 415: `unsupported file type`.** The content is not a PDF, PNG, or JPEG,
whatever the filename says. The API checks the first bytes of the file.

**Error code `1113`, with the message `余额不足或无可用资源包,请充值。`** The
message is Chinese and means "insufficient balance or no available resource
package, please top up". Your account has no money on it. The HTTP status is
`429`, which normally means "slow down", but here it does not: this is a billing
refusal and retrying cannot fix it. That is why the log shows three attempts that
fail identically. Add credit at https://z.ai/manage-apikey/billing, as covered in
section 6.1.

This error also tells you something useful: **your key is valid.** A key the
platform does not recognise gets error `1000` with HTTP status `401` instead.

**The log says `MaaS client initialized for https://open.bigmodel.cn/...`** but
your key came from Z.ai. The SDK is using its built-in default address. Add the
`api_url` line from section 6.2, then run `docker restart vdu-worker`.

**Error code `1000`, `1001`, or `1003`, with HTTP status `401`.** Authentication
failed. `1000` is a general failure, most often a key pasted with a missing or
extra character. `1001` means no key reached the server. `1003` means the key has
expired and must be regenerated. Also check that the key and the `api_url` belong
to the same platform, since a Z.ai key sent to BigModel, or the reverse, may not
be accepted.

**The card is declined when topping up on Z.ai.** Z.ai's FAQ states 3DS
verification is not supported. Try a card that does not require it.

**`No module named json.tool~`**, or any module name with an unexpected character
on the end. A stray character was typed after `json.tool`. Delete it.

**`A parameter cannot be found that matches parameter name 'X'`** in PowerShell.
You typed `curl` instead of `curl.exe`. See section 6.4.

**You changed the config but nothing is different.** The worker only reads its
config at startup. Run `docker restart vdu-worker`.

**`MissingApiKeyError` and the worker exits immediately.** The key is not where
the SDK looks. It must be under `pipeline.maas.api_key`, not
`pipeline.ocr_api.api_key`. See section 6.2.

### Track 1b problems

**`claude mcp list` shows the server as failed, or the tools never appear.**
Run the server by hand in a terminal, by its full path, for example
`~/.vdu-mcp/Scripts/vdu-mcp`. It should print a line containing
`starting on stdio` and then wait silently for input (Ctrl+C to stop it). If it
prints an error instead, that is the cause. Common ones: a wrong path in the
registration (it must be the full path), a broken install (install it again, as
[docs/mcp_setup.md](docs/mcp_setup.md) section 2 shows), or the API not running
(check `curl http://localhost:5000/health`).

**The assistant says the path is outside the allowed directories.** The server
only reads files under `VDU_ALLOWED_DIRS`. Re-add the server with the folder
your documents are in.

**The assistant calls the tool but gets `the document was rejected`.** The
message that follows is the Rust API's own reason: not a PDF/PNG/JPEG, empty, or
too large. Same fixes as section 6.4.

**`the URL was refused: ...`** The server fetches only https
addresses that lead to public servers, and checks every redirect. An address
inside your own network, or plain http, is refused on purpose. Save the file
into your allowed folder and give the assistant the path instead.

**Something this guide describes is missing, such as the `cached` field or the
`fresh` option.** Claude is starting an older installed copy of the server.
Update it ([docs/mcp_setup.md](docs/mcp_setup.md) section 2), then restart
Claude Code.

### Track 3 problems

Ordered by how likely you are to hit them.

**`ImagePullBackOff` on every pod.** You did not set your container registry in
the kustomization's `images:` block. See section 10.

**Pods stuck in `Pending` forever.** Run
`kubectl describe pod <name>` and read the Events at the bottom. Almost always
one of: no node has a free GPU, the node pool has a taint your pod does not
tolerate, or the cluster autoscaler cannot get capacity in your region.

**The GPU check shows `<none>` for a GPU machine.** The NVIDIA GPU Operator did
not install correctly. The deployment guide's section 4 covers this: check
`kubectl get pods -n gpu-operator`, that the `gpu-operator` namespace has the
`pod-security.kubernetes.io/enforce=privileged` label, and the tolerations in
`k8s/aks/infra/gpu-operator-values.yaml`. Without that label the operator pods
are refused.

**The vLLM pod takes ten minutes to become ready.** This is normal, not broken.
It is pulling a multi-gigabyte image, loading weights, and compiling CUDA graphs.
The manifest sets a `startupProbe` with `failureThreshold: 60` and
`periodSeconds: 10`, which allows it up to ten minutes before Kubernetes gives
up. If it exceeds that, check the logs for an out-of-memory error.

**The worker fails on anything but tiny files locally.** You forgot
`--shm-size=2g` on `docker run`. See section 6.3.

**`bad interpreter` or `\r: command not found` in a container.** Windows line
endings got into `entrypoint.sh`. Work inside WSL2, or run
`dos2unix server/entrypoint.sh`.

**Tasks sit at `queued` and never move.** Either no worker is running, or the
worker crashed. Check `kubectl get pods` and `kubectl logs -l app=ocr-worker-rt`.
A task whose worker was killed mid-document shows `processing` until
`STALE_AFTER_SECONDS` (15 minutes) has passed; then the reaper puts it back in
the queue. Check the reaper with `kubectl logs -l app=ocr-reaper`.

**Redis restarted and everything vanished.** This should not happen: Redis
writes every change to its own disk. If it does, check that
`redis-data-pvc` shows `Bound` in `kubectl get pvc`, and that
`kubectl exec deploy/ocr-redis -- sh -c 'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning config get appendonly'`
answers `yes`.

**A pod stays in `CreateContainerConfigError`.** It needs a Secret that does not
exist yet, or that lacks the key it expects; `kubectl describe pod <name>` says
which. Create the secrets as shown in the deployment guide, section 8.

**A pod crashes with `Read-only file system` or `Permission denied`.** Every
container runs as an ordinary user with a read-only disk. The log
names the path it tried to write. Give it an `emptyDir` volume mounted at that
path, as the worker and vLLM deployments do for `/tmp`, rather than removing the
restriction.

**The network check prints `NOAUTH` instead of `blocked`.** The cluster has no
network policy engine, so the rules in `k8s/*/networking/network-policies.yml`
are accepted and ignored. Recreating the cluster with the settings in the
deployment guide is the reliable fix; on GKE it is the only one.

---

## 13. What To Record While Testing

Keep a plain text file as you go. You will want these numbers later, and once
the cluster is torn down you cannot recover them.

**From Track 1:**
- Time from submit to `done` for a one-page document, and for a twenty-page one.
- The Markdown output for three documents you care about, saved to disk. These
  become your first regression test fixtures.
- Every case where the output was wrong, with the input file. These become your
  evaluation set.
- The evaluation scores on your own documents (`tools/evaluate.py`,
  [testing-guide.md](testing-guide.md) section 13). They are the baseline every
  prompt or profile change is measured against.

**From Track 3:**
- Cold start time: from submitting the first request of the day to getting a
  result, with the pools scaled to zero.
- Warm throughput: `tools/throughput.py` sends 50 documents and reports pages
  per second and the time each one took ([docs/performance.md](docs/performance.md)
  shows the command). There is no earlier figure to compare against, so this is
  the system's first real number: write down the hardware with it, and add it
  to the table in `docs/performance.md`.
- Peak GPU memory on the A100, from
  `kubectl exec` into the vLLM pod and running `nvidia-smi`.
- What KEDA actually did, from `kubectl get hpa` and
  `kubectl describe scaledobject ocr-worker-rt-scaler`.
- Your actual spend for the day, from the portal.

Record these before making any changes. Every change you make should make
something measurably better, and without a baseline you are guessing.

---

## Where To Go After This

Once you have seen the system work:

- [testing-guide.md](testing-guide.md) tries every capability, one at a time,
  and shows what you should see back, including how to score the quality of
  the output on your own documents.
- [docs/aks_deployment.md](docs/aks_deployment.md) and
  [docs/gke_deployment.md](docs/gke_deployment.md) build the full system on
  Azure or Google Cloud, and check each part as they go.
- [docs/mcp_setup.md](docs/mcp_setup.md) connects Claude Code or Claude Desktop,
  either to the system on your own computer or to a deployed one.
- [docs/performance.md](docs/performance.md) is where your GPU numbers go.
  Nothing about reading speed on GPUs has been measured yet, so record yours
  there, with the hardware and the date.
- [system-explanation.md](system-explanation.md) explains how the whole system
  works. Its [known limits](system-explanation.md#11-known-limits) and
  [ideas for extending it](system-explanation.md#12-ideas-for-extending-it) are
  the place to start if you want to change it.

---

## Sources

External facts in section 1 were verified against:

- [glmocr on PyPI](https://pypi.org/project/glmocr/)
- [Qwen/Qwen3.5-4B on Hugging Face](https://huggingface.co/Qwen/Qwen3.5-4B)
- [PaddlePaddle/PP-DocLayoutV3_safetensors on Hugging Face](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3_safetensors)
- [vllm/vllm-openai on Docker Hub](https://hub.docker.com/r/vllm/vllm-openai/tags)
- [vLLM MTP documentation](https://docs.vllm.ai/en/latest/features/speculative_decoding/mtp/)
- [vLLM InstantTensor documentation](https://docs.vllm.ai/en/latest/models/extensions/instanttensor/)
- [vLLM engine arguments](https://docs.vllm.ai/en/stable/configuration/engine_args/)
- [GLM-OCR API documentation, Z.ai](https://docs.z.ai/guides/vlm/glm-ocr)

Portal navigation in sections 7 and 8 was verified against:

- [Get subscription and tenant IDs in the Azure portal](https://learn.microsoft.com/en-us/azure/azure-portal/get-subscription-tenant-id)
- [Upgrade your Azure account](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/upgrade-azure-subscription)
- [View quotas, Azure Quotas](https://learn.microsoft.com/en-us/azure/quotas/view-quotas)
- [View and manage quotas, Google Cloud](https://docs.cloud.google.com/docs/quotas/view-manage)
- [Google Cloud free trial FAQs](https://cloud.google.com/signup-faqs)
