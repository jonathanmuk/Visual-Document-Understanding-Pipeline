# Connecting AI Assistants: the MCP Setup Guide

The MCP server lets an AI assistant such as Claude Code or Claude Desktop read
documents through this system as if it were one of its own abilities. You say
"read this invoice and tell me the total", and the assistant hands the invoice to
the pipeline, waits, and answers from the result.

This guide covers every way to connect, step by step. Every command here was
run while writing it. Where you must fill something in, it is written like
`<this>`.

## Contents

1. [Which setup do you need?](#1-which-setup-do-you-need)
2. [Install the server once](#2-install-the-server-once)
3. [Claude Code, on your own computer](#3-claude-code-on-your-own-computer)
4. [Claude Desktop, on your own computer](#4-claude-desktop-on-your-own-computer)
5. [Using a deployed system](#5-using-a-deployed-system)
6. [Every setting the server reads](#6-every-setting-the-server-reads)
7. [Rotating the deployed server's token](#7-rotating-the-deployed-servers-token)
8. [When something does not work](#8-when-something-does-not-work)

---

## 1. Which setup do you need?

Two things decide it: which assistant you use, and where the system is running.

| Your assistant | The system runs on | Setup | Section |
| :--- | :--- | :--- | :--- |
| Claude Code | Your computer (the test stack, or Track 1) | Local server | 3 |
| Claude Desktop | Your computer | Local server | 4 |
| Claude Code | The cluster | The cluster's own MCP server, or a local server pointed at the gateway | 5 |
| Claude Desktop | The cluster | A local server pointed at the gateway | 5 |

**Local server** means the MCP server runs on your computer, started by the
assistant itself whenever it needs it. It can read files on your computer (only
from folders you allow) and passes them to the system's API.

**The cluster's MCP server** runs next to the API in Kubernetes. It is shared by
everyone on the team, protected by a token, and cannot see anyone's computer, so
you give it web addresses (https URLs) of documents rather than file paths.

Either way, every document goes through the same API, queue, and worker.
Nothing about the reading changes.

---

## 2. Install the server once

The server is a small Python program. Install it into an environment of its
own, a folder that holds its own copies of the packages it needs, so it can
never disturb any other Python program on your computer. Both assistants then
start it by its full path, so it works whatever environment your terminal has
active.

**On Windows**, in Git Bash, from the repository folder:

```bash
python -m venv ~/.vdu-mcp
~/.vdu-mcp/Scripts/python -m pip install ./mcp_server
~/.vdu-mcp/Scripts/vdu-mcp --help
```

**On macOS or Linux**, the same, with `bin` in place of `Scripts`:

```bash
python3 -m venv ~/.vdu-mcp
~/.vdu-mcp/bin/python -m pip install ./mcp_server
~/.vdu-mcp/bin/vdu-mcp --help
```

| Line | What it does |
| :--- | :--- |
| `python -m venv ~/.vdu-mcp` | Makes the environment in a folder called `.vdu-mcp` in your home folder (`~` means your home folder, for example `C:\Users\<you>`). |
| `... -m pip install ./mcp_server` | Installs the server and the packages it needs into that environment only. |
| `... vdu-mcp --help` | Checks the program exists and starts. |

The last line should print:

```
usage: vdu_mcp [-h] [--transport {stdio,http}] [--host HOST] [--port PORT]
```

**Keep the folder's path short.** On Windows, one of the packages the server
needs (pywin32) has deeply nested files, and a long folder path pushes them
past Windows' 260-character limit, leaving a broken install. `~/.vdu-mcp` is
fine. A folder buried deep inside other folders may not be.

**The full path you will need later** is the program inside that folder:

| Computer | Full path to the server |
| :--- | :--- |
| Windows | `C:\Users\<you>\.vdu-mcp\Scripts\vdu-mcp.exe` |
| macOS | `/Users/<you>/.vdu-mcp/bin/vdu-mcp` |
| Linux | `/home/<you>/.vdu-mcp/bin/vdu-mcp` |

**To update it** after pulling new code, run the install line again with
`--upgrade`:

```bash
~/.vdu-mcp/Scripts/python -m pip install --upgrade ./mcp_server
```

Then restart the assistant, because it keeps the old copy running until then.

**If you installed it another way**, with `pip install ./mcp_server` straight
into your main Python, that still works. You can either keep it and update it
with `pip install --upgrade ./mcp_server`, or remove it from Claude Code
(`claude mcp remove visual-document-understanding -s local`) and follow this
section instead.

---

## 3. Claude Code, on your own computer

You need the system running: the test stack (API at `http://127.0.0.1:15000`)
from [testing-guide.md](../testing-guide.md), or the Track 1 setup (API at
`http://localhost:5000`) from [next-steps.md](../next-steps.md).

**Register the server.** Run this in the folder you want to use Claude Code
from, because by default the registration applies to that folder only:

```bash
claude mcp add visual-document-understanding \
  -e VDU_API_URL=http://127.0.0.1:15000 \
  -e "VDU_ALLOWED_DIRS=C:\test" \
  -- "C:/Users/<you>/.vdu-mcp/Scripts/vdu-mcp.exe"
```

| Part | Meaning |
| :--- | :--- |
| `visual-document-understanding` | The name Claude Code shows for it. |
| `-e VDU_API_URL=...` | Where the system's API is. |
| `-e "VDU_ALLOWED_DIRS=C:\test"` | The only folder the server may read files from. Anything outside it is refused. Several folders are separated by `;` on Windows and `:` on macOS and Linux. |
| `--` | Everything after this is the program to start. |
| `"C:/Users/<you>/.vdu-mcp/..."` | The full path from section 2. Forward slashes work on Windows too. |

Useful variations: add `-s user` before `--` to make it available in every
folder, not just this one.

**Check it connected:**

```bash
claude mcp list
```

```
visual-document-understanding: C:/Users/<you>/.vdu-mcp/Scripts/vdu-mcp.exe  - Connected
```

`Connected` means Claude Code started the server, the two agreed on a protocol
version, and the list of tools came back. Inside a Claude Code session, `/mcp`
shows the same, with the tools, resources, and prompts the server offers.

**Try it:** start Claude Code in that folder and ask *"Read C:\test\sample.pdf
and tell me what it says."* [testing-guide.md](../testing-guide.md) section 17
lists what to ask next and what you should see.

---

## 4. Claude Desktop, on your own computer

Claude Desktop reads a settings file instead of a command.

**1. Open the settings file.** Open Claude Desktop's own settings from the
application menu, not the settings inside a conversation:

- **Windows:** press `Ctrl+,`, or click the menu icon at the top left, point at
  **File**, and choose **Settings**.
- **macOS:** click **Claude** in the menu bar at the top of the screen, then
  **Settings...**

Then choose **Developer** in the list on the left, and click **Edit Config**.
That opens (or creates) this file:

| Computer | File |
| :--- | :--- |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |

**2. Add the server.** If the file is empty or only has `{}`, replace it with
this. If it already lists other servers, add the `"visual-document-understanding"`
block inside the existing `"mcpServers"`.

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

Three rules for this file: the path to the program must be the full path; every
backslash is written twice (that is how JSON writes one backslash); and on macOS
the path looks like `/Users/<you>/.vdu-mcp/bin/vdu-mcp`.

**3. Restart Claude Desktop completely.** Quit the application fully, then
start it again. It only reads this file when it starts.

**4. Check it connected.** In a conversation, click the button at the bottom
left of the message box labelled "Add files, connectors, and more", point at
**Connectors**, and choose **Manage connectors**. `visual-document-understanding`
should be listed, with its tools.

**If it is missing,** its log says why:

| Computer | Log files |
| :--- | :--- |
| Windows | `%APPDATA%\Claude\logs\mcp.log` and `mcp-server-visual-document-understanding.log` |
| macOS | `~/Library/Logs/Claude/mcp.log` and `mcp-server-visual-document-understanding.log` |

`mcp.log` records connection problems; the second file is everything the server
itself printed.

---

## 5. Using a deployed system

Once the system runs in the cluster, there are two ways in.

### 5a. The cluster's own MCP server, from Claude Code

This is the shared server the deployment guides create. It is on a private
address inside your cloud network and needs a token.

**What you need:**

- A way to reach the private address: a VPN into the cloud network, or, for
  testing, a port-forward (below).
- The token, from the cluster's Secret. Whoever runs the cluster reads it with:

  ```bash
  kubectl get secret ocr-mcp-secret -o jsonpath='{.data.tokens}' | base64 -d
  ```

  If it prints several tokens separated by commas, any one of them works.

**For testing from your computer**, forward a local port to the server:

```bash
kubectl port-forward svc/ocr-mcp-service 18080:80
```

Leave that running in its own terminal. While it runs, `http://127.0.0.1:18080`
on your computer reaches the server in the cluster. (A port-forward is tied to
one pod: if the server restarts, start the port-forward again.) If the testing
guide's compose stack is running on your computer, stop it first
(`docker compose -f docker-compose.test.yml stop`): its own MCP server uses port
18080 too, and on Windows both can hold the port at once without an error.

**Register it in Claude Code:**

```bash
claude mcp add --transport http visual-document-understanding \
  http://127.0.0.1:18080/mcp \
  -H "Authorization: Bearer <token>"
```

With a VPN instead, use the internal address:
`http://<internal address of ocr-mcp-service>/mcp`, which
`kubectl get svc ocr-mcp-service` shows under `EXTERNAL-IP` (on a private network,
that is still a private address).

**Remember:** this server cannot see your computer. Give it web addresses of
documents, for example *"Read
https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"*. It only
fetches https addresses that lead to public servers, so internal addresses are
refused on purpose.

### 5b. A local server pointed at the gateway (works for Claude Desktop too)

Run the local server from sections 3 or 4 on your computer, and point it at the
deployed API through the API gateway instead of at your computer. Your files
still work, because the local server reads them and uploads them.

The gateway asks for a key on every call. On Azure API Management that is a
subscription key (the deployment guide shows how to create one), sent in a
header called `Ocp-Apim-Subscription-Key`. Give the server the key and it sends
it with every call to the API, and never to any other address:

**Claude Code:**

```bash
claude mcp add visual-document-understanding \
  -e VDU_API_URL=https://<your-apim-name>.azure-api.net/ocr \
  -e VDU_API_KEY=<subscription key> \
  -e "VDU_ALLOWED_DIRS=C:\test" \
  -- "C:/Users/<you>/.vdu-mcp/Scripts/vdu-mcp.exe"
```

**Claude Desktop**, in the `env` block from section 4:

```json
"env": {
  "VDU_API_URL": "https://<your-apim-name>.azure-api.net/ocr",
  "VDU_API_KEY": "<subscription key>",
  "VDU_ALLOWED_DIRS": "C:\\test"
}
```

If your gateway uses a different header name for its key, add
`VDU_API_KEY_HEADER` with that name.

The API gateway in the Azure guide is on a private network too (internal mode),
so your computer needs a way into that network, such as a VPN.

### Why Claude Desktop cannot use the cluster's server directly

Claude Desktop adds remote servers as **custom connectors**: you give it an https
address, and it signs in with OAuth. There is no place to enter a fixed token,
which is what the cluster's server uses. So for Claude Desktop, use 5b.

Moving the cluster's server to OAuth is possible (the MCP SDK has the pieces),
and [docs/adr/0007-static-bearer-tokens.md](adr/0007-static-bearer-tokens.md)
records it as the upgrade path if people outside the team need to connect.

---

## 6. Every setting the server reads

**Where the system is:**

| Setting | What it does | Default |
| :--- | :--- | :--- |
| `VDU_API_URL` | The API's address. Can include a path, such as a gateway's `/ocr`. | `http://localhost:5000` |
| `VDU_API_KEY` | A key the gateway in front of the API wants. Sent with every call to the API, never anywhere else. | none |
| `VDU_API_KEY_HEADER` | The header the key goes in. | `Ocp-Apim-Subscription-Key` |

**What it may read:**

| Setting | What it does | Default |
| :--- | :--- | :--- |
| `VDU_ALLOWED_DIRS` | The only folders it reads files from. Paths are fully resolved first, so `..` tricks and shortcuts cannot escape. | the folder it was started in |
| `VDU_FETCH_URLS` | `off` turns web addresses off entirely; files still work. | on |
| `VDU_FETCH_ALLOWED_HOSTS` | If set, only these hosts (comma separated, `*.example.com` allowed). | any public host |
| `VDU_FETCH_ALLOW_HTTP` | Allow plain `http` addresses. | off (https only) |
| `VDU_FETCH_ALLOW_PRIVATE` | Allow addresses on private networks. For testing against a file server on your own computer only; never in a shared deployment. | off |

**Logging:**

| Setting | What it does | Default |
| :--- | :--- | :--- |
| `LOG_LEVEL` | How much it logs: `DEBUG`, `INFO`, `WARNING`. | `INFO` |
| `LOG_FORMAT` | `json` for one JSON object per line (what the cluster uses). | text |

**Only for the shared server over HTTP** (the cluster sets these for you):

| Setting | What it does |
| :--- | :--- |
| `MCP_BEARER_TOKENS` | The accepted tokens, comma separated. Read from the `ocr-mcp-secret` Secret in the cluster. |
| `MCP_BEARER_TOKEN` | A single token. The older name; both are read. |
| `MCP_HOST`, `MCP_PORT` | Where it listens. The cluster uses `0.0.0.0` and `8080`. |
| `MCP_ALLOWED_HOSTS` | Host names it answers to, when you want that check on. |

---

## 7. Rotating the deployed server's token

Tokens should change from time to time, and at once if one may have leaked. The
server accepts several at a time, so you can change it without cutting anyone
off. These steps were rehearsed on a test cluster.

```bash
# 1. Read the current token, and make a new one
OLD=$(kubectl get secret ocr-mcp-secret -o jsonpath='{.data.tokens}' | base64 -d)
NEW=$(openssl rand -base64 32)

# 2. Accept both, and restart the server so it reads the change
kubectl create secret generic ocr-mcp-secret --from-literal=tokens="$NEW,$OLD" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deploy/ocr-mcp-deployment
kubectl rollout status deploy/ocr-mcp-deployment

# 3. Give everyone the new token and let them update their assistants

# 4. Accept only the new one
kubectl create secret generic ocr-mcp-secret --from-literal=tokens="$NEW" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deploy/ocr-mcp-deployment
```

The first time, `kubectl apply` warns about a missing
`last-applied-configuration` annotation. That is harmless: it adds it and
carries on. The server's log confirms how many tokens it now accepts:

```bash
kubectl logs deploy/ocr-mcp-deployment | grep "bearer token"
```

```
"message": "bearer token authentication enabled (1 token accepted)"
```

---

## 8. When something does not work

| What you see | Likely cause | What to do |
| :--- | :--- | :--- |
| `claude mcp list` says the server failed | The path is wrong, or the install is broken | Run the full path with `--help` by hand. If it fails, reinstall (section 2). |
| The tools are listed, but every call fails | The API is not reachable at `VDU_API_URL` | `curl <VDU_API_URL>/health` should print nothing and succeed. The test stack's port is 15000, not 5000. |
| "is outside the allowed directories" | The file is not in `VDU_ALLOWED_DIRS` | Move the file there, or add its folder. |
| "the URL was refused" | The address is plain http, or leads to a private network | Use an https address on the public internet, or save the file into an allowed folder. |
| HTTP 401 from the cluster's server | Wrong or missing token | Check the token (section 5a), and that the header says `Bearer ` before it. |
| HTTP 401 or 403 from the gateway | The key is missing or wrong | Check `VDU_API_KEY`, and the header name if your gateway is not Azure's. |
| A document comes back instantly, and the worker did nothing | The result cache: the same file was read in the last day | Ask for a fresh reading ("read it again, fresh"). |
| Features in this guide are missing (no `fresh`, no `cached`) | The assistant is still starting an older copy | Update (section 2) and restart the assistant. |
| Claude Desktop does not show the server | The settings file has a mistake, or Desktop was not fully restarted | Check the JSON (every backslash doubled), quit Desktop fully, start it again, read `mcp.log`. |
