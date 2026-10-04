# Architecture Decision Records

An architecture decision record (ADR) is a short note that captures one
significant choice: what the situation was, what was decided, what it costs,
and what else was considered. They exist so that anyone reading the system
later can see *why* it is the way it is, not just *what* it is, and can tell
whether the reasons still hold before changing it.

Each record has a status. **Accepted** means it describes the system as it is.
A decision that is later reversed is not deleted: its status changes to
**Superseded**, with a link to the record that replaced it.

| # | Decision | Status |
| :--- | :--- | :--- |
| [0001](0001-two-stage-pipeline.md) | Read documents in two stages: find the regions, then read each one | Accepted |
| [0002](0002-reliable-queue.md) | A reliable queue in Redis, with an in-progress list and a reaper | Accepted |
| [0003](0003-mcp-server.md) | Offer the system to AI assistants through an MCP server | Accepted |
| [0004](0004-result-cache.md) | Cache results by the document's exact content | Accepted |
| [0005](0005-no-object-storage-yet.md) | Keep documents only until they are read; no archive | Accepted |
| [0006](0006-callbacks-from-the-reaper.md) | Deliver callbacks from the reaper, signed, to listed hosts only | Accepted |
| [0007](0007-static-bearer-tokens.md) | Protect the shared MCP server with rotatable bearer tokens, not OAuth yet | Accepted |
| [0008](0008-extraction-by-the-calling-model.md) | Let the calling assistant fill extraction schemas; no model of our own | Accepted |

The format follows Michael Nygard's original proposal: context, decision,
consequences, with the alternatives added.
