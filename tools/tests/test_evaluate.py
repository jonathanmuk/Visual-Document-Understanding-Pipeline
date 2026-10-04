"""The scoring must reward correct readings and punish wrong ones, predictably."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import evaluate as ev  # noqa: E402

EVAL_SET = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "fixtures", "eval")


def test_the_starter_set_loads():
    docs = ev.load_set(EVAL_SET)
    assert [d["name"] for d in docs] == ["invoice", "invoice_eur", "letter"]
    assert all(d["facts"] for d in docs)


def test_a_perfect_reading_scores_one():
    for d in ev.load_set(EVAL_SET):
        s = ev.score(d["expected"], d["expected"], d["facts"])
        assert s["overall"] == 1.0, (d["name"], s)
        assert s["missing_facts"] == []


def test_formatting_differences_do_not_cost_points():
    expected = "# Title\n\nSome **bold** text\nacross lines."
    actual = "TITLE\nsome bold text across lines."
    assert ev.text_score(expected, actual) == 1.0


def test_a_euro_reading_must_keep_its_own_number_format():
    d = next(d for d in ev.load_set(EVAL_SET) if d["name"] == "invoice_eur")
    assert ev.score(d["expected"], d["expected"], d["facts"])["missing_facts"] == []
    # A reader that "tidies" 1.046,01 into US style has changed the document.
    us_style = d["expected"].replace("1.046,01", "1,046.01")
    assert ev.score(d["expected"], us_style, d["facts"])["missing_facts"] == ["1.046,01"]
    no_symbol = d["expected"].replace("€", "")
    assert ev.score(d["expected"], no_symbol, d["facts"])["missing_facts"] == ["€"]


def test_a_wrong_number_costs_a_fact_and_a_table_cell():
    d = next(d for d in ev.load_set(EVAL_SET) if d["name"] == "invoice")
    wrong = d["expected"].replace("540.00", "546.00")
    s = ev.score(d["expected"], wrong, d["facts"])
    assert s["missing_facts"] == ["540.00"]
    assert s["facts"] == round(8 / 9, 4)
    assert s["tables"] < 1.0
    assert s["text"] > 0.95, "one digit barely moves the text score, which is why facts exist"


def test_a_lost_table_scores_zero_for_tables():
    d = next(d for d in ev.load_set(EVAL_SET) if d["name"] == "invoice")
    no_table = "\n".join(l for l in d["expected"].splitlines() if not l.startswith("|"))
    assert ev.score(d["expected"], no_table, d["facts"])["tables"] == 0.0


def test_documents_without_tables_or_facts_are_scored_on_what_they_have():
    s = ev.score("plain text only", "plain text only")
    assert set(s) == {"text", "overall"} and s["overall"] == 1.0


def test_table_cells_ignore_the_separator_row_and_spacing():
    md = "| A | B |\n| --- | :---: |\n|  x  y | 2 |"
    assert ev.table_cells(md) == {"a": 1, "b": 1, "x y": 1, "2": 1}


def test_unrelated_text_scores_low():
    d = next(d for d in ev.load_set(EVAL_SET) if d["name"] == "letter")
    s = ev.score(d["expected"], "ACME CORPORATION Invoice #: INV-2026-0042 Total due: 1180.00 USD", d["facts"])
    assert s["overall"] < 0.3
