"""Exercise every MCP capability and print what comes back.

This is what an AI assistant does when it talks to the server, written out so
you can watch it happen. Run it against the compose stack with the demo worker.

    python tools/try_mcp.py                 all of it
    python tools/try_mcp.py discovery       just one section
    python tools/try_mcp.py --list          section names
"""
import asyncio
import json
import os
import sys
import time

import httpx2 as httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import ElicitResult, TextContent

MCP_URL = os.getenv("MCP_URL", "http://127.0.0.1:18080/mcp")
TOKEN = os.getenv("MCP_BEARER_TOKEN", "smoke-test-token")
DOC = os.getenv("DEMO_DOC", "/fixtures/sample.pdf")


def rule(title):
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def text_of(res):
    return "".join(c.text for c in res.content if isinstance(c, TextContent))


def show(res, label="result"):
    if res.is_error:
        print(f"  ERROR: {text_of(res)}")
    elif res.structured_content is not None:
        print(f"  {label}: {json.dumps(res.structured_content, indent=2)[:1200]}")
    else:
        print(f"  {label}: {text_of(res)[:1200]}")


async def discovery(client):
    rule("1. DISCOVERY: what the assistant learns before doing anything")
    print(f"server      : {client.server_info.name} v{client.server_info.version}")
    print(f"protocol    : {client.protocol_version}")
    print(f"instructions: {(client.instructions or '').strip().splitlines()[0]} ...")

    print("\nTOOLS (the model chooses these):")
    for t in (await client.list_tools()).tools:
        first = (t.description or "").strip().splitlines()[0]
        req = t.input_schema.get("required", [])
        print(f"  - {t.name}({', '.join(req)})\n      {first}")

    print("\nRESOURCES (the application reads these):")
    for r in (await client.list_resources()).resources:
        print(f"  - {r.uri}  [{r.mime_type}]")
    for t in (await client.list_resource_templates()).resource_templates:
        print(f"  - {t.uri_template}  (template)")

    print("\nPROMPTS (you choose these, as slash commands):")
    for p in (await client.list_prompts()).prompts:
        args = ", ".join(a.name + ("" if a.required else "?") for a in (p.arguments or []))
        print(f"  - /{p.name}({args})  {p.description}")


async def read(client):
    rule("2. read_document: the main tool, with live progress")
    seen = []

    async def on_progress(progress, total, message):
        seen.append(message)
        print(f"  progress: {progress:>5.1f}/{total}  {message}")

    res = await client.call_tool("read_document", {"source": DOC, "timeout_seconds": 60},
                                 progress_callback=on_progress)
    if res.is_error:
        print(f"  ERROR: {text_of(res)}")
        return None
    out = res.structured_content
    print(f"\n  status   : {out['status']}")
    print(f"  cached   : {out['cached']}")
    print(f"  attempts : {out['attempts']}")
    print(f"  warning  : {out['warning']}")
    print(f"  markdown : {len(out['markdown'])} chars, first lines:")
    for line in out["markdown"].splitlines()[:6]:
        print(f"             {line}")
    print(f"  layout   : {len(out['layout'])} page(s), "
          f"labels on page 1: {[r['label'] for r in out['layout'][0]]}")
    print(f"\n  ({len(seen)} progress notifications arrived while it worked)")
    return out


async def cache(client):
    rule("2b. THE RESULT CACHE: the same document again, then fresh")
    for label, args in (("same document again", {"source": DOC, "timeout_seconds": 60}),
                        ("same document, fresh=true", {"source": DOC, "timeout_seconds": 60, "fresh": True})):
        t0 = time.perf_counter()
        res = await client.call_tool("read_document", args)
        took = time.perf_counter() - t0
        if res.is_error:
            print(f"  {label}: ERROR: {text_of(res)}")
            continue
        out = res.structured_content
        print(f"  {label:<27}: cached={out['cached']!s:<5}  took {took:4.1f}s  task {out['task_id'][:8]}...")
    print("\n  A cached answer skips the queue and the GPU entirely. fresh=true processes it again.")


async def submit_poll(client):
    rule("3. submit_document + get_document_status: the fire-and-poll pair")
    res = await client.call_tool("submit_document", {"source": DOC})
    show(res, "submitted")
    if res.is_error:
        return
    task_id = res.structured_content["task_id"]
    for i in range(20):
        st = await client.call_tool("get_document_status", {"task_id": task_id})
        s = st.structured_content
        print(f"  poll {i + 1}: status={s['status']} attempts={s['attempts']}")
        if s["status"] in ("done", "failed"):
            break
        await asyncio.sleep(2)
    return task_id


async def resources(client, task_id):
    rule("4. RESOURCES: reference data, and finished documents by id")
    schema = json.loads((await client.read_resource("vdu://schema/result")).contents[0].text)
    print(f"  vdu://schema/result -> fields: {list(schema['properties'])}")
    labels = json.loads((await client.read_resource("vdu://reference/layout-labels")).contents[0].text)
    kept = [k for k, v in labels["labels"].items() if v != "abandon"]
    dropped = [k for k, v in labels["labels"].items() if v == "abandon"]
    print(f"  vdu://reference/layout-labels -> {len(kept)} kept, {len(dropped)} discarded")
    print(f"     discarded: {', '.join(dropped)}")
    if task_id:
        md = (await client.read_resource(f"vdu://documents/{task_id}/markdown")).contents[0]
        print(f"  vdu://documents/{task_id[:8]}.../markdown -> [{md.mime_type}] {len(md.text)} chars")
        lay = (await client.read_resource(f"vdu://documents/{task_id}/layout")).contents[0]
        print(f"  vdu://documents/{task_id[:8]}.../layout   -> [{lay.mime_type}] {len(lay.text)} chars")


