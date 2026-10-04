# Testing Guide: Try Everything, in Every Setup

This guide is for trying the system by hand and understanding what comes back,
whichever way you run it: with no API balance and no GPU, with a Z.ai balance,
or on your own GPU cluster. Section 1 gives you a route for each.

Every command here was run on this machine between 29 September and 1 October
2026, and every output shown is real, copied from those runs. Where an output is
shortened, the guide says so. The cluster outputs in section 22 come from a
rehearsal on a local test cluster that has no GPUs; wherever a GPU changes the
answer, the guide says what you should see instead.

Every command is explained in plain words: what each part means, and what the
answer is telling you. If you already know a tool, skip its explanation.

All commands are for **Git Bash**, the terminal that comes with Git for
Windows, started in the repository folder. Where PowerShell is different, the
guide says so.

## Table of Contents

1. [Choose your scenario](#1-choose-your-scenario)
2. [The system in one minute, and the words used below](#2-the-system-in-one-minute-and-the-words-used-below)
3. [Set up once](#3-set-up-once)
4. [Start the system](#4-start-the-system)
5. [Test A: the whole system checked in one command](#5-test-a-the-whole-system-checked-in-one-command)
6. [Test B: one document by hand](#6-test-b-one-document-by-hand)
7. [Test C: the result cache](#7-test-c-the-result-cache)
8. [Test D: a worker dies, the document survives](#8-test-d-a-worker-dies-the-document-survives)
9. [Test E: bad documents, at the door and inside](#9-test-e-bad-documents-at-the-door-and-inside)
10. [Test F: webhooks, the system calls you back](#10-test-f-webhooks-the-system-calls-you-back)
11. [Test G: every MCP capability, in one script](#11-test-g-every-mcp-capability-in-one-script)
12. [Test H: measuring speed](#12-test-h-measuring-speed)
13. [Test I: measuring quality](#13-test-i-measuring-quality)
14. [Test J: the real worker, with Z.ai](#14-test-j-the-real-worker-with-zai)
15. [Test K: the security you can see](#15-test-k-the-security-you-can-see)
16. [Connecting the MCP server to Claude Code](#16-connecting-the-mcp-server-to-claude-code)
17. [What to ask Claude, and what you should see](#17-what-to-ask-claude-and-what-you-should-see)
18. [Connecting Claude Desktop instead](#18-connecting-claude-desktop-instead)
19. [The automated test suites](#19-the-automated-test-suites)
20. [When something does not work](#20-when-something-does-not-work)
21. [Cleaning up](#21-cleaning-up)
22. [Scenario C: testing on your GPU cluster](#22-scenario-c-testing-on-your-gpu-cluster)

---

## 1. Choose your scenario

The system works the same way in every setup. The only part that changes is the
**worker**, the part that actually reads the document. Everything around it (the
API, the queue, the recovery, the cache, the callbacks, the MCP server, the
security checks) is the same code in every case.

| | Scenario A: no balance, no GPU | Scenario B: Z.ai balance, no GPU | Scenario C: your GPU cluster |
| :--- | :--- | :--- | :--- |
| **What reads the documents** | The demo worker (`tools/demo_worker.py`): checks the file opens, waits 6 seconds, returns a made-up invoice | The real worker, in Z.ai mode: sends each document to Z.ai's service, which reads it | The real worker and vLLM on your GPUs: layout on the T4, reading on the A100 |
| **Where it runs** | Your computer | Your computer | Azure or Google Cloud |
| **What it costs** | Nothing | Each page read costs a little Z.ai credit | GPU machines by the hour while they run |
| **What you learn** | Every mechanism works | Real readings of your documents | Real readings, real speed, scaling, the network rules |
| **Profiles and prompts apply** | No (canned answer) | No (Z.ai uses its own) | Yes |
| **Needs** | Docker Desktop, Python | The same, plus a Z.ai key with balance in `realtime_consumer/config.local.yaml` | The cluster, deployed with `docs/aks_deployment.md` or `docs/gke_deployment.md` |

Scenario C does **not** need a Z.ai balance: the cluster reads documents with its
own models and never calls Z.ai. And only ever run **one** worker at a time
against the same queue; two would both take documents, and you could not tell
which one answered.

**Route A, no balance and no GPU.** Start here even if you have more; it costs
nothing and shows every mechanism.

1. [Section 2](#2-the-system-in-one-minute-and-the-words-used-below): the words used below.
2. [Section 3](#3-set-up-once) and [section 4](#4-start-the-system): set up once, start the system and the demo worker.
3. [Section 5](#5-test-a-the-whole-system-checked-in-one-command): the whole system checked in one command (stop the demo worker first).
4. Sections [6](#6-test-b-one-document-by-hand) to [11](#11-test-g-every-mcp-capability-in-one-script): one document by hand, the cache, a dying worker, bad documents, callbacks, and every MCP capability.
5. [Section 12](#12-test-h-measuring-speed): the front door's speed (stop the demo worker first).
6. [Section 15](#15-test-k-the-security-you-can-see): the security you can see.
7. Sections [16](#16-connecting-the-mcp-server-to-claude-code) to [18](#18-connecting-claude-desktop-instead): Claude Code and Claude Desktop.
8. [Section 21](#21-cleaning-up): cleaning up.

The words that come back are always the same made-up invoice. That is the demo
worker, not the pipeline.

**Route B, with a Z.ai balance.** Do route A first: it costs nothing and checks
everything around the worker. Then swap the demo worker for the real one, so the
readings are real.

1. Stop the demo worker (Ctrl+C in its terminal), then start from a clean slate,
   as the start of [section 14](#14-test-j-the-real-worker-with-zai) shows.
   This matters: the cache remembers every answer for a day, including the
   demo worker's made-up invoice, so without it a document you already sent in
   route A comes straight back, marked `cached`, with the fake answer. It also
   empties the queue, which the real worker would otherwise read, and charge you
   for.
2. [Section 14](#14-test-j-the-real-worker-with-zai): start the real worker, and read its warnings about cost and blank pages first.
3. Sections [6](#6-test-b-one-document-by-hand), [7](#7-test-c-the-result-cache), [9](#9-test-e-bad-documents-at-the-door-and-inside), [10](#10-test-f-webhooks-the-system-calls-you-back), and [11](#11-test-g-every-mcp-capability-in-one-script) again: the same steps, now with real readings. Section 8 has nothing new to show here: the recovery it tests belongs to the queue and the reaper, which are the same whatever the worker, and its `--delay`, `--fail` and `--warn` options exist only in the demo worker.
4. [Section 13](#13-test-i-measuring-quality): quality scores on real readings. Add your own documents.
5. [Section 12](#12-test-h-measuring-speed): `throughput.py` now measures Z.ai's speed, which says nothing about your own GPUs.
6. Sections [16](#16-connecting-the-mcp-server-to-claude-code) to [18](#18-connecting-claude-desktop-instead): ask Claude about your real documents.
7. [Section 21](#21-cleaning-up): cleaning up, including stopping the real worker.

**Route C, on your GPU cluster.** Deploy first, then test from your computer.

1. Deploy with [docs/aks_deployment.md](docs/aks_deployment.md) (Azure) or
   [docs/gke_deployment.md](docs/gke_deployment.md) (Google Cloud), up to and
   including its section 10, "Check that everything works".
2. [Section 3](#3-set-up-once) here: the tools' environment on your computer.
3. [Section 22](#22-scenario-c-testing-on-your-gpu-cluster): connect your
   computer to the cluster, then run the tests that apply there, measure speed
   and quality on the GPUs, and watch it scale.
4. [docs/mcp_setup.md](docs/mcp_setup.md) section 5: connect Claude to the cluster.

The one-command check (section 5), the real-worker section (14), and the
container security checks (15) are for your computer only; section 22 gives
the cluster's equivalents.

---

## 2. The system in one minute, and the words used below

Think of the system as a post office that reads letters for you.

- The **API** is the front counter. You hand over a document; it checks it is a
  real PDF or picture and not too big, gives you a ticket number (the
  **task_id**), and puts it on a shelf. It never reads the document itself.
- **Redis** is the wall of shelves. One shelf holds documents waiting
  (`ocr_tasks`), one holds documents being read right now
  (`ocr_tasks:processing`), and one holds documents that could not be read
  (`ocr_tasks:dead`, the "dead letter" shelf).
- The **worker** is the reader. It takes the oldest waiting document, reads it,
  and writes the answer back.
- The **reaper** is the night watchman. If a reader collapses halfway through a
  document, the watchman notices and puts it back on the waiting shelf. It also
  makes the phone calls for webhooks.
- The **cache** is a memory: "we read this exact document an hour ago, here is
  the copy".
- A **webhook** is the post office phoning you when your document is done, so
  you do not have to keep coming back to ask.
- The **MCP server** is a separate counter just for AI assistants like Claude.

The tools you will type:

| Word | What it is |
| :--- | :--- |
| `curl` | A program that sends a web request from the terminal, like a browser with no window. |
| `docker compose` | Starts several containers together, as described in a recipe file. A **container** is a sealed box holding one program and everything it needs. |
| `docker exec` | Runs one command inside a container that is already running. |
| `redis-cli` | The program for talking to Redis directly, to look at the shelves. |
| `python` | Runs a Python script. In this guide, always the one inside the project's virtual environment. |
| JSON | The text format the answers come back in: `{"name": "value"}`. |

The numbers the API answers with (**HTTP status codes**):

| Code | Plain meaning |
| :--- | :--- |
| 200 | OK, here is your answer. |
| 202 | Accepted, it is queued, come back later. |
| 400 | Your request was wrong; the message says how. |
| 401 | You did not show a valid key or token. |
| 404 | There is no such thing (for example, an unknown task_id). |
| 413 | Too big. |
| 415 | Not a file type we read. |

---

## 3. Set up once

**Docker Desktop must be running** (the whale icon in the taskbar is steady, not
animating).

**A private Python environment for the tools.** A virtual environment is a
folder holding its own copy of Python packages, so what this project installs
cannot break your other projects.

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r tools/requirements.txt
```

| Line | What it does |
| :--- | :--- |
| `python -m venv .venv` | Creates the environment in a folder called `.venv`. If it already exists, nothing is lost. |
| `source .venv/Scripts/activate` | Switches this terminal to use it. Your prompt starts with `(.venv)`. In PowerShell the line is `.venv\Scripts\Activate.ps1`. |
| `pip install -r tools/requirements.txt` | Installs what the tools need: `httpx` and `redis` to talk to the API and Redis, `mcp` to talk to the MCP server, and `pypdfium2` and `pillow`, which the demo worker uses to check that a document can really be opened. |

Do the `activate` line again in every new terminal. The `.venv` folder is
ignored by git, so it is never committed.

---

## 4. Start the system

**Terminal 1**, from the repository folder:

```bash
docker compose -f docker-compose.test.yml up --build -d
```

| Part | Meaning |
| :--- | :--- |
| `docker compose` | Start several containers together. |
| `-f docker-compose.test.yml` | Use this recipe file. It describes five containers: Redis, the API, the reaper, the MCP server, and a small webhook receiver that plays the part of a client's app. |
| `up` | Start them. |
| `--build` | First rebuild each container from the current code, so you test what is in the folder now. |
| `-d` | "Detached": run them in the background and give the terminal back. |

The first build takes a few minutes. Then check all three doors answer:

```bash
curl -s -o /dev/null -w "api       %{http_code}\n" http://127.0.0.1:15000/health
curl -s -o /dev/null -w "mcp       %{http_code}\n" http://127.0.0.1:18080/health
curl -s -o /dev/null -w "receiver  %{http_code}\n" http://127.0.0.1:19000/health
```

| Part | Meaning |
| :--- | :--- |
| `-s` | Silent: no progress bar. |
| `-o /dev/null` | Throw the page itself away; we only want the status code. |
| `-w "api  %{http_code}\n"` | Print the word `api` and then the status code. |
| `http://127.0.0.1:15000/health` | `127.0.0.1` means "this computer", `15000` is the API's door, `/health` asks "are you alive?". |

Real output:

```
api       200
mcp       200
receiver  200
```

Three 200s: all three are up. The doors use unusual numbers so they never clash
with anything else you run:

| Port | What is behind it |
| :--- | :--- |
| 15000 | The API |
| 16379 | Redis |
| 19100 | The reaper's numbers (metrics) |
| 18080 | The MCP server |
| 19000 | The webhook receiver |

**Put two test documents where the tools can reach them:**

```bash
mkdir -p /c/test
cp tests/fixtures/sample.pdf tests/fixtures/sample.png /c/test/
```

`mkdir -p` makes the folder `C:\test` (and says nothing if it exists). `cp`
copies a small PDF and a small PNG into it. In Git Bash, `/c/test` and
`C:/test` are the same folder.

**A shortcut for looking at Redis.** The full command to ask Redis anything is
long, so define a short name for it in this terminal:

```bash
alias rcli='docker exec visual_document_understanding-redis-1 redis-cli -a smoke-test-password --no-auth-warning'
```

| Part | Meaning |
| :--- | :--- |
| `alias rcli='...'` | From now on in this terminal, typing `rcli` means the long command. |
| `docker exec visual_document_understanding-redis-1` | Run something inside the Redis container. |
| `redis-cli` | Redis's own command-line program. |
| `-a smoke-test-password` | The Redis password in this test stack (the cluster uses a real one, from a Secret). |
| `--no-auth-warning` | Do not print a warning about typing a password on the command line. |

Test it: `rcli PING` answers `PONG`.

**Terminal 2**, start the demo worker (activate the environment first):

```bash
source .venv/Scripts/activate
REDIS_HOST=127.0.0.1 REDIS_PORT=16379 REDIS_PASSWORD=smoke-test-password \
  python tools/demo_worker.py
```

The three `NAME=value` words before `python` are settings handed to just this
one program: where Redis is and its password. The `\` at the end of the first
line means "the command continues on the next line".

Real output:

```
demo worker ready (delay 6.0s, fail=False, warn=False)
this is a stand-in: no layout detection, no model, canned output
```

It prints a line every time it takes and finishes a document. Keep this
terminal visible.

---

## 5. Test A: the whole system checked in one command

**Stop the demo worker first** (Ctrl+C in terminal 2). This test checks that
documents wait untouched on the shelf, which is only true when nobody is taking
them.

```bash
python tests/integration/smoke.py
```

It is a script that plays every part in turn: a client, a broken worker, an AI
assistant, an attacker. It prints one line per check. `[ok  ]` means the check
passed; the first failure prints `[FAIL]` and stops. The text after each check
is the evidence it looked at.

Expected: **84** lines starting `[ok  ]`, ending with `All smoke checks passed.`
Here is the real output, section by section, with what each part means.

### The API and Redis are up

```
[ok  ] API answers /health within 60s
[ok  ] API /ready is 200 (Redis reachable with password)
[ok  ] Redis reachable with password
[ok  ] Redis rejects unauthenticated clients
[ok  ] Redis persistence is on
```

The front counter is open, and it can reach the shelves (`/ready` only says yes
if Redis answers). Redis answers when given the password and **refuses** anyone
without it. "Persistence is on" means Redis writes everything to disk, so a
restart does not wipe the shelves.

### Accepted uploads, and what lands in Redis

```
[ok  ] sample.pdf: POST /process returns 202  got 202 {'task_id': 'b299969a-d2a3-4159-81fa-58d705bfbf3f', 'status': 'queued'}
[ok  ] sample.pdf: task_id looks like a UUID
[ok  ] sample.pdf: GET /status returns 200  got 200
[ok  ] sample.pdf: status queued, attempts 0 (no worker should be running)  {..., 'status': 'queued', ..., 'attempts': 0}
[ok  ] sample.pdf: stored filename matches
[ok  ] sample.pdf: stored extension detected as pdf  pdf
[ok  ] sample.pdf: the document is not inside the task hash
[ok  ] sample.pdf: stored raw bytes match the file exactly
[ok  ] sample.pdf: the stored document expires
[ok  ] sample.pdf: task_id is on the waiting queue
```

(The same ten lines follow for `sample.png`, then:)

```
[ok  ] PDF uploaded as .jpg is accepted  got 202
[ok  ] ...and stored with extension pdf, from its content  pdf
```

The script hands in a PDF. The API answers 202 with a ticket number (a UUID, a
36-character random ID). Asking for its status says "queued, tried 0 times",
because no worker is running. Then the script looks at the shelves directly:

- the document is stored **as the exact bytes of the file**, in its own drawer,
  not squeezed into text inside the task record (that saves memory and makes
  status checks fast);
- that drawer has an expiry date, so a forgotten document cannot sit there
  forever;
- the file type came from the file's **first bytes**, not its name: a PDF
  renamed to `.jpg` is still stored as a PDF.

### The result cache

```
[ok  ] first upload of a document is 202 queued  202 {'task_id': '3194aa6a-...', 'status': 'queued'}
[ok  ] identical upload while waiting joins the same task (202, deduplicated)  202 {'task_id': '3194aa6a-...', 'status': 'queued', 'deduplicated': True}
[ok  ] ...and the queue holds it once
[ok  ] identical upload after it is done is 200 with cached true  200 {'task_id': '3194aa6a-...', 'status': 'done', 'cached': True}
[ok  ] Cache-Control: no-cache forces a new task  202 {'task_id': '5f098c4c-...', 'status': 'queued'}
```

The same document handed in twice while the first is still waiting gets **the
same ticket** (`deduplicated`), and it sits on the shelf once, so nobody reads it
twice. Once it is done, handing it in again gets the finished answer straight
away (`200`, `cached: True`), with no reading at all. Saying `no-cache` forces a
fresh reading with a new ticket. Section 7 does this by hand.

### Rejections, and hostile input

```
[ok  ] text in the file field (curl without @) is 400  got 400
[ok  ] ...with a message that mentions file=@  the 'file' field must be a file upload, not text (with curl, use file=@path)
[ok  ] unsupported content is 415  got 415
[ok  ] empty file is 400  got 400
[ok  ] missing file field is 400  got 400
[ok  ] a file of exactly 10485760 bytes is accepted  got 202 {...}
[ok  ] one byte more is 413, with both sizes in the message  got 413 the file is 10485761 bytes; the limit is 10485760 bytes
[ok  ] far oversized upload is 413  got 413
[ok  ] callback to a host not on the allowed list is 400  400 callback host evil.example.net is not in the allowed list
[ok  ] callback to an internal service is 400  400 callback host redis is not in the allowed list
[ok  ] nothing was queued by the rejected uploads  []
[ok  ] unknown task_id returns 404  got 404
```

Every way of handing in the wrong thing is refused at the counter, with a
message a person can act on: text instead of a file (what curl sends when you
forget the `@`), something that is not a PDF or picture, an empty file, a form
with no file. The size limit is exact: a file of exactly 10 MiB (10,485,760
bytes) is accepted and **one byte more** is refused. A request asking to be
called back at a website not on the approved list, or at an internal service
like Redis, is refused (otherwise anyone could make the system call places it
should not). None of the refused requests put anything on the shelf.

### Webhooks: the system calls the client back

```
[ok  ] webhook receiver is up
[ok  ] upload with an allowed callback_url is 202  202 {'task_id': '5bc51174-...', 'status': 'queued'}
[ok  ] ...and the callback address is stored with the task
[ok  ] the reaper delivered the callback to the receiver
[ok  ] ...with status done and the result  [{'path': '/done', ..., 'status': 'done', 'signature_valid': True, ...}]
[ok  ] ...and a valid signature  [...]
[ok  ] GET /status shows callback_status delivered  delivered (HTTP 200)
```

The script hands in a document with "call me back at this address when done",
pretends to be a worker finishing it, and then checks the receiver container
really got the call, with the result, and with a **valid signature** (proof the
call came from this system). The task's status then says `delivered`. Section 10
does this by hand.

### API metrics

```
[ok  ] API /metrics is 200
[ok  ] API counts requests by route
[ok  ] API counts rejections by reason
[ok  ] API counts refused callbacks
[ok  ] API records upload sizes by type
[ok  ] API counted the 413s
[ok  ] API counts cache hits, joins, and bypasses
```

The API keeps running totals (metrics) that Prometheus collects and Grafana
draws: how many requests, how many refused and why, how big the uploads are,
how often the cache helped. These checks confirm each total exists and moved.

### The reaper, live: a worker dies holding a task

```
[ok  ] reaper requeues a claim older than STALE_AFTER_SECONDS
[ok  ] ...task is back on the waiting queue
[ok  ] ...and off the in-progress list
[ok  ] reaper dead-letters after MAX_ATTEMPTS  {'status': 'failed', 'error': 'abandoned by its worker (no completion after 3601s, attempt 3); gave up after 3 attempts', ...}
[ok  ] ...with a reason in the error field
[ok  ] ...on the dead letter queue
[ok  ] ...the stored document is deleted
[ok  ] ...and the result expires
[ok  ] ...and the API shows failed with the error
```

The script fakes a worker that took a document an hour ago and never finished.
Within seconds the reaper puts it back on the waiting shelf. Then it fakes one
that has already been tried three times: the reaper gives up, moves it to the
dead-letter shelf with the reason written down, deletes the stored document, and
the API reports `failed` with that reason. Nothing is ever silently lost.

### Reaper metrics

```
[ok  ] reaper /metrics is 200
[ok  ] reaper publishes queue depths
[ok  ] reaper counted its actions
[ok  ] reaper counted the webhook delivery
```

The reaper publishes how many documents are on each shelf. These are the
numbers the autoscaler uses to decide how many GPUs to switch on.

### The MCP server, over real HTTP with a token

```
[ok  ] MCP /health answers without a token
[ok  ] MCP rejects requests without a bearer token (401)  got 401
[ok  ] MCP connects with the token
[ok  ] MCP server identifies itself  name='visual-document-understanding' ... version='0.6.0' ...
[ok  ] MCP negotiated a protocol version  2026-07-28
[ok  ] MCP lists the four tools  ['extract_structured_data', 'get_document_status', 'read_document', 'submit_document']
[ok  ] MCP serves the result schema resource
[ok  ] MCP submit_document reaches the real API  {"task_id": "d84b1b8c-...", "status": "queued", "cached": false, "deduplicated": false}
[ok  ] ...and the task is on the real queue
[ok  ] MCP get_document_status reads it back  {..., 'status': 'queued', ...}
[ok  ] MCP refuses a path outside the allowed directory  Error executing tool read_document: /etc/hostname is outside the allowed directories (/fixtures). ...
[ok  ] MCP refuses a URL that points inside the network  Error executing tool read_document: the URL was refused: redis points to 172.22.0.2, which is not a public address, so it is not fetched
[ok  ] MCP refuses plain http URLs by default  Error executing tool read_document: the URL was refused: only https URLs are accepted (got http)
```

The script connects the way an AI assistant does. Without the token it is
turned away (401). With it, it sees the server's name, version, and four tools,
hands in a real document through MCP, and finds it on the real shelf. Then the
three refusals: a file outside the one folder it may read, a web address that
leads inside the network (here, Redis), and a plain `http` address. The last two
matter because a document an assistant reads could contain text that tries to
trick it into fetching internal addresses, so the server checks every address
itself.

If a check fails, the most common one is:

```
[FAIL] sample.pdf: status queued, attempts 0 (no worker should be running)
  <- if status is processing/done, a worker (or tools/demo_worker.py) is
     consuming the queue; stop it and rerun
```

A worker was running. Stop it and run again. Restart the demo worker once this
test passes.

---

## 6. Test B: one document by hand

The whole pipeline in a few commands, with no MCP involved, so you can see each
layer do its job. For the first half, **keep the demo worker stopped**, so you
can look at the document while it waits.

**Hand in a document:**

```bash
curl -s -X POST http://127.0.0.1:15000/process -F "file=@C:/test/sample.pdf"
```

| Part | Meaning |
| :--- | :--- |
| `-X POST` | We are sending something, not just asking. |
| `/process` | The API's "please read this" address. |
| `-F "file=@C:/test/sample.pdf"` | Send it as a form with one field, `file`. The `@` means "the contents of this file". Without the `@`, curl sends the words `C:/test/sample.pdf` instead of the file, and the API refuses it with a 400. |

Real output:

```json
{"task_id":"aaf30b99-7506-44a9-a2f6-ddd35bcf86a2","status":"queued"}
```

Your ticket number, and "queued": it is on the waiting shelf. Copy your own
task_id; the commands below use this one.

**Ask how it is doing:**

```bash
curl -s http://127.0.0.1:15000/status/aaf30b99-7506-44a9-a2f6-ddd35bcf86a2 | python -m json.tool
```

`/status/<task_id>` asks about one ticket. The `|` (a pipe) passes curl's answer
to the next program, and `python -m json.tool` lays JSON out neatly over several
lines.

Real output:

```json
{
    "task_id": "aaf30b99-7506-44a9-a2f6-ddd35bcf86a2",
    "status": "queued",
    "result": null,
    "error": null,
    "warning": null,
    "attempts": 0
}
```

Waiting, no result yet, no error, tried 0 times.

**Look at the shelves directly:**

```bash
rcli LLEN ocr_tasks
rcli HGETALL task:aaf30b99-7506-44a9-a2f6-ddd35bcf86a2
rcli STRLEN taskdata:aaf30b99-7506-44a9-a2f6-ddd35bcf86a2
rcli TTL taskdata:aaf30b99-7506-44a9-a2f6-ddd35bcf86a2
rcli KEYS '*'
```

| Command | Question it asks Redis |
| :--- | :--- |
| `LLEN ocr_tasks` | How many documents are on the waiting shelf? |
| `HGETALL task:<id>` | Show every field of this task's record card. |
| `STRLEN taskdata:<id>` | How many bytes is the stored document? |
| `TTL taskdata:<id>` | How many seconds until it expires? |
| `KEYS '*'` | List every name in Redis. (Fine on a test stack; never on a busy one.) |

Real output, in order:

```
1
```
```
filename
sample.pdf
cache_key
cache:1:default:b2d3f05f5b9bfd91aa2adad2dcfecea5d84a257b055539b1891c9920318566cc
status
queued
submitted_at
1790675217.191
extension
pdf
attempts
0
```
```
612
```
```
172792
```
```
task:aaf30b99-7506-44a9-a2f6-ddd35bcf86a2
taskdata:aaf30b99-7506-44a9-a2f6-ddd35bcf86a2
ocr_tasks
cache:1:default:b2d3f05f5b9bfd91aa2adad2dcfecea5d84a257b055539b1891c9920318566cc
```

Reading it:

- One document waiting.
- The record card (printed as name, then value, one per line): the file name,
  the detected type, "queued", tried 0 times, the time it arrived (in seconds
  since 1970), and a `cache_key`. The long hex string in the cache key is the
  document's **fingerprint** (a SHA-256 hash): the same bytes always give the
  same fingerprint, which is how the cache recognises a repeat. The `1` is the
  pipeline version and `default` is the profile, so changing either never
  serves an old answer.
- The document itself is **612 bytes**, exactly the size of `sample.pdf`, in a
  drawer of its own. As base64 text it would be about a third bigger (roughly
  816 bytes here), and inside the record card every status check would drag it
  along.
- It expires in about 48 hours (172,800 seconds is two days) if no worker ever
  gets to it.
- Four names in Redis: the record card, the document, the waiting shelf, and the
  fingerprint.

**Now start the demo worker in terminal 2** (the command from section 4). Within
two seconds it prints:

```
claimed aaf30b99-7506-44a9-a2f6-ddd35bcf86a2 (sample.pdf), attempt 1
  done
```

**Ask again.** Real output (the result is shortened here):

```json
{
    "task_id": "aaf30b99-7506-44a9-a2f6-ddd35bcf86a2",
    "status": "done",
    "result": {
        "markdown": "# ACME CORPORATION\n\nInvoice #: INV-2026-0042\nDate: 2026-09-2...",
        "layout": "[1 page, 4 regions]"
    },
    "error": null,
    "warning": null,
    "attempts": 1
}
```

Done, on the first try. `markdown` is the document as text with headings and
tables; `layout` lists every region found on each page with its position. (The
demo worker's answer is always this invoice.)

**And the shelves afterwards:**

```bash
rcli EXISTS taskdata:aaf30b99-7506-44a9-a2f6-ddd35bcf86a2
rcli TTL task:aaf30b99-7506-44a9-a2f6-ddd35bcf86a2
rcli LLEN ocr_tasks
rcli LLEN ocr_tasks:processing
rcli LLEN ocr_tasks:dead
```

Real output: `0`, then `86395`, then `0`, `0`, `0`.

The stored document is **gone** (`EXISTS` answers 0): once a task is finished
the document is deleted at once. The result stays for a day (86,400 seconds),
then expires. All three shelves are empty.

---

## 7. Test C: the result cache

With the demo worker running, hand in **the same file again**:

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:15000/process -F "file=@C:/test/sample.pdf"
```

`-w "\nHTTP %{http_code}\n"` prints the status code after the answer.

Real output:

```
{"task_id":"aaf30b99-7506-44a9-a2f6-ddd35bcf86a2","status":"done","cached":true}
HTTP 200
```

The **same ticket** as in Test B, already `done`, answered with 200 instead of
202, and `cached: true`. The worker in terminal 2 printed nothing: it was never
involved. On the cluster this is a document read without switching on a GPU.

**Ask for a fresh reading anyway:**

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:15000/process \
  -H "Cache-Control: no-cache" -F "file=@C:/test/sample.pdf"
```

`-H` adds a header to the request. `Cache-Control: no-cache` is the standard web
way of saying "do not give me a stored copy".

Real output:

```
{"task_id":"85c05a45-7c75-4096-b260-878ed1cd2827","status":"queued"}
HTTP 202
```

A new ticket, queued. **Straight away, before the worker finishes it**, hand in
the same file once more (without `no-cache`):

```
{"task_id":"85c05a45-7c75-4096-b260-878ed1cd2827","status":"processing","deduplicated":true}
HTTP 202
```

You are given **the ticket already being worked on** (`deduplicated`), not a
third one. Two people handing in the same page at once get one reading.

**When the cache refuses to remember.** A result is only kept for reuse if it
was a clean success. A failure, or a result with a warning that some regions
could not be read, is not reused, so the next identical upload gets a fresh try
rather than a copy of a bad answer.

**The counters:**

```bash
curl -s http://127.0.0.1:15000/metrics | grep "^vdu_cache_total"
```

`grep "^vdu_cache_total"` keeps only the lines that start with that name.

Real output:

```
vdu_cache_total{outcome="bypass"} 7
vdu_cache_total{outcome="dedupe"} 2
vdu_cache_total{outcome="hit"} 2
vdu_cache_total{outcome="miss"} 3
```

Running totals since the API started (they include the smoke test's uploads):
`hit` answered from the cache, `dedupe` joined a task in progress, `miss` was new,
`bypass` asked for `no-cache`.

---

## 8. Test D: a worker dies, the document survives

A worker dies holding a document, and the document still gets read.

**Terminal 2:** stop the demo worker (Ctrl+C), then start it with a long delay
so you have time to kill it mid-document:

```bash
REDIS_HOST=127.0.0.1 REDIS_PORT=16379 REDIS_PASSWORD=smoke-test-password \
  python tools/demo_worker.py --delay 300
```

`--delay 300` tells it to pretend each document takes 300 seconds.

**Terminal 1:** hand in a document, with `no-cache` so the cache does not answer
for it:

```bash
curl -s -X POST http://127.0.0.1:15000/process -H "Cache-Control: no-cache" -F "file=@C:/test/sample.pdf"
```

The worker prints `claimed ...`. Look at the in-progress shelf:

```bash
rcli LRANGE ocr_tasks:processing 0 -1
```

`LRANGE <shelf> 0 -1` lists a shelf from the first item (0) to the last (-1).
Your task_id is there. **Now kill the worker** (Ctrl+C in terminal 2). The
document is stranded: on the in-progress shelf, with nobody reading it. Without
the reaper it would stay there forever.

The test stack tells the reaper to act after two minutes
(`STALE_AFTER_SECONDS=120`; on the cluster it is 15 minutes). Watch it:

```bash
docker compose -f docker-compose.test.yml logs -f reaper
```

`logs -f` shows the reaper's messages and keeps following new ones (Ctrl+C to
stop watching). After two minutes you will see a line like:

```
{"text": "... WARNING ... Requeued: abandoned by its worker (no completion after 121s, attempt 1)\n", ...}
```

The logs are JSON, one message per line, so machines can search them; the part
to read is inside `"text"`. Start a normal worker again
(`python tools/demo_worker.py`) and the document completes with `attempts: 2`.
Nothing was lost.

**To see the give-up path**, run the worker with `--fail`, which makes it fail
every document on purpose:

```bash
REDIS_HOST=127.0.0.1 REDIS_PORT=16379 REDIS_PASSWORD=smoke-test-password \
  python tools/demo_worker.py --fail
```

Hand in a document (with `no-cache`). It is tried three times (`MAX_ATTEMPTS`):

```
claimed 39397f62-... (sample.pdf), attempt 1
  requeued: demo failure
claimed 39397f62-... (sample.pdf), attempt 2
  requeued: demo failure
claimed 39397f62-... (sample.pdf), attempt 3
  failed: demo failure
```

Then look at the dead-letter shelf and the status:

```bash
rcli LRANGE ocr_tasks:dead 0 -1
curl -s http://127.0.0.1:15000/status/<task-id> | python -m json.tool
```

The status says:

```
status  : failed
attempts: 3
error   : demo worker was told to fail (--fail) (gave up after 3 attempts)
```

and the id is on the dead-letter shelf. **A failure is reported as a failure,
never as `done` with empty text**, which would look like success.

**To see a partial success**, run with `--warn`. The document completes, but
carries a `warning` that parts could not be read:

```
status  : done
warning : 2 region(s) in this batch of 1 document(s) failed to transcribe and
          were dropped from the output; this document may be incomplete
```

**A trap when switching modes.** Ctrl+C in its own terminal is the reliable way
to stop the demo worker. If you started it in the background, `pkill` in Git
Bash does not reach it (it is a Windows program). If a document is taken
instantly by a worker you thought you had stopped, find and stop it in
PowerShell:

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*demo_worker*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

This lists running Python programs, keeps the ones whose command line mentions
`demo_worker`, and stops them.

**A clean slate** between experiments:

```bash
rcli FLUSHALL
```

`FLUSHALL` empties Redis completely: every shelf, task, and cached result.

---

## 9. Test E: bad documents, at the door and inside

Two lines of defence. The **counter** (the API) refuses anything that is
obviously wrong. The **worker** opens every document before reading it and
refuses anything that only looks right from the outside.

**At the counter.** Forgetting the `@`:

```bash
curl -s -X POST http://127.0.0.1:15000/process -F "file=C:/test/sample.pdf"
```

```
the 'file' field must be a file upload, not text (with curl, use file=@path)
```

Something that is not a document:

```bash
echo "hello" > /tmp/notes.txt
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:15000/process -F "file=@/tmp/notes.txt"
```

`echo "hello" > /tmp/notes.txt` writes the word hello into a small text file.

```
unsupported file type; send a PDF, PNG, or JPEG
HTTP 415
```

A PDF with a misleading name is accepted, and stored as a PDF:

```bash
cp /c/test/sample.pdf /tmp/misnamed.jpg
curl -s -X POST http://127.0.0.1:15000/process -H "Cache-Control: no-cache" -F "file=@/tmp/misnamed.jpg"
rcli HGET task:<the id it returned> extension
```

Prints `pdf`: decided from the file's first bytes, not its name. That matters
because the reading software picks its PDF or picture reader from the type.

**Inside the worker.** A file that starts like a PDF but is garbage
after that gets past the counter, because the counter only looks at the first
bytes. With the demo worker running:

```bash
printf '%%PDF-1.7\nthis is not really a pdf\n' > /c/test/broken.pdf
curl -s -X POST http://127.0.0.1:15000/process -F "file=@C:/test/broken.pdf"
```

`printf` writes that exact text into a file: the first line is what a real PDF
starts with, the rest is nonsense. (`%%` is how you write a single `%` in
`printf`.)

Real output, from the API and then the worker:

```
{"task_id":"f48de862-8b79-4da9-8dc1-dc077a57ff06","status":"queued"}
```
```
claimed f48de862-8b79-4da9-8dc1-dc077a57ff06 (broken.pdf), attempt 1
  failed: document rejected: the PDF could not be opened (Failed to load document (PDFium: Data format error)); it may be corrupt or password protected
```

And its status:

```json
{
    "task_id": "f48de862-8b79-4da9-8dc1-dc077a57ff06",
    "status": "failed",
    "result": null,
    "error": "document rejected: the PDF could not be opened (Failed to load document (PDFium: Data format error)); it may be corrupt or password protected",
    "warning": null,
    "attempts": 1
}
```

Failed on the **first** attempt, with a reason, and **not retried**: the same
broken bytes would fail the same way every time. The same check refuses a PDF
with more than 200 pages and a picture of more than about 89 million pixels.
Without this check, a broken file would reach the GPU inside a batch, where one
error could fail every document in that batch.

The same check runs in the demo worker and in the real worker, so this behaves
identically whichever you use.

---

## 10. Test F: webhooks, the system calls you back

Instead of asking "is it done yet?" again and again, a client can give an
address to be called at when the document is finished.

The test stack allows callbacks only to the receiver container (and to your own
machine). The receiver plays the client's app: it takes the call, checks the
signature, and remembers what it got.

**Hand in a document with a callback address**, demo worker running:

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:15000/process \
  -H "Cache-Control: no-cache" \
  -F "file=@C:/test/sample.png" \
  -F "callback_url=http://webhook-receiver:9000/done"
```

A second `-F` adds a second form field, `callback_url`. The address uses the
receiver's name inside the Docker network (`webhook-receiver`), because the call
is made from inside that network.

Real output:

```
{"task_id":"324b6990-17dc-46de-b666-7f75273e1570","status":"queued"}
HTTP 202
```

**Try a callback address that is not allowed:**

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:15000/process \
  -F "file=@C:/test/sample.png" -F "callback_url=https://attacker.example.net/steal"
```

```
callback host attacker.example.net is not in the allowed list
HTTP 400
```

Refused before anything is stored. Callbacks are off entirely unless the
operator lists the allowed hosts (`CALLBACK_ALLOWED_HOSTS`); otherwise anyone
could make the system call any address it can reach.

**Ask the receiver what it got:**

```bash
curl -s http://127.0.0.1:19000/received
```

Real output (earlier entries from the smoke test are left out):

```json
  {
    "path": "/done",
    "task_id": "324b6990-17dc-46de-b666-7f75273e1570",
    "status": "done",
    "signature_valid": true,
    "error": null,
    "markdown_characters": 398
  }
```

The call arrived, said `done`, carried the 398-character result, and its
signature checked out. **The signature** is like a wax seal: the system and the
client share a secret, the system stamps each call with a code made from that
secret and the call's contents and time, and the client recomputes it. A forged
call, a changed call, or an old call replayed later fails the check. The
receiver's own log shows the same:

```bash
docker compose -f docker-compose.test.yml logs --no-log-prefix webhook-receiver | tail -1
```

```
received 324b6990-17dc-46de-b666-7f75273e1570: done, signature valid
```

(`--no-log-prefix` hides the container name at the start of each line; `tail -1`
keeps the last line.)

**And the task knows its call was answered:**

```bash
curl -s http://127.0.0.1:15000/status/324b6990-17dc-46de-b666-7f75273e1570 | python -m json.tool
```

```json
{
    "task_id": "324b6990-17dc-46de-b666-7f75273e1570",
    "status": "done",
    "result": {...},
    "error": null,
    "warning": null,
    "attempts": 1,
    "callback_status": "delivered (HTTP 200)"
}
```

The reaper made the call (not the worker, so a slow client can never hold up a
GPU), and the client answered 200. If a client never answers, the call is tried
three times and `callback_status` says `failed after 3 attempts: ...`; the result
can still be collected by asking, as always.

---

## 11. Test G: every MCP capability, in one script

`tools/try_mcp.py` connects to the MCP server over real HTTP, as an AI assistant
would, uses every capability, and prints what the assistant would see. With the
demo worker running:

```bash
python tools/try_mcp.py
```

Or one section at a time, for example `python tools/try_mcp.py cache`. The
sections are `discovery`, `read`, `cache`, `submit`, `resources`, `prompts`,
`extraction`, `elicitation`, `guards`, `auth`. The real output below was taken
right after `rcli FLUSHALL`, so the first read was not answered from the cache.

**1. Discovery.** What the assistant learns before doing anything:

```
server      : visual-document-understanding v0.6.0
protocol    : 2026-07-28

TOOLS (the model chooses these):
  - read_document(source)
      Read a document and return its full text and layout. Waits for the result.
  - submit_document(source)
      Submit a document for reading and return immediately with a task_id.
  - get_document_status(task_id)
      Check on a submitted document. Returns its status and, once done, the result.
  - extract_structured_data(source)
      Read a document and return its text together with the schema of fields to extract.

RESOURCES (the application reads these):
  - vdu://schema/result  [application/json]
  - vdu://reference/layout-labels  [application/json]
  - vdu://documents/{task_id}/markdown  (template)
  - vdu://documents/{task_id}/layout  (template)

PROMPTS (you choose these, as slash commands):
  - /extract_invoice(document, currency?)  Pull the key fields out of an invoice as JSON.
  - /summarise_document(document, length?)  Read a document and summarise it at the requested length.
  - /compare_documents(document_a, document_b)  Read two documents and report what differs.
```

The server's name and version, the protocol version both sides agreed on, and
the three kinds of thing MCP offers: **tools** (actions the model decides to
use), **resources** (data the application can read), and **prompts** (ready-made
instructions you pick, like slash commands). A `?` marks an optional argument.

**2. read_document, with live progress:**

```
  progress:   0.0/60.0  processing (attempt 1), 0s
  progress:   5.1/60.0  processing (attempt 1), 5s
  progress:   6.1/60.0  done (attempt 1), 6s
  progress:  60.0/60.0  done

  status   : done
  cached   : False
  attempts : 1
  warning  : None
  markdown : 383 chars, first lines:
             # ACME CORPORATION

             Invoice #: INV-2026-0042
             Date: 2026-09-20
             Due: 2026-10-20

  layout   : 1 page(s), labels on page 1: ['doc_title', 'text', 'table', 'text']

  (4 progress notifications arrived while it worked)
```

While it waited, the server sent progress messages (an assistant shows these as
a progress bar). `60.0` is the time limit the script set, in seconds. Then the
result: done on the first try, **not** from the cache, and what was found on the
page (a title, some text, a table, more text).

**2b. The result cache:**

```
  same document again        : cached=True   took  0.1s  task 8913d3c8...
  same document, fresh=true  : cached=False  took  6.1s  task 9285c533...

  A cached answer skips the queue and the GPU entirely. fresh=true processes it again.
```

The same document a second time comes back in a tenth of a second from the
cache. With `fresh=true`, the tool asks for a new reading, which takes the
worker's full six seconds. An assistant uses `fresh` when you say something like
"read it again properly".

**3. Submit now, collect later:**

```
  submitted: {
  "task_id": "9285c533-0019-4457-b9c0-cfa5b81e8043",
  "status": "done",
  "cached": true,
  "deduplicated": false
}
  poll 1: status=done attempts=1
```

`submit_document` returns immediately with a ticket, for long documents. Here the
answer was already done and cached (the fresh reading a moment earlier), so the
first check found it finished.

**4. Resources:**

```
  vdu://schema/result -> fields: ['task_id', 'status', 'attempts', 'markdown', 'layout', 'error', 'warning', 'cached']
  vdu://reference/layout-labels -> 17 kept, 8 discarded
     discarded: header, footer, number, footnote, aside_text, reference, footer_image, header_image
  vdu://documents/9285c533.../markdown -> [text/markdown] 383 chars
  vdu://documents/9285c533.../layout   -> [application/json] 361 chars
```

The shape of a result, the list of region types the layout model can find and
which ones are thrown away, and any finished document fetched by its ticket.

**5. Prompts.** What each slash command turns into:

```
  /extract_invoice becomes:
     Call extract_structured_data with source='/fixtures/sample.pdf' and document_type='invoice'. Then fill the schema it returns from the document text and reply with the JSON. You expected amounts in USD. If the document uses a different currency, keep the document's currency in the JSON and add one sentence after it saying so. Keep amounts in the document's own currency and never convert them. If a field is not in the document, use null. Do not guess.
```

(and one each for `/summarise_document` and `/compare_documents`). A prompt is a
well-written instruction, so everyone on a team asks the same way.

**6. Structured extraction:**

```
  document_type: invoice
  schema fields: ['vendor_name', 'vendor_address', 'invoice_number', 'invoice_date', 'due_date', 'currency', 'line_items', 'subtotal', 'tax', 'total']
  required     : ['vendor_name', 'invoice_number', 'total']
  markdown     : 383 chars handed to the model
  instruction  : Fill the schema from document_markdown. Answer with a single JSON object that validates against the schema. Use null for anything the document does not state. Do not invent values.
```

The server hands the assistant the document's text and a form to fill in (a
**schema**: the list of fields and their types). The assistant fills it itself;
the server runs no language model of its own.

**7. Elicitation, the server asks you:**

```
  SERVER ASKS: Which kind of document is this? The answer decides which fields to extract.
  (the host shows a form built from: ['document_type'])
  answering 'invoice' ...
  -> proceeded with document_type=invoice

  (1 question asked. With document_type given, it asks nothing.)
```

When the server cannot know something, it pauses and asks the person, instead of
guessing. The script answers "invoice" automatically; in Claude you would pick
from a list.

**8. Guards, everything it refuses:**

```
  a path outside the allowed folder:
     refused: Error executing tool read_document: /etc/hostname is outside the allowed directories (/fixtures). Set VDU_ALLOWED_DIRS to permit more.
  a file that does not exist:
     refused: Error executing tool read_document: file not found: /fixtures/nope.pdf
  something that is not a document:
     refused: Error executing tool read_document: the document was rejected: unsupported file type; send a PDF, PNG, or JPEG
  an unknown task id:
     refused: Error executing tool get_document_status: no task with id 00000000-0000-0000-0000-000000000000
  a schema that is not an object:
     refused: Error executing tool extract_structured_data: schema must be a JSON Schema object with type 'object' and 'properties'
  a URL that points inside the network:
     refused: Error executing tool read_document: the URL was refused: redis points to 172.22.0.2, which is not a public address, so it is not fetched
  a plain http URL:
     refused: Error executing tool read_document: the URL was refused: only https URLs are accepted (got http)
```

Each refusal comes with a sentence the assistant can pass on to you. The last two
are part of the security checks in section 15.

**9. Authentication:**

```
  without a token: HTTP 401  Bearer
  body: {"error":"unauthorized","detail":"a valid 'Authorization: Bearer <token>' header is required"}
  with the token : every call in this script succeeded
```

Over the network, the MCP server wants a token (a long secret string) with every
request, and says which kind (`Bearer`) when it is missing.

---

## 12. Test H: measuring speed

`tools/benchmark.py` measures the front counter and the shelves (the API and
Redis). It does **not** measure reading speed or GPUs; that needs the cluster.
**Stop every worker first**: it hands in hundreds of test documents and
measures them waiting.

```bash
python tools/benchmark.py --label my-first-run
```

`--label` names the run; the results are saved to
`benchmarks/my-first-run.json`. It takes about a minute. It cleans up after
itself.

This is the real output from a run on this machine on 29 September 2026 (laid
out more compactly than the script prints it, and with its label line left out):

```json
{
  "when": "2026-09-29T08:47:01+00:00",
  "machine": "Windows 11, 12 CPUs, Docker Desktop",
  "scope": "Rust API + Redis only, compose stack, no worker running. Not OCR or GPU performance.",
  "large": {
    "document_bytes": 9500016,
    "upload": {"n": 10, "p50_ms": 90.51, "p95_ms": 159.52, "p99_ms": 159.52, "mean_ms": 101.5},
    "redis_bytes_per_waiting_document": 10486469
  },
  "poll": {
    "status_poll_while_large_document_waits": {"n": 50, "p50_ms": 2.22, "p95_ms": 2.66, "p99_ms": 3.91, "mean_ms": 2.32}
  },
  "ingest": {
    "uploads": 500, "concurrency": 20, "seconds": 2.22, "uploads_per_second": 225.4,
    "upload": {"n": 500, "p50_ms": 70.8, "p95_ms": 192.9, "p99_ms": 271.19, "mean_ms": 85.8}
  },
  "cache": {
    "cache_hits": 50, "of": 50,
    "cached_upload": {"n": 50, "p50_ms": 2.84, "p95_ms": 3.62, "p99_ms": 6.05, "mean_ms": 2.98}
  }
}
```

The words:

| Word | Meaning |
| :--- | :--- |
| `n` | How many times it was measured. |
| `p50_ms` | The middle time, in milliseconds (thousandths of a second): half were faster, half slower. The fairest single number. |
| `p95_ms`, `p99_ms` | The time that 95, or 99, out of 100 beat. These show the slow moments. |
| `mean_ms` | The average. |

What each part measured:

- **large**: handing in a 9.5 MB document ten times. It took 90 ms in the middle
  case, and each waiting document used 10.5 MB of Redis memory.
- **poll**: asking "is it done?" 50 times while that big document waited: 2.2 ms
  each, because the document is stored apart from its status record.
- **ingest**: 500 small documents, 20 at a time: 225 accepted per second.
- **cache**: the same finished document handed in 50 times: all 50 answered from
  the cache, in under 3 ms each.

To compare two runs, open both JSON files side by side, or compare with the
numbers in [docs/performance.md](docs/performance.md). Your own numbers will
differ with your computer; what matters is comparing runs made on the same
machine.

### The whole pipeline: `throughput.py`

`benchmark.py` only times the front door. `tools/throughput.py` times the whole
journey: it sends the same document several times, each marked "no cache" so
every copy is really read, waits until all are finished, and reports how fast
documents came out the other end. **A worker must be running** for this one.

This is the real run against the demo worker, started with `--delay 2` so each
document takes 2 seconds:

```bash
python tools/throughput.py --file C:/test/sample.pdf --count 10 --concurrency 5 \
  --label demo-worker --hardware "Laptop, demo worker at 2 s per document"
```

| Part | Meaning |
| :--- | :--- |
| `--file` | The document to send. |
| `--count 10` | Send it ten times. |
| `--concurrency 5` | Five at a time. |
| `--label` | Names the run; results are saved to `benchmarks/throughput-<label>.json`. |
| `--hardware` | What it ran on, written into the results so the numbers never lose their context. |

Real output (the result part):

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

All ten were read, none failed. One demo worker reads one document at a time at 2
seconds each, so it can do at most 30 a minute; the tool measured 29.4, which is
how you know it counts correctly. `seconds_per_document` runs from upload to
result, so it includes waiting in the queue behind the others: that is what a
real user would wait.

With the demo worker these numbers only show the tool working. With the real
worker in Z.ai mode they measure Z.ai. On your cluster they are the numbers that
matter: [docs/performance.md](docs/performance.md) explains how to measure pages
per second, cold start, and cost per page there, and has the table to fill in.

---

## 13. Test I: measuring quality

`tools/evaluate.py` hands in documents whose correct reading is known, and
scores what comes back. It is how you tell whether a change to a prompt or a
profile made things better or worse.

**The documents.** `tests/fixtures/eval/` holds three pages drawn by
`tools/make_eval_set.py` from known text: an invoice in US dollars, a German
invoice in euros written the European way (`1.046,01 €`), and a clinic's
referral letter. Each has three files: the picture (`.png`), the perfect reading
(`.expected.md`), and a list of must-have facts such as amounts and names
(`.facts.json`). To rebuild them:

```bash
python tools/make_eval_set.py
```

```
wrote the evaluation set to C:\Users\<you>\Desktop\Projects\visual_document_understanding\tests\fixtures\eval
```

(It prints the full path of your own copy of the repository.)

**Run it** (a worker must be running):

```bash
python tools/evaluate.py run --label demo-a
```

Real output with the **demo worker**:

```
submitted invoice as 7262b95f-b526-4cec-9e60-7f1f27144674
submitted invoice_eur as 70ca0782-ef67-4696-a761-88c3552d7e5d
submitted letter as e58253bc-8e39-4a70-a45b-309a3328ccca

demo-a
document        status        text  tables   facts  overall
invoice         done          0.98    1.00    1.00     0.99
invoice_eur     done          0.48    0.31    0.00     0.26
                missing: RE-2026-0318, 21.09.2026, 21.10.2026, 12,50, 45,90, 879,00, 167,01, 1.046,01, €, EUR, DE89 3704 0044 0532 0130 00
letter          done          0.17       -    0.12     0.15
                missing: Harbour View Clinic, 3 March 2026, Amina Hassan, 150/95, 148/92, four weeks, Grace Wanjiru
average                                                0.47

saved to benchmarks\eval-demo-a.json
```

Each score runs from 0 (nothing right) to 1 (perfect):

| Score | What it checks |
| :--- | :--- |
| `text` | How closely the whole reading matches the perfect one, ignoring capitals, line breaks, and Markdown symbols. |
| `tables` | How many of the table's cells were found correctly. `-` means the document has no table. |
| `facts` | How many of the must-have facts appear anywhere. A single wrong digit barely changes `text` but loses a fact, which is why facts are scored separately. |
| `overall` | The average of the scores the document has. |

**Why these scores mean nothing here:** the demo worker always returns the ACME
invoice. So the dollar invoice scores almost perfectly (it happens to be the same
invoice), the euro invoice and the letter score low, and each `missing` line
lists the facts it did not find. That is the harness working correctly
on a fake reader.

**Compare two runs:**

```bash
python tools/evaluate.py compare benchmarks/eval-demo-a.json benchmarks/eval-demo-b.json
```

Real output (two identical demo runs, so no change):

```
document               demo-a       demo-b   change
invoice                  0.99         0.99    +0.00
invoice_eur              0.26         0.26    +0.00
letter                   0.15         0.15    +0.00
average                  0.47         0.47    +0.00
```

**How you will really use it,** once you have a real worker:

1. Add your own documents to `tests/fixtures/eval/`: for each, the file, its
   perfect reading as `<name>.expected.md`, and optionally `<name>.facts.json`.
   Scans and phone photos matter most; the three drawn pages are the easiest case
   there is.
2. `python tools/evaluate.py run --label before`
3. Change one thing: a prompt, a profile, a setting. Restart the worker.
4. `python tools/evaluate.py run --label after`
5. `python tools/evaluate.py compare benchmarks/eval-before.json benchmarks/eval-after.json`

Each run asks for fresh readings (`no-cache`), so a stored answer from before the
change is never scored by mistake.

---

## 14. Test J: the real worker, with Z.ai

This is the answer to "what about when I do have a balance". The compose file
includes the real worker, switched off unless asked for. It reads your Z.ai key
from `realtime_consumer/config.local.yaml`, which git ignores.

**Stop the demo worker first, and start from a clean slate:**

```bash
docker compose -f docker-compose.test.yml down -v
docker compose -f docker-compose.test.yml up -d
```

`down -v` removes the containers and Redis's saved data: the queue, the results,
and the cache. `up -d` starts them again, empty. Skip this and every document the
demo worker handled in the last day comes back at once, marked `cached`, with the
demo's made-up invoice instead of a real reading. (Tried on this machine:
`invoice.png`, sent once while the demo worker ran, came back
`"status":"done","cached":true` the next time.)

Then start the real worker:

```bash
docker compose -f docker-compose.test.yml --profile maas up -d --build worker
```

| Part | Meaning |
| :--- | :--- |
| `--profile maas` | Include the services marked "maas" (Z.ai's hosted mode). Only the worker is. |
| `up -d --build worker` | Build and start just the worker, in the background. The first build is large (about 8.7 GB, it carries GPU libraries) and takes a while. |

Watch it start:

```bash
docker compose -f docker-compose.test.yml --profile maas logs -f worker
```

Real output (the NVIDIA licence banner at the top is left out):

```
WARNING: The NVIDIA Driver was not detected.  GPU functionality will not be available.
2026-09-29 09:17:20.535 | INFO     | __main__:prepare_config:62 - Using profile 'default' (/config/config.local.yaml), Z.ai mode
[DEBUG] glmocr.maas_client: MaaS client initialized for https://api.z.ai/api/paas/v4/layout_parsing
[INFO] glmocr.api: GLM-OCR initialized in MaaS mode (cloud API passthrough)
2026-09-29 09:17:21.908 | INFO     | __main__:main:291 - Metrics on :9100/metrics
2026-09-29 09:17:21.908 | INFO     | __main__:worker_loop:262 - Starting worker (max batch 4, window 100ms, max attempts 3, result TTL 86400s)
```

- "NVIDIA Driver was not detected" is expected: in Z.ai mode the reading happens
  on Z.ai's computers, so no GPU is needed here.
- It read your config, set up the Z.ai connection, and is waiting for documents
  (up to 4 at a time, gathering for 100 ms, 3 tries each, results kept a day).

Now the tests in sections 6, 7, and 9 to 13 work exactly as written (section 8's
options belong to the demo worker), **except** that the answers are real
readings of your documents, and **every page costs money**.

**Your first real document.** Send `sample.pdf` as in section 6. It holds one line
of text, so the reading should be those words, `Visual Document Understanding Pipeline`,
perhaps shown as a heading. Then try a drawn invoice from the evaluation set,
from the repository folder:

```bash
curl -s -X POST http://127.0.0.1:15000/process -F "file=@tests/fixtures/eval/invoice.png"
```

Wait a few seconds, then print just the text of the reading (use your ID):

```bash
curl -s http://127.0.0.1:15000/status/<task_id> | python -c "import sys, json; print(json.load(sys.stdin)['result']['markdown'])"
```

The `python -c` part takes the JSON answer and prints only `result.markdown`, the
reading. Put it beside `tests/fixtures/eval/invoice.expected.md`: that file is
the perfect reading, so you can see at a glance how close the real one is. (If it
says `TypeError`, the status is not `done` yet, so there is no result to print;
wait and run it again.)

**An invoice in euros.** `tests/fixtures/eval/invoice_eur.png` is a German
supplier's invoice, written the European way: `1.046,01 €` is one thousand and
forty-six euros. Send it the same way:

```bash
curl -s -X POST http://127.0.0.1:15000/process -F "file=@tests/fixtures/eval/invoice_eur.png"
```

A good reading keeps every amount exactly as printed, with the comma as the
decimal point and the euro sign in place; compare it with
`tests/fixtures/eval/invoice_eur.expected.md`. Then copy the file into `C:\test`
and ask Claude (section 16) to *"extract the invoice fields from
C:\test\invoice_eur.png"*. The answer should give `currency` as `EUR`,
`currency_as_printed` as `€`, and the total as `1046.01`: read correctly, and
left in euros rather than converted to dollars. Section 13 scores the reading
part of this automatically.

**Do not send `sample.png` to the real worker.** It is a blank 2 by 2 pixel
image, so a real reader finds nothing on it. The worker treats an empty answer
as a failure that might succeed next time and tries it three times (three paid
calls) before recording `failed` with "SDK returned an empty result (no text and
no layout)". The demo
worker never reads the image, which is why it works there.

**Keep counts small.** `throughput.py --count 20` is twenty paid readings, and
the evaluation set is three. The cache helps: a document read once is answered
from the cache for a day, free, unless you ask for a fresh reading.

**If the balance is empty,** a document fails on the first attempt with an error
that contains `"code":"1113"` and ends with `(not retried: this error cannot
succeed on retry)`. Billing and key errors are never retried, so an empty
account costs nothing extra.

**Profiles.** A profile changes the instructions (prompts) the reading model is
given and which parts of a page are kept, for a kind of document: `finance`
keeps page headers and footers (where invoice numbers live), `academic` keeps
footnotes. Choose one by starting the worker with `VDU_PROFILE`:

```bash
docker compose -f docker-compose.test.yml --profile maas rm -sf worker
VDU_PROFILE=finance docker compose -f docker-compose.test.yml --profile maas up -d worker
```

(`rm -sf worker` stops and removes the running worker first; `-s` is stop, `-f`
is "do not ask".) Real output in the log:

```
WARNING  | __main__:prepare_config:60 - Profile 'finance' changes prompts and region rules, which Z.ai mode ignores; it only takes effect in self-hosted mode
INFO     | __main__:prepare_config:62 - Using profile 'finance' (/tmp/glmocr-finance.yaml), Z.ai mode
```

Read the warning: **in Z.ai mode the whole document goes to Z.ai's service, which
uses its own instructions**, so profiles only change anything on your own GPUs.
In Z.ai mode, leave the profile at `default`.

A misspelt profile stops the worker at once rather than running with the wrong
rules:

```bash
docker compose -f docker-compose.test.yml --profile maas rm -sf worker
VDU_PROFILE=legal docker compose -f docker-compose.test.yml --profile maas up -d worker
docker compose -f docker-compose.test.yml --profile maas ps -a worker
docker compose -f docker-compose.test.yml --profile maas logs --no-log-prefix worker | tail -1
```

`ps -a` shows the worker's state even after it has stopped, and the last line of
its log says why. Real output of the last two commands:

```
Exited (1) 15 seconds ago
unknown profile 'legal'; available: default, academic, finance
```

(`ps` prints a table; the state column is the part shown here.)

**Stop the real worker** when you are done, so it does not take documents meant
for the demo worker or the smoke test:

```bash
docker compose -f docker-compose.test.yml --profile maas rm -sf worker
```

---

## 15. Test K: the security you can see

**Nothing runs as the all-powerful user.** In Linux, `root` can do anything. Every
container here runs as an ordinary user, on a disk it cannot write to:

```bash
for s in api reaper mcp redis webhook-receiver; do
  printf '%-17s ' "$s"
  docker compose -f docker-compose.test.yml exec $s sh -c 'printf "%s  " "$(id)"; touch /probe 2>&1 || true'
done
```

This loops over the five containers. In each it prints who the program runs as
(`id`) and then tries to create a file (`touch /probe`).

Real output:

```
api               uid=10001(vdu) gid=10001(vdu) groups=10001(vdu)  touch: /probe: Read-only file system
reaper            uid=10001(vdu) gid=10001(vdu) groups=10001(vdu)  touch: cannot touch '/probe': Read-only file system
mcp               uid=10001(vdu) gid=10001(vdu) groups=10001(vdu)  touch: cannot touch '/probe': Read-only file system
redis             uid=999(redis) gid=1000(redis) groups=1000(redis)  touch: /probe: Read-only file system
webhook-receiver  uid=10001 gid=10001 groups=10001  touch: cannot touch '/probe': Read-only file system
```

`uid=0` would mean root; none are.
And none can write to their own disk: if someone did break into one, they could
not change its programs.

**No special powers either.** Linux "capabilities" are pieces of root's power
that can be handed out one by one. The API has none:

```bash
docker compose -f docker-compose.test.yml exec api sh -c 'grep -E "^Cap(Eff|Prm)|NoNewPrivs" /proc/1/status'
```

```
CapPrm:	0000000000000000
CapEff:	0000000000000000
NoNewPrivs:	1
```

All zeros means no powers at all, and `NoNewPrivs: 1` means it can never gain
any.

**The MCP server will not fetch internal addresses.** See the last two refusals
in section 11. You can also ask Claude to "read https://redis:6379/" and watch it
be refused.

**Callbacks will not go to strangers.** See the refused callback in section 10.

**What only a real cluster can show.** The rules about which part may talk to
which (NetworkPolicies: for example, only the API, the worker, the reaper, and
KEDA may reach Redis) are enforced by the cluster's network, which Docker on a
laptop does not have. The deployment guides include a one-line check to run on
the cluster that must print `blocked`; on a small local Kubernetes cluster
(kind) it did. To check it on your own cluster, see section 22.

---

## 16. Connecting the MCP server to Claude Code

The full instructions are in [docs/mcp_setup.md](docs/mcp_setup.md): installing
the server once, in its own environment (section 2), and registering it with
Claude Code (section 3). That guide also covers connecting to a deployed system.

**If you installed it into your main Python instead**, with a plain `pip install
./mcp_server`, that works too. Update it after pulling new code, so Claude gets
the current version (0.6.0, with the cache, `fresh`, the address checks, and the
rules for amounts in any currency).
Run this in a terminal where the project's environment is **not** active (type
`deactivate` if your prompt starts with `(.venv)`), because Claude Code starts
the copy installed in your main Python:

```bash
pip install --upgrade ./mcp_server
```

Then restart Claude Code and check it still connects:

```bash
claude mcp get visual-document-understanding
```

Real output, from an earlier registration:

```
visual-document-understanding:
  Scope: Local config (private to you in this project)
  Status: Connected
  Type: stdio
  Command: vdu-mcp
  Args:
  Environment:
    VDU_API_URL=http://127.0.0.1:15000
    VDU_ALLOWED_DIRS=C:\test

To remove this server, run: claude mcp remove visual-document-understanding -s local
```

`Connected` means Claude Code started the server, the two agreed a protocol, and
the tool list came back. `stdio` means they talk through the program's input and
output, with no network involved. `VDU_ALLOWED_DIRS=C:\test` is the only folder
the server may read files from.

---

## 17. What to ask Claude, and what you should see

Start Claude Code in the folder where you registered the server, with the demo
worker (or the real worker) running. Inside the session, `/mcp` shows the
connected servers and what they offer.

### 17.1 The basic read

> Read C:\test\sample.pdf and tell me what it says.

Claude calls `read_document`; you approve the tool the first time; it waits a few
seconds while the worker reads it, then answers. Terminal 2 shows `claimed ...
done` at the same moment. With the demo worker, expect an ACME invoice for
1180.00 USD.

**What this shows:** the whole pipeline driven by an assistant, with no code
written by you.

### 17.2 The specific question

> What is the total on C:\test\sample.pdf, and what are the line items?

Expect three line items (Widget large 540.00, Widget small 375.00, Delivery
85.00) and a total of 1180.00. **What this shows:** the table survived as a real
table, so the model can reason over rows instead of guessing from a blob of text.

### 17.3 The cache, seen from Claude

> Read C:\test\sample.pdf again.

This time the answer comes back at once, and nothing appears in terminal 2:
Claude got the stored reading (`cached: true`). Then:

> Read C:\test\sample.pdf again, fresh, don't use a stored copy.

Claude should pass `fresh: true` (the tool's description tells it how), and
terminal 2 shows the worker reading it again. If it does not, say "use fresh".

### 17.4 The question the server asks you

> Extract the fields from C:\test\sample.pdf.

You did not say what kind of document it is, so the server asks. Claude Code
shows a choice: invoice, receipt, contract, generic. Pick **invoice**; Claude
fills the invoice form and replies with JSON. Compare with:

> Extract the fields from C:\test\sample.pdf as an invoice.

No question this time, because you said.

### 17.5 The slash command

Type `/` in Claude Code and look for this server's prompts. Run the invoice one
on `C:\test\sample.pdf`. **What this shows:** a ready-made instruction you
choose, so everyone asks the same way.

### 17.6 The long document

> Submit C:\test\sample.pdf without waiting, then check on it.

Claude calls `submit_document`, gets a ticket immediately, and checks later with
`get_document_status`. Ask it to read `vdu://documents/<that task id>/markdown`
to see a resource in use.

### 17.7 The refusals

> Read C:\Windows\System32\drivers\etc\hosts

Refused, naming the allowed folder.

> Read C:\test\nonexistent.pdf

`file not found`.

> Read https://redis:6379/

Refused: the address is not public.

### 17.8 The failure path

Restart the demo worker with `--fail`, then:

> Read C:\test\sample.pdf fresh

After three attempts Claude reports that the document could not be read, with
the real reason, instead of being handed empty text that looks like success.

---

## 18. Connecting Claude Desktop instead

Claude Desktop reads a settings file rather than a command.
[docs/mcp_setup.md](docs/mcp_setup.md) section 4 walks through it: where the
settings are, what to put in the file, how to check it connected, and where its
logs are. With the server installed as that guide's section 2 describes, the
entry looks like this (put your own user name in the path; every backslash is
written twice in JSON):

```json
{
  "mcpServers": {
    "visual-document-understanding": {
      "command": "C:\\Users\\<you>\\.vdu-mcp\\Scripts\\vdu-mcp.exe",
      "env": {
        "VDU_API_URL": "http://127.0.0.1:15000",
        "VDU_ALLOWED_DIRS": "C:\\test"
      }
    }
  }
}
```

If you installed it into your main Python instead, the path is the `vdu-mcp.exe`
in that Python's `Scripts` folder (for Python 3.12 installed for one user, usually
`C:\Users\<you>\AppData\Local\Programs\Python\Python312\Scripts\vdu-mcp.exe`).
Quit Claude Desktop completely and start it again after saving.

---

## 19. The automated test suites

These are the checks that run on every change. With the environment active:

```bash
# Worker, reaper, profiles, pre-flight checks, webhooks: 70 tests
cd realtime_consumer && pip install -r requirements-dev.txt && pytest -q && cd ..

# The tools: evaluation scoring and throughput arithmetic, 12 tests
pytest -q tools/tests

# MCP server: 46 tests, driven through the SDK's own client
cd mcp_server && pip install -r requirements.txt -r requirements-dev.txt && pytest -q && cd ..
```

`pytest -q` runs every test it finds and prints one dot per passing test, then a
summary. Real endings: `70 passed`, `12 passed`, `46 passed`. None of these need
the stack running: they use a pretend Redis and a pretend API.

**The Kubernetes manifests.** If you have kubectl, this checks that every object
points at the others correctly (a scaler at a real deployment, a monitor at a
real service, and so on):

```bash
kubectl kustomize k8s/aks | python tests/manifests/check_references.py
```

Real output: `25 objects checked, 0 broken reference(s)`. The same for `k8s/gke`.

The worker's `requirements-dev.txt` includes the OCR SDK itself (without its GPU
parts), because the profile tests check each profile against the SDK's own
settings rules.

**Rust API: 32 tests.** Six need nothing; the other 26 need a real, empty Redis
to talk to. Without one they print `REDIS_URL not set; skipping` and pass without
checking anything, so run them with a throwaway Redis:

```bash
docker network create vdu-test
docker run -d --name vdu-test-redis --network vdu-test redis:7-alpine
MSYS_NO_PATHCONV=1 docker run --rm --network vdu-test \
  -v "$(pwd -W)/realtime_producer:/app" -w /app \
  -e REDIS_URL=redis://vdu-test-redis:6379 rust:1.88 cargo test
```

| Line | What it does |
| :--- | :--- |
| `docker network create vdu-test` | A private network for the two containers below. |
| `docker run -d --name vdu-test-redis ...` | Starts a throwaway Redis on that network. |
| `MSYS_NO_PATHCONV=1` | Stops Git Bash from rewriting `/app` into a Windows path. |
| `docker run --rm ... rust:1.88 cargo test` | Runs the tests inside the official Rust image, with the code folder shared in (`-v`) and Redis's address given (`-e`). `--rm` deletes the container afterwards. |
| `$(pwd -W)` | The current folder, written the Windows way, which Docker Desktop needs. |

The first run downloads and compiles for a few minutes. Real ending:
`test result: ok. 6 passed` and `test result: ok. 26 passed`. Afterwards:
`docker rm -f vdu-test-redis && docker network rm vdu-test`.

GitHub runs all of these on every push, plus the smoke test, a build of the
worker image with a check that it runs as an ordinary user, both Kubernetes
folders checked against the Kubernetes rules (custom KEDA and Prometheus objects
included) and for broken references, and a scan of every dependency for known
security problems.

---

## 20. When something does not work

**`claude mcp list` shows failed.** Run `vdu-mcp` by hand. It should print
`starting on stdio` and then wait silently. Anything else is the cause. Usually:
it is not found (use the full path), or it needs reinstalling
(`pip install --upgrade ./mcp_server`).

**Claude connects but every tool call fails.** The MCP server is fine; the API is
not reachable from it. Check `curl http://127.0.0.1:15000/health`. The port is
15000, not 5000.

**Every document stays `queued`.** No worker is running. Start one.

**A document comes back instantly and the worker did nothing.** That is the
cache: the same file was read in the last day. Add `-H "Cache-Control: no-cache"`
to curl, or ask Claude for a fresh reading.

**`ModuleNotFoundError` when running a tool.** The environment is not active in
this terminal (`source .venv/Scripts/activate`), or its packages are missing
(`pip install -r tools/requirements.txt`).

**Documents get retried and eventually fail with "abandoned by its worker".** The
reaper is reclaiming them before the worker finishes: `STALE_AFTER_SECONDS` is
shorter than the reading takes. The test stack sets 120 seconds; with the demo
worker at `--delay 300` that is expected.

**The smoke test fails on "status queued, attempts 0".** A worker is taking
documents. Stop it (the demo worker, and the real worker with
`docker compose -f docker-compose.test.yml --profile maas rm -sf worker`) and
run again.

**The real worker exits at once.** Read its log. `unknown profile` means
`VDU_PROFILE` is misspelt. `config for profile ... is not usable` lists what is
wrong with a profile file you edited.

**Claude reads a stale document.** Results last a day, and the demo worker always
returns the same invoice whatever you send. That is the demo worker, not the
pipeline.

**The real worker fails a document with "SDK returned an empty result".** The
document has no readable content, for example the blank `sample.png`. See
section 14.

**The real worker answers with the demo's made-up invoice, marked `cached`.**
The demo worker read that document earlier, and the cache kept its answer for a
day. Start from a clean slate as the start of section 14 shows, or send the
document with `-H "Cache-Control: no-cache"`.

**Problems on the cluster** are covered in section 22.9 and in the deployment
guides' troubleshooting sections.

---

## 21. Cleaning up

```bash
# stop the demo worker: Ctrl+C in terminal 2

# stop the real worker, if you started it
docker compose -f docker-compose.test.yml --profile maas rm -sf worker

# remove the MCP server from Claude Code
claude mcp remove visual-document-understanding

# stop the containers and delete their data
docker compose -f docker-compose.test.yml down -v

# leave the environment
deactivate
```

`down` stops and removes the containers; `-v` also deletes Redis's saved data, so
the next start is clean. `deactivate` switches the terminal back to your normal
Python.

After testing on the cluster, see section 22.9 instead.

---

## 22. Scenario C: testing on your GPU cluster

This is route C from section 1. The system is deployed in Azure or Google Cloud,
and you test it from your computer. A Z.ai balance is not needed: the cluster
reads documents with its own models.

The commands and outputs below were rehearsed on a local test cluster built from
the same manifests (30 September 2026). That cluster had no GPUs, so its
documents stayed `queued`; each step says what you should see instead on real
GPUs.

### 22.1 What you need

- The cluster deployed and checked, up to and including section 10 of
  [docs/aks_deployment.md](docs/aks_deployment.md) or
  [docs/gke_deployment.md](docs/gke_deployment.md). `kubectl get nodes` should
  list its machines.
- The tools' environment from section 3, and the test files in `C:\test` from
  section 4 (the `mkdir` and `cp` lines only; do not start the compose stack).
- **The compose test stack stopped**, if it is running, because the cluster is
  about to use the same ports on your computer:
  `docker compose -f docker-compose.test.yml stop`. This matters more than it
  looks. On Windows, the port-forward below does not complain when the stack is
  still running: it quietly takes `127.0.0.1:15000` and leaves
  `localhost:15000` to the stack. Then `127.0.0.1` reaches the cluster and
  `localhost` reaches your computer, and the same task ID is found by one and
  "not found" by the other. This was tried on this machine.
- An eye on the time. GPU machines bill while they run. Outside the warm hours
  (weekdays 8am to 6pm New York time, unless you changed them) the first
  document starts them, which takes several minutes.

### 22.2 Connect your computer to the cluster

The API and the MCP server have private addresses inside your cloud network. A
**port-forward** is a private tunnel from a port on your computer to a service
in the cluster, open as long as the command runs. Forwarding to the same port
numbers as the test stack means every command in this guide works unchanged.

**Terminal 1** (leave it running):

```bash
kubectl port-forward svc/ocr-api-service 15000:80
```

**Terminal 2** (leave it running):

```bash
kubectl port-forward svc/ocr-mcp-service 18080:80
```

`svc/ocr-api-service` is the API's service in the cluster, `15000:80` connects
port 15000 on your computer to its port 80. A port-forward is tied to one pod: if
that pod restarts (after an update, say), the command ends and you start it
again.

**Terminal 3**, for everything else. Activate the environment
(`source .venv/Scripts/activate`), then check both answer:

```bash
curl -s -o /dev/null -w "api  %{http_code}\n" http://127.0.0.1:15000/health
curl -s -o /dev/null -w "mcp  %{http_code}\n" http://127.0.0.1:18080/health
```

Rehearsal output:

```
api  200
mcp  200
```

**Looking inside Redis on the cluster.** The `rcli` shortcut from section 4
talks to the compose container. For the cluster, define this instead, as three
separate lines:

```bash
unalias rcli 2>/dev/null
rcli() { kubectl exec deploy/ocr-redis -- sh -c 'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning "$@"' _ "$@"; }
rcli PING
```

It is a small function: `rcli PING` runs `redis-cli PING` inside the Redis pod,
using the password the pod already holds, so you never see or type it. Rehearsal
output: `PONG`. The first line removes section 4's shortcut if this terminal still
has it; without it, the second line fails with
``syntax error near unexpected token `('``.

### 22.3 A first document, end to end

In a fourth terminal, watch the pods while you work:

```bash
kubectl get pods -w
```

`-w` keeps watching and prints a line every time a pod changes. Now send a
document from terminal 3:

```bash
curl -s -X POST http://127.0.0.1:15000/process -F "file=@C:/test/sample.pdf"
```

Rehearsal output (your ID will differ):

```json
{"task_id":"21ccadcf-9470-41ae-9638-0fac768c5d58","status":"queued"}
```

If no worker was running, terminal 4 now shows KEDA starting one: a
`ocr-worker-rt-deployment-...` pod appears as `Pending`, then
`ContainerCreating`, then `Running`, and a `ocr-vlm-deployment-...` pod the same
way. If the GPU machines were at zero, `Pending` lasts several minutes while a
machine starts, and vLLM needs up to ten more minutes to load the model. This is
KEDA's scale-from-zero working.

Ask for the status (use your ID):

```bash
curl -s http://127.0.0.1:15000/status/21ccadcf-9470-41ae-9638-0fac768c5d58 | python -m json.tool
```

While it waits (rehearsal output):

```json
{
    "task_id": "21ccadcf-9470-41ae-9638-0fac768c5d58",
    "status": "queued",
    "result": null,
    "error": null,
    "warning": null,
    "attempts": 0
}
```

**With GPUs**, once the worker and vLLM are ready, the status becomes `done` and
`result.markdown` holds the one line of text in the PDF,
`Visual Document Understanding Pipeline`. That is your first real reading on your own
hardware.

And the shelves (rehearsal output, while it waited):

```bash
rcli LLEN ocr_tasks
rcli STRLEN taskdata:21ccadcf-9470-41ae-9638-0fac768c5d58
rcli HGET task:21ccadcf-9470-41ae-9638-0fac768c5d58 status
```

```
1
612
queued
```

One document waiting, stored as its exact 612 bytes, status `queued`: the same
as on your computer in section 6.

### 22.4 Which of the earlier tests to repeat

| Test | On the cluster |
| :--- | :--- |
| B, one document by hand (section 6) | As written, with the cluster's `rcli` function. The answer is a real reading. |
| C, the cache (section 7) | As written. |
| D, a dying worker (section 8) | Send a document, and while it is being read: `kubectl delete pod -l app=ocr-worker-rt`. On the cluster the reaper waits 15 minutes (`STALE_AFTER_SECONDS`), then puts the document back; watch with `kubectl logs -l app=ocr-reaper -f`. It finishes with `attempts: 2`. The `--fail` and `--warn` parts are demo worker options; skip them. |
| E, bad documents (section 9) | As written. The real worker opens every document first, exactly as the demo worker does, so the corrupt PDF is refused the same way. |
| F, callbacks (section 10) | Only after turning callbacks on (deployment guide section 13) with an https receiver you control; the test receiver runs only in the compose stack. Otherwise skip it. |
| G, the MCP script (section 11) | With the cluster's token and a web address; see 22.5. |
| H, speed (section 12) | `throughput.py` as in 22.6. `benchmark.py` is for your computer only. |
| I, quality (section 13) | As written, with real readings; see 22.7. |
| A, J, K (sections 5, 14, 15) | For your computer only. The cluster's equivalents are the checks in the deployment guide's section 10. |

### 22.5 The MCP server in the cluster

The cluster's MCP server wants a token, which lives in a Secret. Put it in the
variable the tools read:

```bash
export MCP_BEARER_TOKEN=$(kubectl get secret ocr-mcp-secret -o jsonpath='{.data.tokens}' | base64 -d | cut -d, -f1)
```

This reads the Secret, decodes it, and keeps the first token if there are
several. It never prints the token.

The cluster's server cannot see your computer, so give it a web address. This
public test PDF is one page reading "Dummy PDF file":

```bash
DEMO_DOC=https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf \
  python tools/try_mcp.py discovery submit auth
```

Rehearsal output (shortened):

```
server      : visual-document-understanding v0.6.0
protocol    : 2026-07-28
...
  submitted: {
  "task_id": "ecb92c66-7aab-4f50-9c34-658fb81d7fed",
  "status": "queued",
  "cached": false,
  "deduplicated": false
}
  poll 1: status=queued attempts=0
...
  without a token: HTTP 401  Bearer
  body: {"error":"unauthorized","detail":"a valid 'Authorization: Bearer <token>' header is required"}
  with the token : every call in this script succeeded
```

The server in the cluster fetched the PDF from the internet (through the network
rules, which let it reach public addresses only), handed it to the API, and it
was queued; `rcli STRLEN taskdata:<id>` showed its full 13,264 bytes. Without the
token it answered 401. **With GPUs** the polls reach `done`, and running the
`read` section instead of `submit` returns the text, `Dummy PDF file`.

To have Claude Code use the cluster's server, see
[docs/mcp_setup.md](docs/mcp_setup.md) section 5a.

### 22.6 Speed on the GPUs

Measure how fast the GPUs read, with a real document of the kind you will
process:

```bash
python tools/throughput.py --file my-report.pdf --count 50 --concurrency 10 \
  --label cluster-first-run --hardware "<cloud>, 1 x A100 80GB, 1 x T4, <date>"
```

and the cold start, with the GPU machines at zero:

```bash
python tools/throughput.py --file my-report.pdf --count 1 --label cold-start \
  --hardware "<cloud>, GPU pools at zero, <date>"
```

Section 12 explains every field of the report. [docs/performance.md](docs/performance.md)
explains how to turn these into cost per page, how to tune the batching
settings, and how to test multi-token prediction, and has the table to record
your numbers in.

### 22.7 Quality on the GPUs

Section 13's evaluation now scores real readings made with your prompts:

```bash
python tools/evaluate.py run --label cluster-default
```

This is also where profiles finally do something (on your computer they cannot:
the demo worker ignores them and Z.ai uses its own prompts). To try one, set
`VDU_PROFILE=finance` in the kustomization, apply it
(`kubectl apply -k k8s/aks/`, or `k8s/gke/`), wait for the worker to restart,
then:

```bash
python tools/evaluate.py run --label cluster-finance
python tools/evaluate.py compare benchmarks/eval-cluster-default.json benchmarks/eval-cluster-finance.json
```

Add your own documents to `tests/fixtures/eval/` (section 13 explains how); two
drawn pages are the easiest possible case.

### 22.8 Watching it work

- **Scaling.** `kubectl get pods -w` shows KEDA adding workers as documents
  queue up and removing them five minutes after the queue empties (outside the
  warm hours).
- **The dashboard.** The deployment guide's section 10 shows how to open Grafana
  and the **Visual Document Understanding Pipeline** dashboard: queues, tasks per minute,
  vLLM's waiting requests, GPU use, and failures. On Google Cloud the GPU panel
  stays empty, because GKE sends GPU numbers to Cloud Monitoring instead (its
  guide's section 10).
- **One document's story.** Every log line about a document carries its ID:
  `kubectl logs -l app=ocr-worker-rt | grep <task_id>`.

### 22.9 When something does not work, and cleaning up

| What you see | What to do |
| :--- | :--- |
| A task ID is `Task ID not found` although you just made it, or `localhost` and `127.0.0.1` give different answers | The compose test stack is still running and shares the port with the port-forward (22.1). Stop the stack, then stop and start the port-forward. |
| `error: unable to listen on any of the requested ports: [{15000 5000}]` | Another port-forward already uses that port, probably in a terminal you forgot. Close it, or use another port on your side, such as `15001:80`, and set `API_URL=http://127.0.0.1:15001` for the tools. |
| `curl` fails after it worked | The port-forward ended, usually because the pod restarted. Start it again. |
| Documents stay `queued` for a long time | Outside the warm hours the first document starts a GPU machine and loads the model: allow up to 15 minutes. `kubectl get pods` shows where it is; `kubectl describe pod <name>` explains a `Pending` pod. |
| `rcli` says `Error from server (NotFound): deployments.apps "ocr-redis" not found` | kubectl is pointing at another cluster or namespace. `kubectl config current-context` shows which. |
| 401 from the MCP server | `MCP_BEARER_TOKEN` is not set in this terminal, or the token was rotated. Set it again (22.5). |

Anything else: the troubleshooting section of your deployment guide.

**Cleaning up.** Stop the port-forwards (Ctrl+C in terminals 1 and 2) and the
pod watch (terminal 4). Closing terminal 3 forgets the `rcli` function and the
token. The cluster scales its GPU machines back to zero by itself outside the
warm hours; to remove everything, follow the teardown in your deployment guide's
section 14.

---

## What this does not cover

- **Speed and cost on your hardware** until you measure them: section 22.6 and
  [docs/performance.md](docs/performance.md) show how. Nothing measured on a
  laptop, and nothing measured with the demo worker, says anything about GPUs.
- **Reading quality on your documents** until you add them to the evaluation
  set (section 13) and score real readings (section 14 or 22.7).
- **Long-running behaviour**: days of steady load, memory growth, and upgrades
  while documents are in flight. Watch the dashboard and the alerts once it is
  in real use.
