"""Drives the MCP server exactly as a host would, through the SDK's Client over
an in-memory transport. The Rust API is replaced by a fake that speaks its HTTP
contract, so these tests need no Redis, no containers, and no network.
"""
import json
import os
import uuid

import httpx2 as httpx
import pytest
from mcp import Client
from mcp.types import ElicitResult, TextContent

from vdu_mcp import schemas, server, urls
from vdu_mcp.api_client import ApiClient
from vdu_mcp.auth import BearerTokenMiddleware, tokens_from_env

PDF = b"%PDF-1.4\n%fake\n"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"

# Stands in for DNS. api.test is public; the others point inside the network.
ADDRESSES = {
    "api.test": ["93.184.215.14"],
    "internal.test": ["10.0.0.5"],
    "metadata.test": ["169.254.169.254"],
    "mixed.test": ["93.184.215.14", "192.168.1.10"],
}


async def fake_resolver(host, port):
    try:
        urls.ipaddress.ip_address(host)
        return [host]
    except ValueError:
        pass
    if host not in ADDRESSES:
        raise OSError("no such host")
    return ADDRESSES[host]


def make_policy(**overrides):
    kwargs = dict(enabled=True, allow_http=True, allowed_hosts=[], allow_private=False, resolver=fake_resolver)
    kwargs.update(overrides)
    return urls.FetchPolicy(**kwargs)


class FakeApi:
    """Behaves like the Rust API: validates uploads, stores tasks, advances status
    a configurable number of polls after submission."""

    def __init__(self, polls_until_done=1, outcome="done", warning=None):
        self.tasks = {}
        self.polls = {}
        self.polls_until_done = polls_until_done
        self.outcome = outcome
        self.warning = warning
        self.submissions = []
        self.headers = []
        self.cache = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/process":
            return self._process(request)
        if request.method == "GET" and path.startswith("/status/"):
            return self._status(path.rsplit("/", 1)[1])
        if request.method == "GET" and path == "/remote.pdf":
            return httpx.Response(200, content=PDF)
        if request.method == "GET" and path == "/huge.pdf":
            return httpx.Response(200, content=b"%PDF-" + b"x" * (11 * 1024 * 1024))
        if request.method == "GET" and path == "/moved.pdf":
            return httpx.Response(302, headers={"location": "/remote.pdf"})
        if request.method == "GET" and path == "/to-internal.pdf":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
        if request.method == "GET" and path == "/loop.pdf":
            return httpx.Response(302, headers={"location": "/loop.pdf"})
        return httpx.Response(404, text="nope")

    def _process(self, request):
        body = request.content
        # Minimal multipart parse: find the filename and the payload.
        if b'filename="' not in body:
            return httpx.Response(400, text="the 'file' field must be a file upload, not text (with curl, use file=@path)")
        filename = body.split(b'filename="', 1)[1].split(b'"', 1)[0].decode()
        payload = body.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n--", 1)[0]
        if not payload:
            return httpx.Response(400, text="the uploaded file is empty")
        if not (payload.startswith(b"%PDF-") or payload.startswith(b"\x89PNG") or payload[:3] == b"\xff\xd8\xff"):
            return httpx.Response(415, text="unsupported file type; send a PDF, PNG, or JPEG")
        self.headers.append(dict(request.headers))
        fresh = "no-cache" in request.headers.get("cache-control", "")
        if payload in self.cache and not fresh:
            return httpx.Response(200, json={"task_id": self.cache[payload], "status": "done", "cached": True})
        task_id = str(uuid.uuid4())
        self.tasks[task_id] = {"filename": filename, "bytes": payload}
        self.polls[task_id] = 0
        self.submissions.append((filename, payload))
        return httpx.Response(202, json={"task_id": task_id, "status": "queued"})

    def _status(self, task_id):
        if task_id not in self.tasks:
            return httpx.Response(404, text="Task ID not found")
        self.polls[task_id] += 1
        n = self.polls[task_id]
        base = {"task_id": task_id, "attempts": 1, "result": None, "error": None, "warning": None}
        if n < self.polls_until_done:
            return httpx.Response(200, json={**base, "status": "queued" if n == 1 else "processing"})
        if self.outcome == "failed":
            return httpx.Response(200, json={**base, "status": "failed", "error": "vLLM unreachable (gave up after 3 attempts)"})
        return httpx.Response(200, json={**base, "status": "done", "warning": self.warning,
                                          "result": {"markdown": f"# {self.tasks[task_id]['filename']}\n\nHello world",
                                                     "layout": [[{"label": "doc_title", "content": "x"}]]}})


