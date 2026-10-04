"""Score the pipeline's output against documents whose correct reading is known.

Without this, every prompt or profile change is a guess. With it, a change either
raises the score on your documents or it does not.

    python tools/evaluate.py run --label before-prompts
    ... change a prompt, a profile, or a setting, restart the worker ...
    python tools/evaluate.py run --label after-prompts
    python tools/evaluate.py compare benchmarks/eval-before-prompts.json benchmarks/eval-after-prompts.json

"run" submits every document in the evaluation set to the API, waits for each
result, scores it, and saves benchmarks/eval-<label>.json. It sends each document
with Cache-Control: no-cache, so a stored result from an earlier run is never
scored by mistake. A worker must be running: the real one (Z.ai or GPU) for real
scores, or tools/demo_worker.py to see the harness work (its canned answer only
matches the invoice, so its scores mean nothing).

Three scores per document, each from 0 to 1:

    text     how closely the whole output matches the expected text, ignoring
             Markdown symbols, capitals, and line breaks
    tables   the share of expected table cells found in the output's tables
             (F1, so extra wrong cells count against it too)
    facts    the share of must-have strings (numbers, names, dates) found anywhere

"overall" is the average of whichever of the three the document has.
"""
import argparse
import difflib
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SET = os.path.join(HERE, "..", "tests", "fixtures", "eval")
DOC_TYPES = (".pdf", ".png", ".jpg", ".jpeg")


def normalise(text):
    text = re.sub(r"^\s*\|?\s*:?-{3,}.*$", " ", text, flags=re.M)   # table separator rows
    text = re.sub(r"[#*_`|>]", " ", text)                           # Markdown symbols
    return " ".join(text.lower().split())


def text_score(expected, actual):
    # autojunk off: on long pages the default treats common characters as junk
    # and under-reports similarity.
    return difflib.SequenceMatcher(None, normalise(expected), normalise(actual), autojunk=False).ratio()


def table_cells(markdown):
    cells = []
    for line in markdown.splitlines():
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        if re.fullmatch(r"\|[\s:|-]+\|", line):
            continue
        cells += [" ".join(c.lower().split()) for c in line.strip("|").split("|")]
    return Counter(c for c in cells if c)


def table_score(expected, actual):
    want, got = table_cells(expected), table_cells(actual)
    if not want:
        return None
    if not got:
        return 0.0
    matched = sum((want & got).values())
    return 2 * matched / (sum(want.values()) + sum(got.values()))


def facts_score(facts, actual):
    if not facts:
        return None
    haystack = " ".join(actual.lower().split())
    found = [f for f in facts if " ".join(f.lower().split()) in haystack]
    return len(found) / len(facts), [f for f in facts if f not in found]


def score(expected, actual, facts=None):
    result = {"text": round(text_score(expected, actual), 4)}
    t = table_score(expected, actual)
    if t is not None:
        result["tables"] = round(t, 4)
    f = facts_score(facts, actual)
    if f is not None:
        result["facts"] = round(f[0], 4)
        result["missing_facts"] = f[1]
    parts = [v for k, v in result.items() if k in ("text", "tables", "facts")]
    result["overall"] = round(sum(parts) / len(parts), 4)
    return result


def load_set(folder):
    docs = []
    for name in sorted(os.listdir(folder)):
        stem, ext = os.path.splitext(name)
        if ext.lower() not in DOC_TYPES:
            continue
        expected_path = os.path.join(folder, f"{stem}.expected.md")
        if not os.path.exists(expected_path):
            print(f"skipping {name}: no {stem}.expected.md", file=sys.stderr)
            continue
        facts_path = os.path.join(folder, f"{stem}.facts.json")
        facts = json.load(open(facts_path, encoding="utf-8")) if os.path.exists(facts_path) else []
        docs.append({"name": stem, "path": os.path.join(folder, name),
                     "expected": open(expected_path, encoding="utf-8").read(), "facts": facts})
    return docs


