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

**Two things worth knowing before you trust the README:**

**The Multi-Token Prediction claim is not configured.** The README credits MTP
with a 50 percent throughput increase and the 1.86 pages per second figure. I
searched the entire repository for `mtp`, `speculative`, `draft`, and `ngram`
and found zero matches. vLLM enables MTP through a
`--speculative-config '{"method": "mtp", ...}'` argument, and
`server/entrypoint.sh` has no such flag. Treat the performance numbers as
unverified marketing until you measure them on your own hardware.

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
| **Azure CLI (`az`)** | Controls your Azure account from the terminal | Track 2 |
| **kubectl** | Controls a Kubernetes cluster | Track 3 |
| **Helm** | Installs packaged Kubernetes software (KEDA, Prometheus, GPU drivers) | Track 3 |

Installation on Windows, in PowerShell:

```powershell
winget install --id Git.Git -e
winget install --id Docker.DockerDesktop -e
winget install --id Microsoft.AzureCLI -e
winget install --id Kubernetes.kubectl -e
winget install --id Helm.Helm -e
```

Then close and reopen your terminal so the new commands are on your PATH, and
verify:

```powershell
git --version
docker --version
az version
kubectl version --client
helm version
```

If you plan to use Google Cloud instead of Azure, install the gcloud CLI
following [docs/gcp_gpu_prereqs.md](docs/gcp_gpu_prereqs.md) section 3 instead
of the Azure CLI.

---

## 4. A Windows-Specific Warning You Must Read

You are on Windows 11. Every command in this repository's deployment guides is
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

Your Windows files are visible inside WSL at `/mnt/c/`, so this repository is at:

```bash
cd /mnt/c/Users/mukjo/Desktop/Projects/visual_understanding_system
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

Since Phase 1, this whole track is automated. From the repository root:

```bash
docker compose -f docker-compose.test.yml up --build -d
python tests/integration/smoke.py
docker compose -f docker-compose.test.yml down
```

`smoke.py` runs 21 checks and prints one line per check. If every line says
`ok`, Track 0 is done and you can skip to Track 1. The manual steps below are
still worth reading once, because they show you what the automation is checking.

### 5.1 Start Redis

```bash
docker network create vus-net
docker run -d --name vus-redis --network vus-net -p 6379:6379 redis:7-alpine
```

### 5.2 Build and run the Rust API

```bash
cd realtime_producer
docker build -t vus-api:local .
docker run -d --name vus-api --network vus-net -p 5000:5000 \
  -e REDIS_HOST=vus-redis \
  -e REDIS_PORT=6379 \
  vus-api:local
```

The first build takes several minutes because it compiles Rust from source. Later
builds are fast because the Dockerfile uses `cargo-chef` to cache dependencies
separately from your code.

Check it started:

```bash
docker logs vus-api
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
docker exec -it vus-redis redis-cli

# Inside the Redis prompt:
LRANGE ocr_tasks 0 -1          # should list your task_id
HKEYS task:3f8c1a2e-...        # should show: status, filename, extension, data
HGET task:3f8c1a2e-... status  # should print: queued
STRLEN task:3f8c1a2e-... 
exit
```

**What you have proved:** file upload works, the 10 MB limit works, the atomic
`HSET` write works, the queue push works, and the status endpoint reads back
correctly.

**A thing to observe while you are here.** Run `HGET task:<id> data` and look at
how long that base64 string is, then compare it to your original file size. It
will be about 33 percent larger. That is gap 10 from the system explanation, and
seeing it yourself makes the fix worth doing later.

### 5.5 Clean up

```bash
docker rm -f vus-api vus-redis
docker network rm vus-net
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
Add it to `.gitignore` before your next commit:

```bash
echo "config.local.yaml" >> ../.gitignore
```

### 6.3 Build and run the worker

If the smoke test's containers are still running from Track 0, stop them first,
because they hold the same ports:

```bash
docker compose -f ../docker-compose.test.yml down
```

Then build the worker:

```bash
docker build -t vus-worker:local .
```

This image is large (it starts from an NVIDIA CUDA base) and will take a while
to build the first time.

Then run the whole stack together:

```bash
docker network create vus-net
docker run -d --name vus-redis --network vus-net -p 6379:6379 redis:7-alpine

docker run -d --name vus-api --network vus-net -p 5000:5000 \
  -e REDIS_HOST=vus-redis \
  vus-api:local

docker run -d --name vus-worker --network vus-net \
  --shm-size=2g \
  -e REDIS_HOST=vus-redis \
  -e GLMOCR_CONFIG_PATH=/app/config.yaml \
  -v "$(pwd)/config.local.yaml:/app/config.yaml:ro" \
  vus-worker:local
```

The API key is not passed as an environment variable here, because in MaaS mode
it lives inside the config file you just mounted.

**If you change `config.local.yaml` later, restart the worker.** The worker reads
its config once, when it starts. Editing the file while it is running changes
nothing until you run:

```bash
docker restart vus-worker
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
  -F "file=@C:/Users/mukjo/Desktop/Business/Change of Directors/Board Resolution.pdf"
```

