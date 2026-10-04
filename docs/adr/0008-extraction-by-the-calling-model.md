# 0008. Let the calling assistant fill extraction schemas; no model of our own

**Status:** Accepted. Recorded 30 September 2026.

## Context

Often what people want from a document is not its text but a few fields: an
invoice's number, date, and total; a contract's parties. Turning text into those
fields is a language task. Something has to do it: either a model inside this
system, or the assistant that asked.

## Decision

`extract_structured_data` reads the document as usual and returns its text
together with a schema of the fields wanted (built-in ones for invoices,
receipts, contracts, and a general one, or one the caller supplies), plus an
instruction to fill it without inventing values. The calling assistant, which is
itself a capable language model, fills the schema.

If the caller does not say what kind of document it is, the server asks the
person (elicitation) rather than guessing.

## Consequences

Good:

- No second model to host, pay for, secure, or keep up to date.
- The assistant sees the full text and can explain its answer or ask a follow-up.
- Works with every MCP assistant the same way.

Costs:

- Clients that are not language models (a script, a business system) get a
  schema and text, not filled fields. They must fill it themselves or call a
  model.
- The quality of the fields depends on the calling assistant.

## When to revisit

If a client that is not a language model needs filled fields, add a server-side
extraction step that calls a model directly, behind the same tool.

## Alternatives considered

- **A server-side model.** Useful for non-assistant clients; a paid dependency
  and a second place for errors for everyone else.
- **Template rules per document type.** Precise for one layout, brittle across
  many.
