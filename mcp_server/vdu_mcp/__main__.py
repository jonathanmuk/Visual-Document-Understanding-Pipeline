"""Run the server.

    python -m vdu_mcp                       stdio, for a local assistant
    python -m vdu_mcp --transport http      Streamable HTTP, for a shared deployment

On stdio, stdout is the protocol channel, so every log line goes to stderr.
"""
import argparse
import logging
import os
import sys

from .auth import BearerTokenMiddleware, tokens_from_env
from .server import fetch_policy, mcp


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        import json
        payload = {"time": self.formatTime(record), "level": record.levelname,
                   "logger": record.name, "message": record.getMessage()}
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stderr)
    if os.getenv("LOG_FORMAT", "text").lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    # force=True replaces the Rich handler the SDK installs on import.
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), handlers=[handler], force=True)


def main() -> None:
    parser = argparse.ArgumentParser(prog="vdu_mcp")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", "8080")))
    args = parser.parse_args()

    configure_logging()
    log = logging.getLogger("vdu_mcp")
    if not fetch_policy.enabled:
        log.info("URL sources are turned off (VDU_FETCH_URLS=off)")
    elif fetch_policy.allow_private:
        log.warning("VDU_FETCH_ALLOW_PRIVATE is on: URLs may reach private addresses; use only for local testing")

    if os.getenv("VDU_API_KEY"):
        log.info("sending the API key in the %s header", os.getenv("VDU_API_KEY_HEADER") or "Ocp-Apim-Subscription-Key")

    if args.transport == "stdio":
        log.info("starting on stdio; API at %s", os.getenv("VDU_API_URL", "http://localhost:5000"))
        mcp.run(transport="stdio")
        return

    import uvicorn
    from mcp.server.transport_security import TransportSecuritySettings

    allowed_hosts = [h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if args.host in ("127.0.0.1", "localhost", "::1"):
        security = None  # the SDK enables loopback-only protection itself
    elif allowed_hosts:
        security = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=allowed_hosts)
    else:
        # Bound to a non-loopback address with no host list: the server is
        # expected to sit behind the internal load balancer and API gateway,
        # and the bearer token below is the access control.
        security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

    app = mcp.streamable_http_app(host=args.host, transport_security=security)

    tokens = tokens_from_env(os.getenv("MCP_BEARER_TOKEN", ""), os.getenv("MCP_BEARER_TOKENS", ""))
    if tokens:
        app.add_middleware(BearerTokenMiddleware, tokens=tokens, exempt_paths=("/health",))
        log.info("bearer token authentication enabled (%d token%s accepted)", len(tokens), "" if len(tokens) == 1 else "s")
    else:
        log.warning("no bearer token is set; the HTTP transport is unauthenticated")

    log.info("starting Streamable HTTP on %s:%s/mcp; API at %s", args.host, args.port,
             os.getenv("VDU_API_URL", "http://localhost:5000"))
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
