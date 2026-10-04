"""The API client on its own: gateway keys, gateway paths, and where the key goes."""
import httpx2 as httpx
import pytest

from vdu_mcp import urls
from vdu_mcp.api_client import ApiClient

PDF = b"%PDF-1.4\n%fake\n"


async def public_resolver(host, port):
    return ["93.184.215.14"]


def recording_client(seen, **kwargs):
    def handler(request):
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(202, json={"task_id": "t-1", "status": "queued"})
        if request.url.path.endswith("/doc.pdf"):
            return httpx.Response(200, content=PDF)
        return httpx.Response(200, json={"task_id": "t-1", "status": "queued", "attempts": 0})
    return ApiClient(transport=httpx.MockTransport(handler), **kwargs)


async def test_gateway_key_is_sent_on_uploads_and_status_checks():
    seen = []
    api = recording_client(seen, base_url="https://gateway.test/ocr", api_key="k-123")
    await api.submit("a.pdf", PDF)
    await api.status("t-1")
    assert [r.url.path for r in seen] == ["/ocr/process", "/ocr/status/t-1"], "the gateway's path prefix is kept"
    assert all(r.headers.get("ocp-apim-subscription-key") == "k-123" for r in seen)


async def test_gateway_key_is_never_sent_to_a_document_url():
    seen = []
    api = recording_client(seen, base_url="https://gateway.test/ocr", api_key="k-123")
    policy = urls.FetchPolicy(enabled=True, allow_http=False, allowed_hosts=[], allow_private=False,
                              resolver=public_resolver)
    await api.fetch_url("https://files.example.com/doc.pdf", policy)
    assert len(seen) == 1
    assert "ocp-apim-subscription-key" not in seen[0].headers, "a key must not leak to third-party hosts"


async def test_no_key_configured_means_no_header(monkeypatch):
    monkeypatch.delenv("VDU_API_KEY", raising=False)
    seen = []
    api = recording_client(seen, base_url="http://api.test")
    await api.submit("a.pdf", PDF, fresh=True)
    assert "ocp-apim-subscription-key" not in seen[0].headers
    assert seen[0].headers.get("cache-control") == "no-cache", "the fresh flag still works"
    assert api.sends_api_key is False


async def test_key_and_header_name_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("VDU_API_KEY", "env-key")
    monkeypatch.setenv("VDU_API_KEY_HEADER", "x-api-key")
    seen = []
    api = recording_client(seen, base_url="http://api.test")
    await api.status("t-1")
    assert seen[0].headers.get("x-api-key") == "env-key"
    assert "ocp-apim-subscription-key" not in seen[0].headers


@pytest.mark.parametrize("base", ["https://gateway.test/ocr", "https://gateway.test/ocr/"])
async def test_trailing_slash_on_the_gateway_address_makes_no_difference(base):
    seen = []
    api = recording_client(seen, base_url=base)
    await api.submit("a.pdf", PDF)
    assert seen[0].url.path == "/ocr/process"