def run(args):
    import httpx

    docs = load_set(args.set)
    if not docs:
        sys.exit(f"no documents with expected output in {args.set}")
    report = {"label": args.label, "when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "api": args.api, "documents": {}}
    with httpx.Client(base_url=args.api, timeout=60) as client:
        submitted = {}
        for d in docs:
            with open(d["path"], "rb") as f:
                r = client.post("/process", files={"file": (os.path.basename(d["path"]), f.read())},
                                headers={"Cache-Control": "no-cache"})
            if r.status_code not in (200, 202):
                sys.exit(f"{d['name']}: the API refused it ({r.status_code}): {r.text}")
            submitted[d["name"]] = r.json()["task_id"]
            print(f"submitted {d['name']} as {submitted[d['name']]}")

        deadline = time.time() + args.timeout
        pending = dict(submitted)
        finished = {}
        while pending and time.time() < deadline:
            for name, task_id in list(pending.items()):
                st = client.get(f"/status/{task_id}").json()
                if st["status"] in ("done", "failed"):
                    finished[name] = st
                    del pending[name]
            if pending:
                time.sleep(1)

    for d in docs:
        st = finished.get(d["name"])
        if st is None:
            entry = {"status": "timed out", "overall": 0.0}
        elif st["status"] == "failed":
            entry = {"status": "failed", "error": st.get("error"), "overall": 0.0}
        else:
            entry = {"status": "done", **score(d["expected"], (st.get("result") or {}).get("markdown", ""), d["facts"])}
            if st.get("warning"):
                entry["warning"] = st["warning"]
        entry["task_id"] = submitted[d["name"]]
        report["documents"][d["name"]] = entry

    overall = [e["overall"] for e in report["documents"].values()]
    report["average_overall"] = round(sum(overall) / len(overall), 4)
    os.makedirs("benchmarks", exist_ok=True)
    path = os.path.join("benchmarks", f"eval-{args.label}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print_report(report)
    print(f"\nsaved to {path}")
    if pending:
        print(f"{len(pending)} document(s) did not finish within {args.timeout}s: is a worker running?")


def print_report(report):
    print(f"\n{report['label']}")
    print(f"{'document':<16}{'status':<10}{'text':>8}{'tables':>8}{'facts':>8}{'overall':>9}")
    for name, e in report["documents"].items():
        cols = [f"{e[k]:.2f}" if k in e else "-" for k in ("text", "tables", "facts", "overall")]
        print(f"{name:<16}{e['status']:<10}{cols[0]:>8}{cols[1]:>8}{cols[2]:>8}{cols[3]:>9}")
        if e.get("missing_facts"):
            print(f"{'':<16}missing: {', '.join(e['missing_facts'])}")
        if e.get("error"):
            print(f"{'':<16}error: {e['error'][:120]}")
    print(f"{'average':<16}{'':<10}{'':>8}{'':>8}{'':>8}{report['average_overall']:>9.2f}")


def compare(args):
    a = json.load(open(args.before, encoding="utf-8"))
    b = json.load(open(args.after, encoding="utf-8"))
    print(f"{'document':<16}{a['label'][:12]:>13}{b['label'][:12]:>13}{'change':>9}")
    def fmt(v):
        return f"{v:.2f}" if v is not None else "-"

    for name in sorted(set(a["documents"]) | set(b["documents"])):
        x = a["documents"].get(name, {}).get("overall")
        y = b["documents"].get(name, {}).get("overall")
        change = f"{y - x:+.2f}" if x is not None and y is not None else "-"
        print(f"{name:<16}{fmt(x):>13}{fmt(y):>13}{change:>9}")
    delta = b["average_overall"] - a["average_overall"]
    print(f"{'average':<16}{fmt(a['average_overall']):>13}{fmt(b['average_overall']):>13}{delta:>+9.2f}")


def main():
    # Print UTF-8 even when the output is piped, as in Git Bash on Windows, so a
    # euro sign or any other character in a document shows correctly instead of
    # garbling or stopping the script.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="submit the evaluation set and score the results")
    r.add_argument("--label", required=True)
    r.add_argument("--set", default=DEFAULT_SET)
    r.add_argument("--api", default=os.getenv("API_URL", "http://127.0.0.1:15000"))
    r.add_argument("--timeout", type=int, default=600)
    c = sub.add_parser("compare", help="compare two saved runs")
    c.add_argument("before")
    c.add_argument("after")
    args = ap.parse_args()
    run(args) if args.command == "run" else compare(args)


if __name__ == "__main__":
    main()