**In PowerShell**, type `curl.exe`, not `curl`. In Windows PowerShell, plain
`curl` is a shortcut for a different command called `Invoke-WebRequest`, which
does not understand `-X` or `-F` and fails with an error about a parameter it
cannot find. Typing `curl.exe` runs the real curl that ships with Windows:

```powershell
curl.exe -s -X POST http://localhost:5000/process -F "file=@C:\test\sample.pdf"
```

Either way you get back a `task_id`.

**Confirm the file really arrived, before you wait on anything else.** This takes
five seconds and catches the missing `@` immediately:

```bash
docker exec vus-redis redis-cli HGET task:<task_id> filename
```

| What it prints | What it means |
| :--- | :--- |
| Your real filename, such as `sample.pdf` | The file was uploaded. Carry on. |
| `unknown.pdf` | **No file was uploaded.** The API only uses that name when the request had no file attached. Check for the missing `@` and submit again. |

Then watch the worker process it:

```bash
docker logs -f vus-worker
```

Press `Ctrl+C` to stop following the log. This stops the log view only, not the
worker.

### 6.5 Check whether it genuinely worked

**Warning: `status: "done"` does not mean it worked.** This is a real bug in the
current worker, found by exactly this test. When the cloud API refuses a request,
the SDK records the failure quietly instead of raising an error, and the worker
does not check for it. The task gets marked `done` with empty output and no error
message. It is logged as gap 20 in the implementation plan and fixed in Phase 2.

Until then, check three things yourself.

**1. Read the result:**

```bash
curl -s http://localhost:5000/status/<task_id> | python -m json.tool
```

Note there is nothing after `json.tool`. A stray character there, such as
`json.tool~`, makes Python look for a module that does not exist.

**2. Look at what came back:**

| What you see | What it means |
| :--- | :--- |
| `"markdown"` contains real text from your document | **It worked.** |
| `"markdown": ""` and `"layout": []` | **It failed**, despite saying `done`. Go to step 3. |

**3. Look for `[ERROR]` lines in the worker log.** Run this in Git Bash, since
`grep` does not exist in PowerShell:

```bash
docker logs vus-worker 2>&1 | grep -i "error"
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

### 6.5 What to actually look at

This is the most valuable half hour in the whole project. Take documents you
care about and study the output:

- Did the tables come back as real Markdown tables, or as mangled text?
- Did it get the reading order right on a multi-column page?
- Are headers and page numbers correctly absent from the output?
- What happened to charts? They are currently in the `skip` bucket in the
  config, so they will be detected and then not described. Notice the gap where
  a chart should be.
- Take a photo of a document at an angle with your phone and try that.

Whatever disappoints you here tells you which improvements matter for your
domain. That is more useful than any generic recommendation.

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

Now the command that confused you makes sense. It tells the Azure CLI which
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
6. Give the subscription a name. Something like `visual-understanding-system` is
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
3. Name it something like `visual-understanding-system`.
4. Create it, then make sure it is the selected project in the top bar before
   doing anything else.

### 8.3 Find your project ID

The project **name** is what you typed. The project **ID** is what the CLI wants,
and they are often different, because IDs must be globally unique. Google usually
appends digits, so `visual-understanding-system` may become
`visual-understanding-system-481203`.

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

Follow [docs/aks_deployment.md](docs/aks_deployment.md) end to end. It is 576
lines and it is genuinely complete. Do not improvise around it.

Here is the shape of what it does, so you know where you are while working
through it:

| Stage | What happens | Roughly how long |
| :--- | :--- | :--- |
| 0 | Set environment variables, log in to Azure | 5 min |
| 1 | Create container registry and AKS cluster, add four node pools | 30 min |
| 1b | Install the NVIDIA GPU Operator via Helm, verify GPUs are schedulable | 15 min |
| 2 | Create the shared storage claim, run the model ingest job | 45 min, mostly downloading |
| 3 | Build and push three container images | 20 min |
| 4 | Install KEDA and Prometheus, deploy the stack | 15 min |
| 5 | Test end to end, check logs and metrics | 30 min |
| 6 | Set up Azure API Management in front of it | 45 min, and APIM itself takes 30 to 45 min to provision |

### Changes you must make before Stage 3

The manifests contain the original author's container registry hardcoded. If you
do not change these, your deployment will try to pull images from a registry you
do not own and every pod will fail with `ImagePullBackOff`.

| File | Line | Change |
| :--- | :--- | :--- |
| `docs/aks_deployment.md` | 19 | `ACR_NAME` to your own registry name |
| `k8s/aks/apps/deployment-api.yml` | 26 | Registry host on the API image |
| `k8s/aks/apps/deployment-api.yml` | 74 | Registry host on the worker image |
| `k8s/aks/apps/deployment-vlm.yml` | 26 | Registry host on the vLLM image |

Azure Container Registry names are globally unique across all of Azure, so the
name in the repository is permanently taken by someone else. Pick your own.

Also change the label `managed-by: gemini-cli-agent` in
`k8s/aks/kustomization.yml` line 15 **before your first deploy**. That block has
`includeSelectors: true`, which bakes the label into every Deployment's pod
selector, and selectors cannot be changed on a running Deployment. Changing it
later means deleting and recreating everything. Changing it now costs nothing.

### Two things in the deployment guide that will confuse you

**The example output in section 2.4 is wrong.** It shows a model called
`Qwen3-VL-Embedding-2B` in the weights directory. The ingest job at
`k8s/aks/infra/provisioning/ingest-job.yaml` line 23 only downloads
`PaddlePaddle/PP-DocLayoutV3_safetensors` and `Qwen/Qwen3.5-4B`. The example is
left over from an earlier version. Your directory listing will not match, and
that is fine.

**There is a typo at line 54**, "Downlaod AKS credentials". Harmless, but it
tells you the guide was not proofread, so read it critically rather than pasting
blindly.

### Do not expect the A100 autoscaler to work

I need to flag this before you spend a day debugging it. The KEDA rule that
scales the A100 pool queries a Prometheus metric called
`vllm:num_requests_waiting`. For that metric to exist in Prometheus, something
must tell Prometheus to scrape the vLLM pod. I searched the repository for a
`ServiceMonitor`, a `PodMonitor`, and `prometheus.io/scrape` annotations and
found none.

So the A100 scale-up trigger will find no data and will not fire. The cron
warm-start trigger on the same rule will still work, so you will get one replica
during business hours, but it will not scale beyond that under load.

This is a genuine missing piece, not a mistake on your part. It is logged as a
gap in the implementation plan and gets fixed in Phase 3. Knowing it now saves
you the debugging session.

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

Note that the guide's own example uses a pool named `gpunp`, which does not
match the pools it created earlier in the same document (`gpunpa100` and
`gpunpt4`). Use the correct pool name, shown above.

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
API Management layer in Stage 6 with its 100 calls per minute limit is not
optional polish. It is the brake. Do not leave the system reachable without it.

---

## 12. Things That Will Break, and What To Do

### Track 1 problems

These are the ones you meet first, in roughly the order you meet them.

**The task says `done` but the markdown is empty.** The work failed and the
worker reported success anyway. This is gap 20, a real bug. Look at the worker
log for the actual reason, using the `grep` command in section 6.5. Every entry
below starts from there.

**The filename in Redis is `unknown.pdf`.** Your document was never uploaded. The
curl command was missing the `@` before the path, so it sent the path as text
instead of sending the file. See section 6.4.

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
`api_url` line from section 6.2, then run `docker restart vus-worker`.

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
config at startup. Run `docker restart vus-worker`.

**`MissingApiKeyError` and the worker exits immediately.** The key is not where
the SDK looks. It must be under `pipeline.maas.api_key`, not
`pipeline.ocr_api.api_key`. See section 6.2.

### Track 3 problems

Ordered by how likely you are to hit them.

**`ImagePullBackOff` on every pod.** You did not change the container registry
host in the manifests. See the table in section 10.

**Pods stuck in `Pending` forever.** Run
`kubectl describe pod <name>` and read the Events at the bottom. Almost always
one of: no node has a free GPU, the node pool has a taint your pod does not
tolerate, or the cluster autoscaler cannot get capacity in your region.

**`GPU_ALLOCATABLE` shows 0 or none.** The NVIDIA GPU Operator did not install
correctly. The deployment guide's own troubleshooting note covers this: check
that the `gpu-operator` namespace has the `pod-security.kubernetes.io/enforce=privileged`
label, and check the tolerations in `k8s/aks/infra/gpu-operator-values.yaml`.
Without that label the operator pods are silently blocked from starting.

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
Note that if a worker pod is killed while holding tasks, those tasks are lost
permanently and will sit at `processing` forever. That is gap 8 and it is fixed
in Phase 2 of the implementation plan.

**Redis restarted and everything vanished.** Expected with the current setup.
Redis runs with no persistence, one replica, and no password. Also gap 6, also
Phase 2.

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

**From Track 3:**
- Cold start time: from submitting the first request of the day to getting a
  result, with the pools scaled to zero.
- Warm throughput: submit 50 documents at once and time the whole batch. Divide
  to get pages per second. Compare against the README's claim of 1.86.
- Peak GPU memory on the A100, from
  `kubectl exec` into the vLLM pod and running `nvidia-smi`.
- What KEDA actually did, from `kubectl get hpa` and
  `kubectl describe scaledobject ocr-worker-rt-scaler`.
- Your actual spend for the day, from the portal.

Record these before making any changes. Every improvement in the implementation
plan is supposed to make something measurably better, and without a baseline you
are guessing.

---

## Where To Go After This

Once you have seen the system work, move to
[implementation-plan.md](implementation-plan.md). It contains the verified gap
register, the target architecture including the MCP server, and the phased plan
for getting from here to there.

Do not start Phase 0 until you have at least completed Track 1. Changing a system
you have never seen run means you cannot tell whether your change helped or
broke something.

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
