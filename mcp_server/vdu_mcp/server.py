"""The Visual Document Understanding Pipeline MCP server.

Exposes the document pipeline to any MCP host through the three primitives:

    tools      read_document, submit_document, get_document_status,
               extract_structured_data
    resources  vdu://schema/result, vdu://reference/layout-labels,
               vdu://documents/{task_id}/markdown, vdu://documents/{task_id}/layout
    prompts    extract_invoice, summarise_document, compare_documents

It is a thin front door. Every document still goes through the Rust API, the
queue, the T4 worker, and vLLM. This process knows nothing about models.
"""
import json
import logging
import os
import time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from mcp.server.mcpserver import (
    AcceptedElicitation,
    CancelledElicitation,
    Context,
    DeclinedElicitation,
    Elicit,
    ElicitationResult,
    MCPServer,
    Resolve,
)
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.server.mcpserver.prompts.base import Message, UserMessage

from . import schemas, urls
from .api_client import ApiClient, ApiError, Submission, TaskStatus
from .paths import PathNotAllowed, resolve_allowed

log = logging.getLogger("vdu_mcp")

SERVER_VERSION = "0.6.0"
DEFAULT_WAIT_SECONDS = 300

# How money is read, for every extraction. Invoices come in every currency and
# number format; the document always wins over any assumption.
MONEY_RULES = (
    "Keep every amount in the currency the document uses; never convert it. "
    "Read numbers with the document's own separators: 1.234,56 and 1 234,56 are 1234.56, "
    "as is 1,234.56. Name the currency with its ISO 4217 code only when the document makes "
    "it clear, copy the symbol exactly as printed, and never assume US dollars."
)

INSTRUCTIONS = """\
This server reads documents: PDFs, PNGs, and JPEGs. It returns the document as
Markdown in reading order, with tables as Markdown tables and formulas as LaTeX,
plus a layout describing every region found on each page.

Use read_document for most documents; it waits for the result. Use
submit_document and get_document_status for very large documents when you want
to do other work while it processes. Use extract_structured_data when you need
specific fields (an invoice total, a contract's parties) rather than the whole
text.

A result with status "failed" carries the reason in "error". A result with a
"warning" finished, but some regions could not be transcribed, so treat it as
possibly incomplete. A result with "cached": true is the stored result of an
identical document read recently; pass fresh=true to read it again.
"""

mcp = MCPServer(
    "visual-document-understanding",
    title="Visual Document Understanding Pipeline",
    instructions=INSTRUCTIONS,
    version=SERVER_VERSION,
)

# One client and one URL policy per process. Tests replace both.
api = ApiClient()
fetch_policy = urls.FetchPolicy()


def set_api_client(client: ApiClient) -> None:
    global api
    api = client


def set_fetch_policy(policy: urls.FetchPolicy) -> None:
    global fetch_policy
    fetch_policy = policy


# --------------------------------------------------------------------------- helpers

async def load_source(source: str) -> tuple[str, bytes]:
    """Turn a local path or an http(s) URL into (filename, bytes)."""
    if source.startswith(("http://", "https://")):
        try:
            return await api.fetch_url(source, fetch_policy)
        except urls.UrlNotAllowed as e:
            raise ToolError(f"the URL was refused: {e}")
        except ApiError as e:
            raise ToolError(e.message)
    try:
        path = resolve_allowed(source)
    except PathNotAllowed as e:
        raise ToolError(str(e))
    return path.name, path.read_bytes()


async def submit_source(source: str, fresh: bool = False) -> Submission:
    filename, content = await load_source(source)
    try:
        sub = await api.submit(filename, content, fresh=fresh)
    except ApiError as e:
        raise ToolError(f"the document was rejected: {e.message}")
    log.info(json.dumps({"event": "submitted", "task_id": sub.task_id, "filename": filename,
                         "bytes": len(content), "cached": sub.cached, "deduplicated": sub.deduplicated}))
    return sub


async def wait_with_progress(task_id: str, timeout_seconds: int, ctx: Context) -> TaskStatus:
    started = time.monotonic()

    async def on_progress(st: TaskStatus, elapsed: float) -> None:
        # notifications/progress: still part of the protocol, flows on this
        # request's own response stream.
        await ctx.report_progress(
            progress=min(elapsed, timeout_seconds), total=timeout_seconds,
            message=f"{st.status} (attempt {st.attempts or 0}), {int(elapsed)}s",
        )

    try:
        st = await api.wait(task_id, timeout_seconds, on_progress=on_progress)
    except TimeoutError as e:
        raise ToolError(str(e))
    await ctx.report_progress(progress=timeout_seconds, total=timeout_seconds, message=st.status)
    log.info(json.dumps({"event": "finished", "task_id": task_id, "status": st.status,
                         "seconds": round(time.monotonic() - started, 1), "warning": bool(st.warning)}))
    return st


def finished_or_raise(st: TaskStatus, sub: Submission) -> dict[str, Any]:
    if st.status == "failed":
        raise ToolError(f"the document could not be processed: {st.error}")
    return {**st.as_dict(), "cached": sub.cached}


