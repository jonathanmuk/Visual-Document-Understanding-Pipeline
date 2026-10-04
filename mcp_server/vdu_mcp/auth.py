"""Bearer token check for the HTTP transport.

Static tokens, compared in constant time. In the cluster the server sits
behind an internal load balancer of its own, on a private address; the API
gateway does not publish it. The token stops anything inside the network that is
not supposed to be calling the MCP server.

More than one token may be valid at once, so a token can be rotated without
downtime: add the new one, move clients over, then remove the old one.
OAuth through the SDK's AuthSettings and TokenVerifier is the upgrade path when
clients belong to people outside the team; see
docs/adr/0007-static-bearer-tokens.md.
"""
import hmac

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


def tokens_from_env(single: str, many: str) -> list[str]:
    """MCP_BEARER_TOKENS (comma separated) plus the older MCP_BEARER_TOKEN."""
    tokens = [t.strip() for t in (many or "").split(",") if t.strip()]
    if single and single.strip() and single.strip() not in tokens:
        tokens.append(single.strip())
    return tokens


class BearerTokenMiddleware:
    def __init__(self, app: ASGIApp, tokens: list[str], exempt_paths: tuple[str, ...] = ()):
        if not tokens:
            raise ValueError("at least one token is required")
        self.app = app
        self.tokens = [t.encode() for t in tokens]
        self.exempt_paths = exempt_paths

    def _valid(self, presented: bytes) -> bool:
        # Compare against every token, so the time taken does not reveal which
        # one nearly matched.
        matched = False
        for token in self.tokens:
            matched |= hmac.compare_digest(presented, token)
        return matched

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        header = b""
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                header = value
                break
        scheme, _, presented = header.partition(b" ")
        if scheme.lower() != b"bearer" or not self._valid(presented.strip()):
            response = JSONResponse(
                {"error": "unauthorized", "detail": "a valid 'Authorization: Bearer <token>' header is required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
