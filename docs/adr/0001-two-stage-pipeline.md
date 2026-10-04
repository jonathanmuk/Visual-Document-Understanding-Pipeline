# 0001. Read documents in two stages: find the regions, then read each one

**Status:** Accepted. Recorded 30 September 2026.

## Context

A vision language model can be given a whole page and asked to write out
everything on it. That is simple, but on hard pages (scans, dense tables,
several columns) such models get the *structure* wrong: they merge columns,
skip or repeat rows, attach a number to the wrong label, or invent text. For
invoices, contracts, and financial statements, a wrong structure is as bad as
wrong text, and harder to notice.

The system also has to be affordable at volume, and its output has to say what
each piece of text was (a title, a table, a footnote).

## Decision

Split the job in two:

1. A small, fast layout model (PP-DocLayoutV3, on a T4 GPU) finds the regions on
   each page and labels them: paragraph, table, formula, chart, header, and so on.
2. Each useful region is cut out and sent separately to the reading model
   (Qwen3.5-4B, served by vLLM on an A100), with an instruction that suits its
   type: "transcribe this text", "convert this table to Markdown", "write this
   formula as LaTeX", "describe this chart".

Page furniture (running headers, page numbers) is thrown away before it reaches
the reading model, and the pieces are put back together in reading order.

## Consequences

Good:

- Narrow questions leave the model little room to invent: "convert this one
  table" has few reasonable answers; "read this page" has many.
- The output keeps the document's structure, because every region already has a
  label.
- Less is sent to the expensive model: discarded regions cost nothing.
- The two stages run on different, right-sized hardware and scale separately.
- Prompts and region rules can be tuned per kind of document (the profiles).

Costs:

- More moving parts: two models, two GPU pools, an orchestrating worker.
- A region the layout model misses is lost, whatever the reading model could
  have done with it.
- A region the reading model fails on can disappear quietly; the SDK drops it.
  The worker counts those failures from the SDK's log and adds a warning, but
  the proper fix belongs upstream.

## Alternatives considered

- **One model reads the whole page.** Simpler, and improving quickly, but the
  structural mistakes above are the reason this system exists.
- **Traditional OCR only.** Cheap, but it returns text without structure and
  cannot describe charts.
