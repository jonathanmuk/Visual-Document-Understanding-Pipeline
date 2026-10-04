# 0007. Protect the shared MCP server with rotatable bearer tokens, not OAuth yet

**Status:** Accepted. Recorded 30 September 2026.

## Context

The MCP server in the cluster is shared by a team and must not be usable by
anyone who can reach its address. MCP's own answer for remote servers is OAuth:
the assistant sends the person to sign in, and the server checks the resulting
token. The MCP Python SDK supports this (`AuthSettings`, `TokenVerifier`), but
it needs an identity provider set up, registered clients, and token checking.

The server sits on a private address, behind the cluster's network rules, and
is used by a known team.

## Decision

Require a bearer token on every request (except the health check), compared in
constant time. The accepted tokens come from the `ocr-mcp-secret` Secret, and
several can be valid at once (`MCP_BEARER_TOKENS`, comma separated), so a token
is changed by adding the new one, moving everyone over, and removing the old
one, with no moment when nobody can connect. `docs/mcp_setup.md` section 7 has
the steps; they were rehearsed on a test cluster.

## Consequences

Good:

- Simple to operate: one Secret, one header.
- Works with Claude Code and any client that can send a header.
- Rotation without downtime.

Costs:

- Anyone holding a token has full use of the server until it is removed. Tokens
  must be handled like passwords.
- No record of which person made a request, only that a valid token was used.
- Claude Desktop's custom connectors sign in with OAuth and have no place for a
  fixed token, so Claude Desktop reaches a deployed system through a local
  server pointed at the gateway instead (`docs/mcp_setup.md` section 5b).

## When to revisit

Move to OAuth through the SDK's `AuthSettings` and `TokenVerifier` when people
outside the team need access, when requests must be tied to a person, or when
Claude Desktop needs to reach the shared server directly.

## Alternatives considered

- **OAuth now.** The right end state for a wider audience; more than a small
  team on a private network needs today.
- **No authentication, network rules only.** Anyone inside the network could use
  it, and every document can start a GPU machine.
