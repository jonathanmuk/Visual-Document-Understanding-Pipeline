# 0003. Offer the system to AI assistants through an MCP server

**Status:** Accepted. Recorded 30 September 2026.

## Context

More and more of the people who would use a document reader work through an AI
assistant. Without a standard, every assistant needs its own integration with
every tool: M assistants times N tools. The Model Context Protocol (MCP) is the
open standard that turns that into M plus N: an assistant that speaks MCP can
use any MCP server, and a tool offered as an MCP server works with every such
assistant. (The reasoning is set out in the author's article,
[Model Context Protocol](https://www.jonathanmuk.com/insights/model-context-protocol).)

AI assistants such as Claude Code and Claude Desktop increasingly read
documents for people, and MCP is the standard way to give them a new tool.

## Decision

Build `mcp_server/`, a thin MCP server on the official Python SDK:

- It knows nothing about models or GPUs. Every document goes through the same
  API as every other client, so it inherits the API's checks, limits, and
  metrics.
- It offers MCP's three kinds of thing: **tools** the model chooses
  (`read_document`, `submit_document`, `get_document_status`,
  `extract_structured_data`), **resources** the application reads (the result
  schema, the layout labels, any finished document), and **prompts** the person
  chooses (invoice extraction, summaries, comparisons).
- It reports progress while it waits, and asks the person a question
  (elicitation) when it cannot know something, rather than guessing.
- Locally it runs over stdio, started by the assistant; in the cluster it runs
  over Streamable HTTP behind a bearer token.
- It enforces its own rules for which files and web addresses it may read,
  rather than trusting the assistant.

## Consequences

Good:

- Any MCP-capable assistant can read documents through the system with no code
  written by its user.
- Because it is thin, it has almost nothing of its own that can go wrong, and it
  gets every improvement to the pipeline for free.
- A remote server exposed to model-chosen input is an attack surface; building
  the path and URL rules into the server closes it at the server, not at the
  assistant.

Costs:

- One more service to deploy, secure, and keep current with a protocol that is
  still changing (the 2026-07-28 revision removed sessions and changed
  elicitation; the server follows the SDK).
- The shared server's bearer tokens are not accepted by Claude Desktop's custom
  connectors, which sign in with OAuth (see ADR 0007).

## Alternatives considered

- **A REST API only.** It already exists; assistants would each need their own
  glue code to use it.
- **Assistant-specific plugins.** One per assistant, the M times N problem again.