@pytest.fixture
def fake(monkeypatch, tmp_path):
    api = FakeApi()
    server.set_api_client(ApiClient(base_url="http://api.test", transport=httpx.MockTransport(api.handler)))
    server.set_fetch_policy(make_policy())
    monkeypatch.setenv("VDU_ALLOWED_DIRS", str(tmp_path))
    (tmp_path / "invoice.pdf").write_bytes(PDF)
    (tmp_path / "scan.png").write_bytes(PNG)
    (tmp_path / "notes.txt").write_bytes(b"just text")
    api.dir = tmp_path
    return api


def text_of(result) -> str:
    return "".join(c.text for c in result.content if isinstance(c, TextContent))


# --- discovery -----------------------------------------------------------------

async def test_server_advertises_tools_resources_and_prompts(fake):
    async with Client(server.mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert set(tools) == {"read_document", "submit_document", "get_document_status", "extract_structured_data"}
        # Descriptions are for the model to read: they must say what and when.
        assert "Waits for the result" in tools["read_document"].description
        assert "submit_document" in tools["read_document"].description, "should say when to prefer the other tool"
        assert "source" in tools["read_document"].input_schema["properties"]
        assert tools["read_document"].input_schema["required"] == ["source"]

        resources = {r.uri.__str__() for r in (await client.list_resources()).resources}
        assert resources == {"vdu://schema/result", "vdu://reference/layout-labels"}

        templates = {t.uri_template for t in (await client.list_resource_templates()).resource_templates}
        assert templates == {"vdu://documents/{task_id}/markdown", "vdu://documents/{task_id}/layout"}

        prompts = {p.name for p in (await client.list_prompts()).prompts}
        assert prompts == {"extract_invoice", "summarise_document", "compare_documents"}


async def test_server_identity_and_instructions(fake):
    async with Client(server.mcp) as client:
        assert client.server_info.name == "visual-document-understanding"
        assert client.server_info.version == "0.6.0"
        assert "read_document" in (client.instructions or "")
        assert client.protocol_version is not None


# --- read_document ---------------------------------------------------------------

async def test_read_document_local_path_returns_markdown_and_layout(fake):
    async with Client(server.mcp) as client:
        res = await client.call_tool("read_document", {"source": str(fake.dir / "invoice.pdf")})
        assert not res.is_error, text_of(res)
        out = res.structured_content
        assert out["status"] == "done"
        assert out["markdown"].startswith("# invoice.pdf")
        assert out["layout"][0][0]["label"] == "doc_title"
        assert out["warning"] is None
        assert out["cached"] is False
        assert fake.submissions == [("invoice.pdf", PDF)], "exact bytes must be uploaded"


async def test_read_document_reports_progress_while_waiting(fake):
    fake.polls_until_done = 3
    seen = []

    async def on_progress(progress, total, message):
        seen.append((progress, total, message))

    async with Client(server.mcp) as client:
        res = await client.call_tool("read_document", {"source": str(fake.dir / "invoice.pdf"), "timeout_seconds": 30},
                                     progress_callback=on_progress)
        assert res.structured_content["status"] == "done"
    assert len(seen) >= 2, f"expected progress notifications, got {seen}"
    assert any("processing" in (m or "") for _, _, m in seen), seen
    assert seen[-1][2] == "done"


async def test_read_document_url_source(fake):
    async with Client(server.mcp) as client:
        res = await client.call_tool("read_document", {"source": "http://api.test/remote.pdf"})
        assert not res.is_error, text_of(res)
        assert fake.submissions[0][0] == "remote.pdf"


async def test_read_document_surfaces_failure_with_reason(fake):
    fake.outcome = "failed"
    async with Client(server.mcp) as client:
        res = await client.call_tool("read_document", {"source": str(fake.dir / "invoice.pdf")})
        assert res.is_error
        assert "vLLM unreachable" in text_of(res)


async def test_read_document_passes_warning_through(fake):
    fake.warning = "2 region(s) in this batch of 1 document(s) failed to transcribe"
    async with Client(server.mcp) as client:
        res = await client.call_tool("read_document", {"source": str(fake.dir / "invoice.pdf")})
        assert res.structured_content["warning"].startswith("2 region(s)")


async def test_read_document_times_out_with_a_useful_message(fake):
    fake.polls_until_done = 10_000
    async with Client(server.mcp) as client:
        res = await client.call_tool("read_document", {"source": str(fake.dir / "invoice.pdf"), "timeout_seconds": 10})
        assert res.is_error
        assert "get_document_status" in text_of(res)


# --- input guarding --------------------------------------------------------------

async def test_path_outside_allowed_dirs_is_refused_before_upload(fake, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp("elsewhere") / "secret.pdf"
    elsewhere.write_bytes(PDF)
    async with Client(server.mcp) as client:
        res = await client.call_tool("read_document", {"source": str(elsewhere)})
        assert res.is_error
        assert "outside the allowed directories" in text_of(res)
    assert fake.submissions == [], "nothing must reach the API"


async def test_traversal_out_of_allowed_dir_is_refused(fake, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "x.pdf"
    outside.write_bytes(PDF)
    sneaky = str(fake.dir / ".." / outside.parent.name / "x.pdf")
    async with Client(server.mcp) as client:
        res = await client.call_tool("read_document", {"source": sneaky})
        assert res.is_error
    assert fake.submissions == []


async def test_missing_file_is_a_clear_error(fake):
    async with Client(server.mcp) as client:
        res = await client.call_tool("read_document", {"source": str(fake.dir / "nope.pdf")})
        assert res.is_error
        assert "file not found" in text_of(res)


async def test_api_rejection_is_surfaced(fake):
    async with Client(server.mcp) as client:
        res = await client.call_tool("read_document", {"source": str(fake.dir / "notes.txt")})
        assert res.is_error
        assert "PDF, PNG, or JPEG" in text_of(res)


async def test_oversized_url_is_refused_before_upload(fake):
    async with Client(server.mcp) as client:
        res = await client.call_tool("read_document", {"source": "http://api.test/huge.pdf"})
        assert res.is_error
        assert "limit" in text_of(res)
    assert fake.submissions == []


# --- submit + status pair ----------------------------------------------------------

async def test_submit_then_status(fake):
    fake.polls_until_done = 2
    async with Client(server.mcp) as client:
        sub = await client.call_tool("submit_document", {"source": str(fake.dir / "scan.png")})
        assert not sub.is_error
        task_id = sub.structured_content["task_id"]
        assert sub.structured_content["status"] == "queued"

        first = await client.call_tool("get_document_status", {"task_id": task_id})
        assert first.structured_content["status"] == "queued"
        second = await client.call_tool("get_document_status", {"task_id": task_id})
        assert second.structured_content["status"] == "done"
        assert second.structured_content["markdown"].startswith("# scan.png")


async def test_status_of_unknown_task(fake):
    async with Client(server.mcp) as client:
        res = await client.call_tool("get_document_status", {"task_id": "00000000-0000-0000-0000-000000000000"})
        assert res.is_error
        assert "no task with id" in text_of(res)


# --- resources ------------------------------------------------------------------------

async def test_static_resources(fake):
    async with Client(server.mcp) as client:
        schema = json.loads((await client.read_resource("vdu://schema/result")).contents[0].text)
        assert schema["properties"]["status"]["enum"] == ["queued", "processing", "done", "failed"]
        labels = json.loads((await client.read_resource("vdu://reference/layout-labels")).contents[0].text)
        assert labels["labels"]["table"] == "table" and labels["labels"]["header"] == "abandon"
        assert labels["labels"]["chart"] == "chart", "charts are described, not skipped"
        assert "cached" in schema["properties"]


async def test_document_resources_by_task_id(fake):
    async with Client(server.mcp) as client:
        sub = await client.call_tool("submit_document", {"source": str(fake.dir / "invoice.pdf")})
        task_id = sub.structured_content["task_id"]
        md = (await client.read_resource(f"vdu://documents/{task_id}/markdown")).contents[0]
        assert md.mime_type == "text/markdown"
        assert md.text.startswith("# invoice.pdf")
        layout = json.loads((await client.read_resource(f"vdu://documents/{task_id}/layout")).contents[0].text)
        assert layout[0][0]["label"] == "doc_title"


async def test_document_resource_for_unfinished_task_explains(fake):
    fake.polls_until_done = 10
    async with Client(server.mcp) as client:
        sub = await client.call_tool("submit_document", {"source": str(fake.dir / "invoice.pdf")})
        task_id = sub.structured_content["task_id"]
        with pytest.raises(Exception) as excinfo:
            await client.read_resource(f"vdu://documents/{task_id}/markdown")
        assert "not finished" in str(excinfo.value)


# --- prompts --------------------------------------------------------------------------

async def test_prompts_render_with_arguments(fake):
    async with Client(server.mcp) as client:
        p = await client.get_prompt("extract_invoice", {"document": "/docs/inv.pdf", "currency": "EUR"})
        text = p.messages[0].content.text
        assert "extract_structured_data" in text and "'/docs/inv.pdf'" in text and "EUR" in text

        p = await client.get_prompt("summarise_document", {"document": "a.pdf", "length": "long"})
        assert "long summary" in p.messages[0].content.text

        p = await client.get_prompt("compare_documents", {"document_a": "a.pdf", "document_b": "b.pdf"})
        assert "'a.pdf'" in p.messages[0].content.text and "'b.pdf'" in p.messages[0].content.text


# --- invoices in any currency ------------------------------------------------------------

def test_money_schemas_never_assume_dollars():
    for kind in ("invoice", "receipt"):
        props = schemas.EXTRACTION_SCHEMAS[kind]["properties"]
        assert "null" in props["currency"]["type"], f"{kind}: an unclear currency must be allowed to stay null"
        assert "Never assume USD" in props["currency"]["description"]
        assert "currency" in schemas.EXTRACTION_SCHEMAS[kind]["required"], f"{kind}: the currency must always be stated"
        assert "currency_as_printed" in props
        assert "never converted" in props["total"]["description"]
        assert "1.234,56" in props["total"]["description"]
    line = schemas.EXTRACTION_SCHEMAS["invoice"]["properties"]["line_items"]["items"]["properties"]
    assert "never converted" in line["unit_price"]["description"]


async def test_extraction_instruction_keeps_the_documents_currency(fake):
    async with Client(server.mcp) as client:
        res = await client.call_tool("extract_structured_data",
                                     {"source": str(fake.dir / "invoice.pdf"), "document_type": "invoice"})
        assert not res.is_error, text_of(res)
        instruction = res.structured_content["instruction"]
        assert "never convert it" in instruction
        assert "1.234,56" in instruction and "1234.56" in instruction
        assert "never assume US dollars" in instruction


async def test_invoice_prompt_lets_the_document_win_over_an_expected_currency(fake):
    async with Client(server.mcp) as client:
        expected = (await client.get_prompt("extract_invoice", {"document": "inv.pdf", "currency": "USD"})).messages[0].content.text
        assert "The amounts are in USD" not in expected, "an expected currency must not override the document"
        assert "If the document uses a different currency" in expected
        assert "never convert them" in expected

        detect = (await client.get_prompt("extract_invoice", {"document": "inv.pdf"})).messages[0].content.text
        assert "reply with only the JSON" in detect and "never convert them" in detect


# --- extract_structured_data and elicitation ------------------------------------------

async def test_extract_with_explicit_type_does_not_elicit(fake):
    asked = []

    async def on_elicit(context, params):
        asked.append(params.message)
        return ElicitResult(action="accept", content={"document_type": "receipt"})

    async with Client(server.mcp, elicitation_callback=on_elicit) as client:
        res = await client.call_tool("extract_structured_data",
                                     {"source": str(fake.dir / "invoice.pdf"), "document_type": "invoice"})
        assert not res.is_error, text_of(res)
        out = res.structured_content
        assert out["document_type"] == "invoice"
        assert "invoice_number" in out["schema"]["properties"]
        assert out["document_markdown"].startswith("# invoice.pdf")
        assert "Do not invent" in out["instruction"]
    assert asked == [], "an explicit document_type must not trigger a question"


async def test_extract_without_type_asks_the_user(fake):
    asked = []

    async def on_elicit(context, params):
        asked.append(params.message)
        return ElicitResult(action="accept", content={"document_type": "contract"})

    async with Client(server.mcp, elicitation_callback=on_elicit) as client:
        res = await client.call_tool("extract_structured_data", {"source": str(fake.dir / "invoice.pdf")})
        assert not res.is_error, text_of(res)
        assert res.structured_content["document_type"] == "contract"
        assert "parties" in res.structured_content["schema"]["properties"]
    assert len(asked) == 1 and "Which kind of document" in asked[0]


async def test_extract_declined_elicitation_does_not_upload(fake):
    async def on_elicit(context, params):
        return ElicitResult(action="decline")

    async with Client(server.mcp, elicitation_callback=on_elicit) as client:
        res = await client.call_tool("extract_structured_data", {"source": str(fake.dir / "invoice.pdf")})
        assert res.is_error
        assert "cancelled" in text_of(res)
    assert fake.submissions == []


async def test_extract_with_custom_schema(fake):
    custom = {"type": "object", "properties": {"po_number": {"type": "string"}}}
    async with Client(server.mcp) as client:
        res = await client.call_tool("extract_structured_data",
                                     {"source": str(fake.dir / "invoice.pdf"), "schema": custom})
        assert not res.is_error, text_of(res)
        assert res.structured_content["document_type"] == "custom"
        assert res.structured_content["schema"]["properties"] == {"po_number": {"type": "string"}}


async def test_extract_rejects_a_schema_that_is_not_an_object_schema(fake):
    async with Client(server.mcp) as client:
        res = await client.call_tool("extract_structured_data",
                                     {"source": str(fake.dir / "invoice.pdf"), "schema": {"type": "string"}})
        assert res.is_error
        assert "type 'object'" in text_of(res)
    assert fake.submissions == []


# --- the result cache ------------------------------------------------------------

async def test_identical_document_is_answered_from_the_cache(fake):
    async with Client(server.mcp) as client:
        first = await client.call_tool("read_document", {"source": str(fake.dir / "invoice.pdf")})
        fake.cache[PDF] = first.structured_content["task_id"]
        again = await client.call_tool("read_document", {"source": str(fake.dir / "invoice.pdf")})
        assert not again.is_error, text_of(again)
        assert again.structured_content["cached"] is True
        assert again.structured_content["task_id"] == first.structured_content["task_id"]
        assert again.structured_content["markdown"].startswith("# invoice.pdf")
    assert len(fake.submissions) == 1, "the second read did not create a task"


async def test_fresh_asks_the_api_to_process_again(fake):
    async with Client(server.mcp) as client:
        first = await client.call_tool("submit_document", {"source": str(fake.dir / "invoice.pdf")})
        fake.cache[PDF] = first.structured_content["task_id"]
        cached = await client.call_tool("submit_document", {"source": str(fake.dir / "invoice.pdf")})
        assert cached.structured_content == {"task_id": first.structured_content["task_id"], "status": "done",
                                             "cached": True, "deduplicated": False}
        fresh = await client.call_tool("submit_document", {"source": str(fake.dir / "invoice.pdf"), "fresh": True})
        assert fresh.structured_content["cached"] is False
        assert fresh.structured_content["task_id"] != first.structured_content["task_id"]
    assert fake.headers[-1].get("cache-control") == "no-cache"
    assert "cache-control" not in fake.headers[0]


# --- URL sources: the fetch policy -------------------------------------------------

async def call_url(url):
    async with Client(server.mcp) as client:
        return await client.call_tool("read_document", {"source": url})


async def test_private_address_is_refused_before_any_request(fake):
    for url in ("http://internal.test/doc.pdf", "http://10.1.2.3/doc.pdf", "http://127.0.0.1:6379/",
                "http://metadata.test/latest/", "http://[::1]/doc.pdf", "http://mixed.test/doc.pdf"):
        res = await call_url(url)
        assert res.is_error, url
        assert "not a public address" in text_of(res), (url, text_of(res))
    assert fake.submissions == []


async def test_redirect_to_an_internal_address_is_refused(fake):
    res = await call_url("http://api.test/to-internal.pdf")
    assert res.is_error
    assert "169.254.169.254" in text_of(res) and "not a public address" in text_of(res)
    assert fake.submissions == []


async def test_safe_redirect_is_followed(fake):
    res = await call_url("http://api.test/moved.pdf")
    assert not res.is_error, text_of(res)
    assert fake.submissions[0][0] == "remote.pdf"


async def test_redirect_loop_stops(fake):
    res = await call_url("http://api.test/loop.pdf")
    assert res.is_error
    assert "redirects" in text_of(res)


async def test_http_is_refused_by_default(fake):
    server.set_fetch_policy(make_policy(allow_http=False))
    res = await call_url("http://api.test/remote.pdf")
    assert res.is_error and "only https" in text_of(res)


async def test_host_allowlist(fake):
    server.set_fetch_policy(make_policy(allowed_hosts=["docs.example.com"]))
    res = await call_url("http://api.test/remote.pdf")
    assert res.is_error and "allowed hosts" in text_of(res)


async def test_url_sources_can_be_turned_off(fake):
    server.set_fetch_policy(make_policy(enabled=False))
    res = await call_url("http://api.test/remote.pdf")
    assert res.is_error and "turned off" in text_of(res)
    ok = await call_url(str(fake.dir / "invoice.pdf"))
    assert not ok.is_error, "local paths still work"


def test_policy_defaults_are_strict(monkeypatch):
    for name in ("VDU_FETCH_URLS", "VDU_FETCH_ALLOW_HTTP", "VDU_FETCH_ALLOWED_HOSTS", "VDU_FETCH_ALLOW_PRIVATE"):
        monkeypatch.delenv(name, raising=False)
    p = urls.FetchPolicy()
    assert p.enabled and not p.allow_http and not p.allow_private and p.allowed_hosts == []


def test_public_address_rules():
    assert urls.is_public("93.184.215.14")
    for addr in ("10.0.0.1", "172.16.0.1", "192.168.0.1", "127.0.0.1", "169.254.169.254",
                 "100.64.0.1", "0.0.0.0", "::1", "fe80::1", "fd00::1", "::ffff:10.0.0.1", "224.0.0.1"):
        assert not urls.is_public(addr), addr


# --- bearer tokens and rotation --------------------------------------------------------

def test_tokens_from_env_combines_both_settings():
    assert tokens_from_env("", "") == []
    assert tokens_from_env("old", "") == ["old"]
    assert tokens_from_env("", "new, old ,") == ["new", "old"]
    assert tokens_from_env("old", "new,old") == ["new", "old"]


async def _status_for(middleware, header):
    sent = {}

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        if message["type"] == "http.response.start":
            sent["status"] = message["status"]

    headers = [(b"authorization", header)] if header is not None else []
    await middleware({"type": "http", "path": "/mcp", "headers": headers}, receive, send)
    return sent["status"]


async def test_any_listed_token_is_accepted_during_rotation():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = BearerTokenMiddleware(app, tokens=["new-token", "old-token"])
    assert await _status_for(mw, b"Bearer new-token") == 200
    assert await _status_for(mw, b"Bearer old-token") == 200
    assert await _status_for(mw, b"Bearer other") == 401
    assert await _status_for(mw, b"new-token") == 401, "the Bearer scheme is required"
    assert await _status_for(mw, None) == 401
