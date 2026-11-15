"""Benchmark docintel on a labelled image/PDF suite (the `ocr_test_suite_200` format).

The suite folder holds `manifest.csv` (case_id, domain, image_path, ...) and, per case, a
ground-truth JSON with `expected_fields` {label: value}, `expected_table` {headers, rows}
and `expected_text`.  Cases are split before anything is looked at: odd case numbers are
the development half (look at their failures, fix causes), even ones are held out (only
ever measured).

    python benchmarks/run_suite.py <suite folder> --split heldout [--out bench_out] [-v]

Reports, per domain: fields correct, table cells correct, words of the expected text
found, SILENT errors (a wrong value, or a value under the wrong label, that docintel did
not flag), flagged errors and missed fields.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docintel.normalize import parse_date  # noqa: E402
from docintel.pipeline import process_file  # noqa: E402


def part(case_id: str) -> str:
    return "dev" if int(case_id.rsplit("-", 1)[1]) % 2 == 1 else "heldout"


def run_one(job):
    src, out_json = job
    t0 = time.time()
    try:
        with tempfile.TemporaryDirectory() as t:
            docs = process_file(Path(src), lambda k, n, g: {"doc_id": f"DOC_{k:03d}", "source_path": Path(t) / f"{k}.pdf"})
        res = {"ok": True, "seconds": round(time.time() - t0, 2), "docs": docs}
    except Exception as e:  # a crash is a finding
        res = {"ok": False, "seconds": round(time.time() - t0, 2), "error": repr(e)}
    Path(out_json).write_text(json.dumps(res), encoding="utf-8")
    return res["ok"]


def nl(s):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(s).lower()).split())


def nv(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def same_value(got, raw, exp):
    if got is None:
        return False
    cands = [", ".join(map(str, got))] if isinstance(got, list) else [got] + ([raw] if raw else [])
    if any(nv(c) == nv(exp) for c in cands):
        return True
    iso = parse_date(str(exp), "dmy")
    return bool(iso) and any(str(c) == iso for c in cands)


def sim(a, b):
    return SequenceMatcher(None, nl(a), nl(b)).ratio()


def score(suite: Path, out: Path, split: str, verbose: bool):
    tot, by_dom, fails = Counter(), defaultdict(Counter), []
    for gtf in sorted(suite.glob("*/ground_truth/*.json")):
        gt = json.loads(gtf.read_text(encoding="utf-8"))
        jf = out / f"{gt['case_id']}.json"
        if part(gt["case_id"]) != split or not jf.exists():
            continue
        res = json.loads(jf.read_text())
        c = Counter(docs=1)
        if not res["ok"]:
            c["crash"] += 1
            tot.update(c); by_dom[gt["domain"]].update(c)
            continue
        doc = res["docs"][0]
        attrs = [{"label": a.get("field_label") or "", "value": a.get("value"), "raw": a.get("raw"),
                  "status": a.get("status")} for e in doc["entities"].values() if e["type"] != "Section"
                 for a in e["attributes"].values()]
        for label, value in gt["expected_fields"].items():
            c["fields"] += 1
            cands = [a for a in attrs if a["label"] and sim(a["label"], label) >= 0.85]
            if cands and any(same_value(a["value"], a["raw"], value) for a in cands):
                c["f_correct"] += 1
            elif cands:
                silent = cands[0]["status"] == "valid"
                c["f_wrong_silent" if silent else "f_wrong_flagged"] += 1
                fails.append((gt["case_id"], "wrong", label, value, cands[0]["value"], silent))
            else:
                other = [a for a in attrs if same_value(a["value"], a["raw"], value)]
                if other:
                    silent = other[0]["status"] == "valid"
                    c["f_mislabelled_silent" if silent else "f_mislabelled_flagged"] += 1
                    fails.append((gt["case_id"], "mislabelled", label, value, other[0]["label"], silent))
                else:
                    c["f_missed"] += 1
                    fails.append((gt["case_id"], "missed", label, value, None, None))
        table = gt.get("expected_table")
        if table:
            rows = [e for e in doc["entities"].values() if e["type"] in ("TableRow", "Medication")]
            for r in table["rows"]:
                match = next(({a.get("field_label") or k: a for k, a in e["attributes"].items()} for e in rows
                              if any(same_value(a.get("value"), a.get("raw"), r[0]) for a in e["attributes"].values())),
                             None)
                for h, cell in zip(table["headers"], r):
                    c["cells"] += 1
                    a = next((a for lab, a in (match or {}).items() if sim(lab, h) >= 0.8), None)
                    if a is None and cell.strip() in ("-", "", "—"):
                        c["c_correct"] += 1
                    elif a is None:
                        c["c_missed"] += 1
                    elif same_value(a.get("value"), a.get("raw"), cell):
                        c["c_correct"] += 1
                    else:
                        c["c_wrong_silent" if a.get("status") == "valid" else "c_wrong_flagged"] += 1
                        fails.append((gt["case_id"], "cell", h, cell, a.get("value"), a.get("status") == "valid"))

        def btext(b):
            parts = [b.get("text") or "", b.get("label") or "", str(b.get("value") or "")]
            parts += [" ".join(map(str, b.get("header") or []))] + [" ".join(map(str, r)) for r in b.get("rows") or []]
            parts += [str(b.get("question") or "")] + [str(o.get("label") or "") if isinstance(o, dict) else str(o)
                                                       for o in b.get("options") or []]  # check-box choices
            return " ".join(parts)

        exp = Counter(re.findall(r"[a-z0-9]+", gt["expected_text"].lower()))
        got = Counter(re.findall(r"[a-z0-9]+", " ".join(btext(b) for b in doc.get("blocks", [])).lower()))
        c["text_words"] += sum(exp.values())
        c["text_found"] += sum((exp & got).values())
        tot.update(c); by_dom[gt["domain"]].update(c)

    def line(name, c):
        sil = c["f_wrong_silent"] + c["f_mislabelled_silent"] + c["c_wrong_silent"]
        flg = c["f_wrong_flagged"] + c["f_mislabelled_flagged"] + c["c_wrong_flagged"]
        print(f"{name:18} docs {c['docs']:3}  fields {c['f_correct']}/{c['fields']} ({c['f_correct'] / max(1, c['fields']):.1%})"
              f"  cells {c['c_correct']}/{c['cells']} ({c['c_correct'] / max(1, c['cells']):.1%})"
              f"  text {c['text_found'] / max(1, c['text_words']):.1%}  SILENT {sil}  flagged {flg}"
              f"  missed {c['f_missed']}  crash {c['crash']}")

    for d in sorted(by_dom):
        line(d, by_dom[d])
    line("TOTAL", tot)
    if verbose:
        for f in fails:
            print("  ", f)
    return tot


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("suite")
    ap.add_argument("--split", choices=["dev", "heldout"], default="heldout")
    ap.add_argument("--out", default="bench_out/suite")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--score-only", action="store_true")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args(argv)
    suite, out = Path(a.suite), Path(a.out) / a.split
    out.mkdir(parents=True, exist_ok=True)
    if not a.score_only:
        rows = list(csv.DictReader(open(suite / "manifest.csv", encoding="utf-8-sig")))
        jobs = [(suite / r["image_path"], out / f"{r['case_id']}.json") for r in rows if part(r["case_id"]) == a.split]
        with ProcessPoolExecutor(a.workers) as ex:
            ok = list(ex.map(run_one, jobs))
        print(f"{len(ok)} processed, {ok.count(False)} crashed")
    score(suite, out, a.split, a.v)


if __name__ == "__main__":
    main()
