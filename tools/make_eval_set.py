"""Build the starter evaluation set in tests/fixtures/eval/.

Each document is drawn from known text, so the correct answer is known exactly:

    <name>.png           the page image
    <name>.expected.md   what a perfect reading returns
    <name>.facts.json    short strings that must appear somewhere in the output

Three pages: an invoice in US dollars, a German invoice in euros with European
number formatting (1.046,01), and a clinic's referral letter. They are clean,
computer-drawn pages, the easiest case there is. They prove the harness works
and catch regressions. Real quality work needs your own scanned, photographed,
and multi-page documents added alongside them in the same format.

    python tools/make_eval_set.py
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "eval")
WIDTH, MARGIN = 1240, 80


def font(size):
    # Pillow ships a scalable font; this needs Pillow 10.1 or newer.
    return ImageFont.load_default(size=size)


# Pillow's built-in font has no euro sign, so the euro invoice is drawn with a
# system font that has one. The first of these that exists is used.
SYMBOL_FONTS = [
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def symbol_font():
    for path in SYMBOL_FONTS:
        if os.path.exists(path):
            return lambda size: ImageFont.truetype(path, size)
    raise SystemExit("The euro invoice needs a font with the euro sign. Install DejaVu Sans "
                     "(fonts-dejavu-core on Debian or Ubuntu), or add a font file to SYMBOL_FONTS.")


class Page:
    def __init__(self, height, fonts=font):
        self.img = Image.new("RGB", (WIDTH, height), "white")
        self.draw = ImageDraw.Draw(self.img)
        self.font = fonts
        self.y = MARGIN

    def line(self, text, size=26, gap=14):
        self.draw.text((MARGIN, self.y), text, fill="black", font=self.font(size))
        self.y += size + gap

    def space(self, n=20):
        self.y += n

    def table(self, rows, widths, size=24):
        row_h = size + 22
        x_edges = [MARGIN]
        for w in widths:
            x_edges.append(x_edges[-1] + w)
        top = self.y
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                self.draw.text((x_edges[c] + 12, self.y + 10), cell, fill="black", font=self.font(size))
            self.y += row_h
            self.draw.line([(MARGIN, self.y), (x_edges[-1], self.y)], fill="black", width=2 if r == 0 else 1)
        self.draw.rectangle([MARGIN, top, x_edges[-1], self.y], outline="black", width=2)
        for x in x_edges[1:-1]:
            self.draw.line([(x, top), (x, self.y)], fill="black", width=1)
        self.y += 20

    def save(self, name):
        self.img.save(os.path.join(OUT, f"{name}.png"), optimize=True)


def md_table(rows):
    out = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join("---" for _ in rows[0]) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


def write(name, expected, facts):
    with open(os.path.join(OUT, f"{name}.expected.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(expected.strip() + "\n")
    with open(os.path.join(OUT, f"{name}.facts.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(facts, f, indent=2)
        f.write("\n")


def invoice():
    rows = [["Item", "Qty", "Unit price", "Total"],
            ["Widget, large", "12", "45.00", "540.00"],
            ["Widget, small", "30", "12.50", "375.00"],
            ["Delivery", "1", "85.00", "85.00"]]
    p = Page(1100)
    p.line("ACME CORPORATION", size=44, gap=30)
    for t in ("Invoice #: INV-2026-0042", "Date: 2026-09-20", "Due: 2026-10-20"):
        p.line(t)
    p.space()
    p.table(rows, [520, 140, 220, 200])
    for t in ("Subtotal: 1000.00", "VAT (18%): 180.00", "Total due: 1180.00 USD"):
        p.line(t)
    p.space()
    p.line("Payment within 30 days to ACME CORPORATION, account 0123456789.")
    p.save("invoice")
    expected = "\n\n".join([
        "# ACME CORPORATION",
        "Invoice #: INV-2026-0042\nDate: 2026-09-20\nDue: 2026-10-20",
        md_table(rows),
        "Subtotal: 1000.00\nVAT (18%): 180.00\nTotal due: 1180.00 USD",
        "Payment within 30 days to ACME CORPORATION, account 0123456789.",
    ])
    write("invoice", expected, ["INV-2026-0042", "2026-09-20", "2026-10-20", "540.00", "375.00",
                                "1000.00", "180.00", "1180.00", "0123456789"])


def invoice_eur():
    """A German supplier's invoice in euros, with European number formatting.

    1.046,01 is one thousand and forty-six euros: a reader that keeps the
    figures exactly as printed passes, and the extraction step must read the
    comma as the decimal point. The euro sign and the EUR code are both facts.
    """
    eur = "€"
    rows = [["Item", "Qty", "Unit price", "Total"],
            ["Steel bracket", "24", f"12,50 {eur}", f"300,00 {eur}"],
            ["Mounting kit", "10", f"45,90 {eur}", f"459,00 {eur}"],
            ["Freight", "1", f"120,00 {eur}", f"120,00 {eur}"]]
    head = ("Hafenstrasse 12, 20457 Hamburg, Germany", "Invoice no.: RE-2026-0318",
            "Date: 21.09.2026", "Due: 21.10.2026")
    sums = (f"Net amount: 879,00 {eur}", f"VAT (19%): 167,01 {eur}", f"Total due: 1.046,01 {eur} (EUR)")
    pay = "Payment within 30 days to IBAN DE89 3704 0044 0532 0130 00."
    p = Page(1000, fonts=symbol_font())
    p.line("NORDWERK GMBH", size=44, gap=30)
    for t in head:
        p.line(t)
    p.space()
    p.table(rows, [460, 120, 240, 240])
    for t in sums:
        p.line(t)
    p.space()
    p.line(pay)
    p.save("invoice_eur")
    expected = "\n\n".join(["# NORDWERK GMBH", "\n".join(head), md_table(rows), "\n".join(sums), pay])
    write("invoice_eur", expected, ["RE-2026-0318", "21.09.2026", "21.10.2026", "12,50", "45,90",
                                    "879,00", "167,01", "1.046,01", eur, "EUR",
                                    "DE89 3704 0044 0532 0130 00"])


def letter():
    paragraphs = [
        ("Harbour View Clinic", 40),
        ("14 Quay Street, Mombasa", 26),
        ("Referral letter, 3 March 2026", 26),
    ]
    body = [
        "Dear Dr. Otieno,",
        "I am referring Ms. Amina Hassan, aged 42, for assessment of recurring",
        "headaches that began in January. Her blood pressure at the last two",
        "visits was 150/95 and 148/92. She takes no regular medication.",
        "Please see her within four weeks. Her records are enclosed.",
        "Yours sincerely,",
        "Dr. Grace Wanjiru",
    ]
    p = Page(900)
    for text, size in paragraphs:
        p.line(text, size=size, gap=18)
    p.space(30)
    for text in body:
        p.line(text)
    p.save("letter")
    expected = "\n\n".join([
        "# Harbour View Clinic",
        "14 Quay Street, Mombasa\nReferral letter, 3 March 2026",
        "Dear Dr. Otieno,",
        " ".join(body[1:4]),
        body[4],
        "Yours sincerely,\nDr. Grace Wanjiru",
    ])
    write("letter", expected, ["Harbour View Clinic", "3 March 2026", "Amina Hassan", "42",
                               "150/95", "148/92", "four weeks", "Grace Wanjiru"])


if __name__ == "__main__":
    # Print UTF-8 even when the output is piped, as in Git Bash on Windows, so a
    # euro sign or any other character in a document shows correctly instead of
    # garbling or stopping the script.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.makedirs(OUT, exist_ok=True)
    invoice()
    invoice_eur()
    letter()
    print(f"wrote the evaluation set to {os.path.normpath(OUT)}")