# --------------------------------------------------------------------------- tools

@mcp.tool()
async def read_document(
    source: Annotated[str, Field(description=(
        "A local file path, or an http(s) URL. PDF, PNG, or JPEG, up to 10 MB. "
        "Local paths must be inside the server's allowed directories."))],
    timeout_seconds: Annotated[int, Field(ge=10, le=1800, description=(
        "How long to wait for the result before giving up. Default 300."))] = DEFAULT_WAIT_SECONDS,
    fresh: Annotated[bool, Field(description=(
        "Process the document again even if an identical one was read recently. "
        "Default false: a recent identical document returns its stored result at once."))] = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Read a document and return its full text and layout. Waits for the result.

    Returns the document as Markdown in reading order (tables as Markdown tables,
    formulas as LaTeX, charts as a written description starting "Chart:"), plus a
    per-page layout listing every region found with its label and position.
    Photos and other images appear in the layout with their position but are
    not transcribed.

    Use this for ordinary documents. For a very large document where you want to
    keep working meanwhile, use submit_document and get_document_status instead.

    Raises an error if the document is rejected (not a PDF/PNG/JPEG, over 10 MB,
    or outside the allowed directories), if processing fails, or if it is not
    finished within timeout_seconds. A result with a "warning" finished but may
    be missing some regions.
    """
    sub = await submit_source(source, fresh)
    st = await wait_with_progress(sub.task_id, timeout_seconds, ctx)
    return finished_or_raise(st, sub)


@mcp.tool()
async def submit_document(
    source: Annotated[str, Field(description="A local file path or an http(s) URL. PDF, PNG, or JPEG, up to 10 MB.")],
    fresh: Annotated[bool, Field(description=(
        "Process the document again even if an identical one was read recently. "
        "Default false: a recent identical document returns its stored result at once."))] = False,
) -> dict[str, Any]:
    """Submit a document for reading and return immediately with a task_id.

    Does not wait. Use get_document_status with the returned task_id to check
    progress and fetch the result. Prefer read_document unless the document is
    large or you have other work to do while it processes. status is "done" at
    once, with cached true, when an identical document was read recently.
    """
    sub = await submit_source(source, fresh)
    return sub.as_dict()


@mcp.tool()
async def get_document_status(
    task_id: Annotated[str, Field(description="The task_id returned by submit_document or read_document.")],
) -> dict[str, Any]:
    """Check on a submitted document. Returns its status and, once done, the result.

    status is one of: queued (waiting for a worker), processing (a worker has it),
    done (result available in markdown and layout), failed (see error). A task
    that fails once may be retried automatically; attempts shows how many tries
    it has had. Results expire after a day.
    """
    try:
        st = await api.status(task_id)
    except ApiError as e:
        raise ToolError(e.message)
    return st.as_dict()


class DocumentTypeChoice(BaseModel):
    document_type: Literal["invoice", "receipt", "contract", "generic"] = Field(
        description="What kind of document this is. Choose 'generic' if none fit.")


async def choose_document_type(document_type: str | None = None, schema: dict[str, Any] | None = None) -> DocumentTypeChoice | Elicit[DocumentTypeChoice]:
    """Resolver: ask the user which kind of document it is, only when nothing told us."""
    if schema:
        return DocumentTypeChoice(document_type="generic")
    if document_type in schemas.EXTRACTION_SCHEMAS:
        return DocumentTypeChoice(document_type=document_type)
    return Elicit(
        "Which kind of document is this? The answer decides which fields to extract.",
        DocumentTypeChoice,
    )


@mcp.tool()
async def extract_structured_data(
    source: Annotated[str, Field(description="A local file path or an http(s) URL. PDF, PNG, or JPEG, up to 10 MB.")],
    document_type: Annotated[str | None, Field(description=(
        "One of: invoice, receipt, contract, generic. Selects a built-in schema. "
        "Leave empty to be asked, or supply schema_json instead."))] = None,
    schema: Annotated[dict[str, Any] | None, Field(description=(
        "A JSON Schema object describing the fields you want. Overrides document_type."))] = None,
    choice: Annotated[ElicitationResult[DocumentTypeChoice], Resolve(choose_document_type)] = None,
    timeout_seconds: Annotated[int, Field(ge=10, le=1800)] = DEFAULT_WAIT_SECONDS,
    fresh: Annotated[bool, Field(description=(
        "Process the document again even if an identical one was read recently. "
        "Default false: a recent identical document returns its stored result at once."))] = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Read a document and return its text together with the schema of fields to extract.

    Give a document_type (invoice, receipt, contract, generic) or your own
    schema. If you give neither, the user is asked which kind of document it is.

    The result contains the document's Markdown and the target schema. Fill the
    schema from the Markdown yourself and answer with JSON that matches it; this
    server does not run a language model. Amounts should be numbers in the
    document's own currency, never converted, read with the document's own
    separators (1.234,56 is 1234.56); dates in YYYY-MM-DD. Name the currency only
    when the document makes it clear; never assume US dollars. Use null for fields
    the document does not contain rather than guessing.
    """
    match choice:
        case AcceptedElicitation(data=DocumentTypeChoice(document_type=chosen)):
            pass
        case DeclinedElicitation():
            raise ToolError("no document type chosen; extraction cancelled")
        case CancelledElicitation():
            raise ToolError("extraction cancelled")
        case _:
            chosen = "generic"

    if schema:
        if schema.get("type") != "object" or "properties" not in schema:
            raise ToolError("schema must be a JSON Schema object with type 'object' and 'properties'")
        chosen = "custom"
    else:
        schema = schemas.EXTRACTION_SCHEMAS[chosen]

    sub = await submit_source(source, fresh)
    st = await wait_with_progress(sub.task_id, timeout_seconds, ctx)
    result = finished_or_raise(st, sub)
    return {
        "task_id": sub.task_id,
        "document_type": chosen,
        "schema": schema,
        "document_markdown": result["markdown"],
        "warning": result["warning"],
        "cached": result["cached"],
        "instruction": (
            "Fill the schema from document_markdown. Answer with a single JSON object "
            "that validates against the schema. Use null for anything the document does "
            "not state. Do not invent values. " + MONEY_RULES
        ),
    }


# --------------------------------------------------------------------------- resources

@mcp.resource("vdu://schema/result", name="result-schema", mime_type="application/json",
              description="JSON Schema of what read_document and get_document_status return.")
def result_schema() -> str:
    return json.dumps(schemas.RESULT_SCHEMA, indent=2)


@mcp.resource("vdu://reference/layout-labels", name="layout-labels", mime_type="application/json",
              description="Every region label the layout model can produce, and what the pipeline does with each.")
def layout_labels() -> str:
    return json.dumps(schemas.LAYOUT_LABELS, indent=2)


@mcp.resource("vdu://documents/{task_id}/markdown", name="document-markdown", mime_type="text/markdown",
              description="The Markdown of a finished document, by task_id.")
async def document_markdown(task_id: str) -> str:
    st = await _finished(task_id)
    return st.markdown


@mcp.resource("vdu://documents/{task_id}/layout", name="document-layout", mime_type="application/json",
              description="The per-page layout of a finished document, by task_id.")
async def document_layout(task_id: str) -> str:
    st = await _finished(task_id)
    return json.dumps(st.layout)


async def _finished(task_id: str) -> TaskStatus:
    try:
        st = await api.status(task_id)
    except ApiError as e:
        raise ResourceError(e.message)
    if st.status == "failed":
        raise ResourceError(f"task {task_id} failed: {st.error}")
    if st.status != "done":
        raise ResourceError(f"task {task_id} is not finished yet (status: {st.status})")
    return st


# --------------------------------------------------------------------------- prompts

@mcp.prompt(title="Extract an invoice", description="Pull the key fields out of an invoice as JSON.")
def extract_invoice(
    document: Annotated[str, Field(description="Path or URL of the invoice")],
    currency: Annotated[str, Field(description="The currency you expect, if any, as an ISO 4217 code such as EUR or "
                                               "KES. Leave blank to take it from the document, which always wins.")] = "",
) -> list[Message]:
    if currency:
        reply = "reply with the JSON"
        hint = (f" You expected amounts in {currency}. If the document uses a different currency, keep the "
                f"document's currency in the JSON and add one sentence after it saying so.")
    else:
        reply, hint = "reply with only the JSON", ""
    return [UserMessage(
        f"Call extract_structured_data with source={document!r} and document_type='invoice'. "
        f"Then fill the schema it returns from the document text and {reply}.{hint} "
        f"Keep amounts in the document's own currency and never convert them. "
        f"If a field is not in the document, use null. Do not guess."
    )]


@mcp.prompt(title="Summarise a document", description="Read a document and summarise it at the requested length.")
def summarise_document(
    document: Annotated[str, Field(description="Path or URL of the document")],
    length: Annotated[str, Field(description="short (3 sentences), medium (a paragraph), or long (a page)")] = "short",
) -> list[Message]:
    return [UserMessage(
        f"Call read_document with source={document!r}. Then write a {length} summary of it. "
        f"Mention any tables or figures it contains. If the result carries a warning, say that "
        f"parts of the document could not be read."
    )]


@mcp.prompt(title="Compare two documents", description="Read two documents and report what differs.")
def compare_documents(
    document_a: Annotated[str, Field(description="Path or URL of the first document")],
    document_b: Annotated[str, Field(description="Path or URL of the second document")],
) -> list[Message]:
    return [UserMessage(
        f"Call read_document for {document_a!r} and again for {document_b!r}. Then compare them: "
        f"list what is in A but not B, what is in B but not A, and any values that differ. "
        f"Quote the differing text. Be precise about numbers and dates."
    )]


# --------------------------------------------------------------------------- health (HTTP transport only)

@mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
async def health(request):
    from starlette.responses import PlainTextResponse
    return PlainTextResponse("ok")
