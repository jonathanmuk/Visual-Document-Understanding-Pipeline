"""Hostile and broken input: the pre-flight check must name the problem, not crash."""
import io
import os

import pypdfium2 as pdfium
from PIL import Image

import vdu_inspect as v
import vdu_queue as q

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "fixtures")
PDF = open(os.path.join(FIXTURES, "sample.pdf"), "rb").read()
PNG = open(os.path.join(FIXTURES, "sample.png"), "rb").read()


def limits(pages=200, pixels=v.DEFAULT_MAX_IMAGE_PIXELS):
    lim = v.Limits()
    lim.max_pdf_pages, lim.max_image_pixels = pages, pixels
    return lim


def pdf_with_pages(n):
    doc = pdfium.PdfDocument.new()
    for _ in range(n):
        doc.new_page(200, 200)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def jpeg(width=64, height=64):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, "JPEG")
    return buf.getvalue()


def test_the_real_fixtures_pass():
    assert v.inspect(PDF, "pdf", limits()) is None
    assert v.inspect(PNG, "png", limits()) is None
    assert v.inspect(jpeg(), "jpg", limits()) is None


def test_valid_header_with_garbage_after_it_is_rejected():
    err = v.inspect(b"%PDF-1.7\n" + os.urandom(2000), "pdf", limits())
    assert err.startswith("document rejected: the PDF could not be opened")


def test_truncated_pdf_is_rejected_or_readable_never_a_crash():
    # PDFium repairs some truncations. Either outcome is fine; an exception is not.
    for cut in (20, 100, len(PDF) // 2):
        result = v.inspect(PDF[:cut], "pdf", limits())
        assert result is None or result.startswith(q.REJECTED_PREFIX)


def test_pdf_page_limit():
    doc = pdf_with_pages(5)
    assert v.inspect(doc, "pdf", limits(pages=5)) is None, "exactly the limit is allowed"
    assert v.inspect(doc, "pdf", limits(pages=4)) == "document rejected: the PDF has 5 pages; the limit is 4"


def test_pdf_with_no_pages_is_rejected():
    # PDFium refuses to open a PDF with no pages at all, so the rejection comes
    # from the open step; the explicit page check covers any it does open.
    assert v.inspect(pdf_with_pages(0), "pdf", limits()).startswith(q.REJECTED_PREFIX)


def test_truncated_png_is_rejected():
    assert "could not be recognised" in v.inspect(PNG[:30], "png", limits())


def test_truncated_jpeg_is_rejected():
    data = jpeg(400, 400)
    err = v.inspect(data[: len(data) // 2], "jpg", limits())
    assert err.startswith("document rejected: the image could not be decoded")


def test_image_over_the_pixel_limit_is_rejected_before_decoding():
    err = v.inspect(jpeg(100, 100), "jpg", limits(pixels=9_999))
    assert err == "document rejected: the image is 100 x 100 pixels; the limit is 9999 pixels"
    assert v.inspect(jpeg(100, 100), "jpg", limits(pixels=10_000)) is None, "exactly the limit is allowed"


def test_rejections_are_never_retried():
    assert q.is_non_retryable("document rejected: the PDF has 900 pages; the limit is 200")
    assert not q.is_non_retryable("connection reset by peer")