async def prompts(client):
    rule("5. PROMPTS: what a slash command expands into")
    for name, args in (("extract_invoice", {"document": DOC, "currency": "USD"}),
                       ("summarise_document", {"document": DOC, "length": "short"}),
                       ("compare_documents", {"document_a": DOC, "document_b": "/fixtures/sample.png"})):
        p = await client.get_prompt(name, args)
        print(f"\n  /{name} becomes:")
        for line in p.messages[0].content.text.splitlines():
            print(f"     {line}")


async def extraction(client):
    rule("6. extract_structured_data: with the type given (no question asked)")
    res = await client.call_tool("extract_structured_data",
                                 {"source": DOC, "document_type": "invoice", "timeout_seconds": 60})
    if res.is_error:
        print(f"  ERROR: {text_of(res)}")
        return
    out = res.structured_content
    print(f"  document_type: {out['document_type']}")
    print(f"  schema fields: {list(out['schema']['properties'])}")
    print(f"  required     : {out['schema']['required']}")
    print(f"  markdown     : {len(out['document_markdown'])} chars handed to the model")
    print(f"  instruction  : {out['instruction']}")
    print("\n  The assistant now fills that schema from the text itself.")


async def elicitation(client_factory):
    rule("7. ELICITATION: the server asks YOU a question")
    asked = []

    async def on_elicit(context, params):
        asked.append(params.message)
        print(f"  SERVER ASKS: {params.message}")
        print(f"  (the host shows a form built from: {list(params.requested_schema['properties'])})")
        print("  answering 'invoice' ...")
        return ElicitResult(action="accept", content={"document_type": "invoice"})

    async with client_factory(on_elicit) as client:
        res = await client.call_tool("extract_structured_data", {"source": DOC, "timeout_seconds": 60})
        if res.is_error:
            print(f"  ERROR: {text_of(res)}")
            return
        print(f"  -> proceeded with document_type={res.structured_content['document_type']}")
    print(f"\n  ({len(asked)} question asked. With document_type given, it asks nothing.)")


async def guards(client):
    rule("8. GUARDS: what the server refuses, and how clearly")
    cases = [
        ("a path outside the allowed folder", "read_document", {"source": "/etc/hostname"}),
        ("a file that does not exist", "read_document", {"source": "/fixtures/nope.pdf"}),
        ("something that is not a document", "read_document", {"source": "/fixtures/README.md"}),
        ("an unknown task id", "get_document_status", {"task_id": "00000000-0000-0000-0000-000000000000"}),
        ("a schema that is not an object", "extract_structured_data",
         {"source": DOC, "schema": {"type": "string"}}),
        ("a URL that points inside the network", "read_document", {"source": "https://redis:6379/"}),
        ("a plain http URL", "read_document", {"source": "http://example.com/doc.pdf"}),
    ]
    for label, tool, args in cases:
        res = await client.call_tool(tool, args)
        mark = "refused" if res.is_error else "ACCEPTED (unexpected)"
        print(f"  {label}:\n     {mark}: {text_of(res)}")


async def auth():
    rule("9. AUTHENTICATION on the HTTP transport")
    async with httpx.AsyncClient() as plain:
        r = await plain.post(MCP_URL, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                             headers={"accept": "application/json, text/event-stream"})
    print(f"  without a token: HTTP {r.status_code}  {r.headers.get('www-authenticate', '')}")
    print(f"  body: {r.text.strip()[:200]}")
    print("  with the token : every call in this script succeeded")


SECTIONS = ["discovery", "read", "cache", "submit", "resources", "prompts", "extraction", "elicitation", "guards",
            "auth"]


async def main():
    # Print UTF-8 even when the output is piped, as in Git Bash on Windows, so a
    # euro sign or any other character in a document shows correctly instead of
    # garbling or stopping the script.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    wanted = [a for a in sys.argv[1:] if not a.startswith("-")] or SECTIONS
    if "--list" in sys.argv:
        print("sections:", ", ".join(SECTIONS))
        return

    def factory(elicit_cb=None):
        c = httpx.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"}, timeout=120)
        return Client(streamable_http_client(MCP_URL, http_client=c), elicitation_callback=elicit_cb)

    task_id = None
    async with factory() as client:
        if "discovery" in wanted:
            await discovery(client)
        if "read" in wanted:
            await read(client)
        if "cache" in wanted:
            await cache(client)
        if "submit" in wanted:
            task_id = await submit_poll(client)
        if "resources" in wanted:
            await resources(client, task_id)
        if "prompts" in wanted:
            await prompts(client)
        if "extraction" in wanted:
            await extraction(client)
    if "elicitation" in wanted:
        await elicitation(factory)
    async with factory() as client:
        if "guards" in wanted:
            await guards(client)
    if "auth" in wanted:
        await auth()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
