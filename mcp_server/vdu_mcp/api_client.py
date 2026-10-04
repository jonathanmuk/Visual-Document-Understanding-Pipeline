"""Thin client for the Rust producer API.

The MCP server never talks to Redis or the GPU pools directly. Everything goes
through the same HTTP API every other client uses, so the MCP layer inherits the
API's validation, its rate limiting at the gateway, and its metrics.

When the API sits behind a gateway that wants a key (Azure API Management wants
Ocp-Apim-Subscription-Key), set VDU_API_KEY, and VDU_API_KEY_HEADER if the
gateway uses a different header name. The key is sent to the API only, never to
a URL a document source points at.
"""
import asyncio
import os
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

import httpx2 as httpx

from . import urls

DEFAULT_API_URL = "http://localhost:5000"
DEFAULT_API_KEY_HEADER = "Ocp-Apim-Subscription-Key"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
FINAL_STATES = ("done", "failed")
REDIRECT_CODES = (301, 302, 303, 307, 308)


class ApiError(Exception):
    """The API answered with something other than success. Carries the status."""

    def __init__(self, status: int, message: str):
        super().__init__(f"API returned {status}: {message}")
        self.status = status
        self.message = message


@dataclass
class TaskStatus:
    task_id: str
    status: str
    attempts: int | None
    result: dict[str, Any] | None
    error: str | None
    warning: str | None
    callback_status: str | None = None

    @property
    def markdown(self) -> str:
        return (self.result or {}).get("markdown", "") or ""

    @property
    def layout(self) -> Any:
        return (self.result or {}).get("layout", [])

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "attempts": self.attempts,
            "markdown": self.markdown,
            "layout": self.layout,
            "error": self.error,
            "warning": self.warning,
        }


@dataclass
class Submission:
    task_id: str
    status: str
    cached: bool = False
    deduplicated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "status": self.status,
                "cached": self.cached, "deduplicated": self.deduplicated}


class ApiClient:
    def __init__(self, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 timeout: float = 60.0, api_key: str | None = None, api_key_header: str | None = None):
        self.base_url = (base_url or os.getenv("VDU_API_URL", DEFAULT_API_URL)).rstrip("/")
        self._transport = transport
        self._timeout = timeout
        self._api_key = api_key if api_key is not None else (os.getenv("VDU_API_KEY") or None)
        self._api_key_header = api_key_header or os.getenv("VDU_API_KEY_HEADER") or DEFAULT_API_KEY_HEADER

    @property
    def sends_api_key(self) -> bool:
        return bool(self._api_key)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, transport=self._transport, timeout=self._timeout)

    def _api_headers(self) -> dict[str, str]:
        # Added per API request rather than to the client, because the same
        # client class also fetches documents from arbitrary URLs.
        return {self._api_key_header: self._api_key} if self._api_key else {}

    async def submit(self, filename: str, content: bytes, fresh: bool = False) -> Submission:
        """Upload a document. Raises ApiError on rejection.

        The API answers 202 for a new task, 202 with deduplicated for an identical
        document already waiting, and 200 with cached for one already done.
        fresh asks it to process the document again regardless.
        """
        if len(content) > MAX_UPLOAD_BYTES:
            raise ApiError(413, f"document is {len(content)} bytes; the limit is {MAX_UPLOAD_BYTES}")
        headers = {"Cache-Control": "no-cache"} if fresh else {}
        headers.update(self._api_headers())
        async with self._client() as c:
            r = await c.post("/process", files={"file": (filename, content, "application/octet-stream")},
                             headers=headers)
        if r.status_code not in (200, 202):
            raise ApiError(r.status_code, r.text.strip())
        d = r.json()
        return Submission(task_id=d["task_id"], status=d.get("status", "queued"),
                          cached=bool(d.get("cached")), deduplicated=bool(d.get("deduplicated")))

    async def status(self, task_id: str) -> TaskStatus:
        async with self._client() as c:
            r = await c.get(f"/status/{task_id}", headers=self._api_headers())
        if r.status_code == 404:
            raise ApiError(404, f"no task with id {task_id}")
        if r.status_code != 200:
            raise ApiError(r.status_code, r.text.strip())
        d = r.json()
        return TaskStatus(
            task_id=d["task_id"], status=d["status"], attempts=d.get("attempts"),
            result=d.get("result"), error=d.get("error"), warning=d.get("warning"),
            callback_status=d.get("callback_status"),
        )

    async def wait(self, task_id: str, timeout_seconds: float, poll_seconds: float = 1.0,
                   on_progress: Callable[[TaskStatus, float], Awaitable[None]] | None = None) -> TaskStatus:
        """Poll until the task reaches a final state or the timeout passes."""
        started = time.monotonic()
        last_status = None
        while True:
            st = await self.status(task_id)
            elapsed = time.monotonic() - started
            if on_progress and (st.status != last_status or int(elapsed) % 5 == 0):
                await on_progress(st, elapsed)
            last_status = st.status
            if st.status in FINAL_STATES:
                return st
            if elapsed >= timeout_seconds:
                raise TimeoutError(
                    f"task {task_id} is still '{st.status}' after {int(elapsed)}s; "
                    f"check later with get_document_status"
                )
            await asyncio.sleep(poll_seconds)

    async def fetch_url(self, url: str, policy: urls.FetchPolicy) -> tuple[str, bytes]:
        """Download a document from a URL the policy allows, capped at the upload limit.

        Redirects are followed by hand so every hop is checked against the policy.
        Raises urls.UrlNotAllowed or ApiError.
        """
        async with self._client() as c:
            for _ in range(urls.MAX_REDIRECTS + 1):
                await urls.check(url, policy)
                async with c.stream("GET", url, follow_redirects=False) as r:
                    if r.status_code in REDIRECT_CODES:
                        location = r.headers.get("location")
                        if not location:
                            raise ApiError(r.status_code, f"{url} redirected without a Location header")
                        url = urllib.parse.urljoin(url, location)
                        continue
                    if r.status_code != 200:
                        raise ApiError(r.status_code, f"could not download {url}")
                    chunks, total = [], 0
                    async for chunk in r.aiter_bytes():
                        total += len(chunk)
                        if total > MAX_UPLOAD_BYTES:
                            raise ApiError(413, f"{url} is larger than the {MAX_UPLOAD_BYTES} byte limit")
                        chunks.append(chunk)
                name = url.rstrip("/").rsplit("/", 1)[-1].split("?")[0] or "document"
                return name, b"".join(chunks)
        raise ApiError(400, f"more than {urls.MAX_REDIRECTS} redirects")
