"""The throughput tool's arithmetic, checked without a running system."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import throughput as t  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "fixtures")


def test_pages_are_counted_from_the_pdf_itself():
    pdf = open(os.path.join(FIXTURES, "sample.pdf"), "rb").read()
    png = open(os.path.join(FIXTURES, "sample.png"), "rb").read()
    assert t.count_pages(pdf) == 1
    assert t.count_pages(png) == 1, "an image is one page"


def test_summary_counts_outcomes_and_rates():
    tasks = [
        {"status": "done", "seconds": 10.0},
        {"status": "done", "seconds": 20.0, "warning": "2 region(s) ... failed"},
        {"status": "failed", "seconds": 5.0, "error": "document rejected"},
        {"status": "queued", "seconds": 1800.0},
    ]
    s = t.summarise(tasks, pages_per_document=3, wall_seconds=60.0)
    assert (s["documents"], s["done"], s["failed"], s["unfinished"], s["with_warning"]) == (4, 2, 1, 1, 1)
    assert s["documents_per_minute"] == 2.0, "only finished documents count towards speed"
    assert s["pages_per_second"] == 0.1, "2 documents x 3 pages in 60 seconds"
    assert s["seconds_per_document"]["max"] == 20.0


def test_no_finished_documents_means_no_rates():
    s = t.summarise([{"status": "failed", "seconds": 1.0}], pages_per_document=1, wall_seconds=5.0)
    assert "pages_per_second" not in s and s["failed"] == 1
