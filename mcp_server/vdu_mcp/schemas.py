"""Static data served as MCP resources, and the built-in extraction schemas."""

# What GET /status/{task_id} returns, and therefore what read_document returns.
RESULT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Visual Document Understanding Pipeline document result",
    "type": "object",
    "properties": {
        "task_id": {"type": "string", "description": "UUID assigned when the document was submitted."},
        "status": {"type": "string", "enum": ["queued", "processing", "done", "failed"]},
        "attempts": {"type": ["integer", "null"], "description": "How many times a worker has picked this task up."},
        "markdown": {"type": "string", "description": "The document as Markdown, in reading order. Tables are Markdown tables, formulas are LaTeX. Empty unless status is done."},
        "layout": {
            "type": "array",
            "description": "One list per page. Each region has a label, its bounding box, and its content.",
            "items": {"type": "array", "items": {"type": "object"}},
        },
        "error": {"type": ["string", "null"], "description": "Set when status is failed. Says why."},
        "warning": {"type": ["string", "null"], "description": "Set when the document finished but some regions could not be transcribed."},
        "cached": {"type": "boolean", "description": "True when an identical document was read recently and its stored result was returned without running the pipeline again."},
    },
    "required": ["task_id", "status"],
}

# Mirrors label_task_mapping in realtime_consumer/config.yaml. Kept here as data
# so the MCP server does not depend on the worker's config file being present.
LAYOUT_LABELS = {
    "description": ("Every region the layout model can detect, and what the pipeline does with it. "
                    "These are the default profile's rules. A deployment running the finance or academic "
                    "profile also reads some regions listed here as abandon, such as headers or footnotes."),
    "fates": {
        "text": "sent to the model with a transcription prompt; appears in markdown",
        "table": "sent to the model with a Markdown-table prompt; appears in markdown as a table",
        "formula": "sent to the model with a LaTeX prompt; appears in markdown as LaTeX",
        "chart": "sent to the model with a chart-description prompt; the description, starting 'Chart:', appears in markdown",
        "skip": "kept in the layout with its position, but not transcribed; appears in markdown as an image placeholder",
        "abandon": "discarded entirely; does not appear in markdown or layout",
    },
    "labels": {
        "abstract": "text", "algorithm": "text", "content": "text", "doc_title": "text",
        "figure_title": "text", "paragraph_title": "text", "reference_content": "text",
        "text": "text", "vertical_text": "text", "vision_footnote": "text", "seal": "text",
        "formula_number": "text",
        "table": "table",
        "display_formula": "formula", "inline_formula": "formula",
        "chart": "chart", "image": "skip",
        "header": "abandon", "footer": "abandon", "number": "abandon", "footnote": "abandon",
        "aside_text": "abandon", "reference": "abandon", "footer_image": "abandon", "header_image": "abandon",
    },
}

# Built-in schemas for extract_structured_data. The calling model fills these
# from the document text; the server does not run a model of its own.
#
# Money works the same way in every schema: amounts stay in the currency the
# document uses (never converted), the currency is only named when the document
# makes it clear (never assumed to be US dollars), and the symbol is also kept
# exactly as printed, since "$" or "kr" alone can mean several currencies.
CURRENCY = {
    "type": ["string", "null"],
    "description": ("ISO 4217 code of the currency the amounts are in, for example EUR, GBP, KES, JPY, USD. "
                    "Use the code if the document prints one; otherwise infer it only when the symbol and the "
                    "issuer's country together make it certain (EUR for a German invoice in euros). "
                    "null when the document does not make it clear. Never assume USD."),
}
CURRENCY_AS_PRINTED = {
    "type": ["string", "null"],
    "description": "The currency symbol or code exactly as printed, for example €, £, KSh, CHF, $.",
}
AMOUNT_NOTE = ("In the document's own currency, never converted. Read the document's separators: "
               "1.234,56 and 1 234,56 are both 1234.56.")


def amount(nullable=False):
    return {"type": ["number", "null"] if nullable else "number", "description": AMOUNT_NOTE}


EXTRACTION_SCHEMAS = {
    "invoice": {
        "type": "object",
        "properties": {
            "vendor_name": {"type": "string"},
            "vendor_address": {"type": "string"},
            "invoice_number": {"type": "string"},
            "invoice_date": {"type": "string", "format": "date"},
            "due_date": {"type": ["string", "null"], "format": "date"},
            "currency": CURRENCY,
            "currency_as_printed": CURRENCY_AS_PRINTED,
            "line_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "quantity": {"type": "number"},
                        "unit_price": amount(),
                        "total": amount(),
                    },
                    "required": ["description", "total"],
                },
            },
            "subtotal": amount(nullable=True),
            "tax": amount(nullable=True),
            "total": amount(),
        },
        "required": ["vendor_name", "invoice_number", "currency", "total"],
    },
    "receipt": {
        "type": "object",
        "properties": {
            "merchant": {"type": "string"},
            "date": {"type": "string", "format": "date"},
            "currency": CURRENCY,
            "currency_as_printed": CURRENCY_AS_PRINTED,
            "items": {"type": "array", "items": {"type": "object", "properties": {
                "description": {"type": "string"}, "amount": amount()}}},
            "total": amount(),
            "payment_method": {"type": ["string", "null"]},
        },
        "required": ["merchant", "currency", "total"],
    },
    "contract": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "parties": {"type": "array", "items": {"type": "string"}},
            "effective_date": {"type": ["string", "null"], "format": "date"},
            "term": {"type": ["string", "null"], "description": "Duration or end condition, as written"},
            "governing_law": {"type": ["string", "null"]},
            "key_obligations": {"type": "array", "items": {"type": "string"}},
            "termination_clauses": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "parties"],
    },
    "generic": {
        "type": "object",
        "properties": {
            "title": {"type": ["string", "null"]},
            "document_type": {"type": "string", "description": "Your best classification of what this document is"},
            "dates": {"type": "array", "items": {"type": "string"}},
            "people_and_organisations": {"type": "array", "items": {"type": "string"}},
            "amounts": {"type": "array", "items": {"type": "string"},
                        "description": "Each amount exactly as printed, with its currency symbol or code."},
            "summary": {"type": "string"},
        },
        "required": ["document_type", "summary"],
    },
}
