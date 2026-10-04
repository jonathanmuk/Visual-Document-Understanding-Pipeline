"""Pre-flight check: open each document on the CPU before it reaches the GPU.

The API only checks a document's first bytes. A file can start like a PDF and be
garbage after that, be password protected, or have ten thousand pages. Without
this check such a file would reach the layout model inside a batch, and if it
failed there it would take the other documents in the batch down with it, up to
three times. Here it fails alone, once, with a reason a person can act on.

Uses the same libraries the SDK uses to read documents (pypdfium2 for PDFs,
Pillow for images), so a file that passes here is one the SDK can open.
"""
import io
import os

from vdu_queue import REJECTED_PREFIX

# Pillow's own decompression bomb threshold. A small file that decodes to more
# pixels than this is almost always an attack or a mistake.
DEFAULT_MAX_IMAGE_PIXELS = 89_478_485
DEFAULT_MAX_PDF_PAGES = 200


class Limits:
    def __init__(self):
        self.max_pdf_pages = int(os.getenv("MAX_PDF_PAGES", str(DEFAULT_MAX_PDF_PAGES)))
        self.max_image_pixels = int(os.getenv("MAX_IMAGE_PIXELS", str(DEFAULT_MAX_IMAGE_PIXELS)))


def _reject(reason):
    return f"{REJECTED_PREFIX} {reason}"


def inspect_pdf(data, limits):
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as e:
        reason = str(e).rstrip(".")
        return _reject(f"the PDF could not be opened ({reason}); it may be corrupt or password protected")
    try:
        pages = len(pdf)
        if pages == 0:
            return _reject("the PDF has no pages")
        if pages > limits.max_pdf_pages:
            return _reject(f"the PDF has {pages} pages; the limit is {limits.max_pdf_pages}")
        # Opening the first page catches files whose header and page count read
        # fine but whose content does not.
        pdf[0].close()
    except pdfium.PdfiumError as e:
        return _reject(f"the PDF could not be read ({e})")
    finally:
        pdf.close()
    return None


def inspect_image(data, limits):
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            if width * height > limits.max_image_pixels:
                return _reject(
                    f"the image is {width} x {height} pixels; the limit is {limits.max_image_pixels} pixels")
            # Decoding the whole image catches truncated and corrupt files.
            img.load()
    except Image.DecompressionBombError as e:
        return _reject(str(e))
    except UnidentifiedImageError:
        return _reject("the image format could not be recognised; the file may be truncated or corrupt")
    except (OSError, ValueError, SyntaxError) as e:
        return _reject(f"the image could not be decoded ({e}); it may be truncated or corrupt")
    return None


def inspect(data, extension, limits=None):
    """Return None if the document looks processable, else the reason it is not."""
    limits = limits or Limits()
    if not data:
        return _reject("the document is empty")
    if extension == "pdf":
        return inspect_pdf(data, limits)
    return inspect_image(data, limits)
