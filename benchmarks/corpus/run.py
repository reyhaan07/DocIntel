"""Run docintel on the corpus and score it, per dataset (suite and FUNSD have their own
runners, ../run_suite.py and ../run_funsd.py).

    python -I run.py <corpus folder> --split heldout [--datasets rvl,cord,...] [--out bench_out/corpus]
                     [--score-only] [-v [N]]

What is scored, against each dataset's own labels:
  rvl           document type (16 RVL-CDIP classes; docintel's finer types are mapped onto them)
  sroie         receipt total, date and merchant
  cord          receipt total
  katanaml      invoice number, date, seller, buyer, total
  fatura        invoice total, number, date, due date
  invoice2data  invoice total, number, date
  gov           every filled-in value of real government forms (fillable and flattened copies)
  multi         every field and table cell of generated documents in 10 file formats

A fact that is wrong and still 'valid' is a SILENT error; one sent to review is flagged.
"""
import argparse
import json
import re
import sys
import tempfile
import time
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from docintel.normalize import parse_date  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("corpus")
ap.add_argument("--split", choices=["dev", "heldout"], required=True)
ap.add_argument("--datasets", default="rvl,sroie,cord,katanaml,fatura,invoice2data,gov,multi")
ap.add_argument("--out", default=str(ROOT / "bench_out" / "corpus"))
ap.add_argument("--score-only", action="store_true")
ap.add_argument("--workers", type=int, default=4)
ap.add_argument("-v", nargs="?", const=120, type=int, default=0)
args = ap.parse_args()
C = Path(args.corpus).resolve()
OUT = Path(args.out)
SPLIT = args.split
WANT = args.datasets.split(",")
items = [i for i in json.loads((C / "corpus.json").read_text()) if i["split"] == SPLIT and i["dataset"] in WANT]


def run_file(job):
    src, out_json = Path(job[0]), Path(job[1])
    from docintel.pipeline import process_file

    out_json.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    try:
        with tempfile.TemporaryDirectory() as t:
            docs = process_file(src, lambda k, n, g: {"doc_id": f"DOC_{k:03d}", "source_path": Path(t) / f"{k}.pdf"})
        res = {"ok": True, "seconds": round(time.time() - t0, 2), "docs": docs}
    except Exception as e:  # a crash is a finding, not a stop
        res = {"ok": False, "seconds": round(time.time() - t0, 2), "error": repr(e), "trace": traceback.format_exc()[-2000:]}
    out_json.write_text(json.dumps(res), encoding="utf-8")
    return res["ok"]


if not args.score_only:
    jobs = [(i["file"], OUT / i["dataset"] / f"{i['id']}.json") for i in items]
    with ProcessPoolExecutor(args.workers) as ex:
        oks = list(ex.map(run_file, jobs))
    print(f"{len(oks)} processed, {oks.count(False)} crashed")

RVL_MAP = {"letter": "letter", "form": "form", "email": "email", "memo": "memo", "resume": "resume",
           "news article": "news article", "scientific publication": "scientific publication",
           "report": "scientific report", "specification": "specification", "budget": "budget", "invoice": "invoice",
           "receipt": "invoice", "presentation": "presentation", "questionnaire": "questionnaire",
           "advertisement": "advertisement", "tax form": "form", "fax cover sheet": "form", "press release": "news article", "insurance": "form", "bank statement": "form",
           "payslip": "form", "lab report": "scientific report", "purchase order": "invoice", "utility bill": "invoice",
           "meeting minutes": "memo", "contract": "letter", "referral": "letter", "prescription": "form",
           "discharge summary": "scientific report", "patient intake": "form"}


def digits(s):
    return re.sub(r"\D", "", str(s or ""))


def amount_eq(a, b):
    da, db = digits(a), digits(b)
    if not da or not db:
        return False
    return da == db or da.rstrip("0") == db.rstrip("0")


def date_eq(a, b):
    sa = {x for o in ("mdy", "dmy") for x in [parse_date(str(a), o)] if x} | ({str(a)} if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(a)) else set())
    sb = {x for o in ("mdy", "dmy") for x in [parse_date(str(b), o)] if x} | ({str(b)} if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(b)) else set())
    if sa & sb:
        return True
    return digits(a) and digits(a) == digits(b)


def norm(s):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).split())


def text_eq(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    return SequenceMatcher(None, na, nb).ratio() >= 0.8 or (len(na) >= 5 and (na in nb or nb in na))


def fact_score(c, kf, fact, truth, eq, tag):
    if truth in (None, ""):
        return
    c[f"{tag}_n"] += 1
    f = kf.get(fact)
    if not f:
        c[f"{tag}_missed"] += 1
        return "missed"
    ok = eq(f.get("raw") or f["value"], truth) or eq(f["value"], truth)
    if ok:
        c[f"{tag}_ok"] += 1
        return "ok"
    silent = f.get("status") == "valid"
    c[f"{tag}_wrong_{'silent' if silent else 'flagged'}"] += 1
    return ("WRONG-SILENT " if silent else "wrong-flagged ") + f"{f['value']!r} vs {truth!r} ({f.get('label')})"


def sim(a, b):
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def fields_score(c, doc, fields, table, details, did):
    attrs = [a for e in doc["entities"].values() if e["type"] != "Section" for a in e["attributes"].values()]
    for label, value in fields.items():
        c["f_n"] += 1
        cands = [a for a in attrs if a.get("field_label") and sim(a["field_label"], label) >= 0.85]
        good = lambda a: norm(a.get("value")) == norm(value) or norm(a.get("raw")) == norm(value) or date_eq(a.get("value"), value) and re.search(r"\d", str(value))
        if cands and any(good(a) for a in cands):
            c["f_ok"] += 1
        elif cands:
            silent = cands[0].get("status") == "valid"
            c[f"f_wrong_{'silent' if silent else 'flagged'}"] += 1
            details.append((did, "field wrong" + (" SILENT" if silent else ""), label, value, cands[0].get("value")))
        else:
            other = [a for a in attrs if good(a)]
            if other:
                silent = other[0].get("status") == "valid"
                c[f"f_mislabel_{'silent' if silent else 'flagged'}"] += 1
                details.append((did, "mislabelled" + (" SILENT" if silent else ""), label, value, other[0].get("field_label")))
            else:
                c["f_missed"] += 1
                details.append((did, "missed", label, value, None))
    if table:
        rows = [e for e in doc["entities"].values() if e["type"] in ("TableRow", "Medication")]
        used = set()
        for r in table["rows"]:  # rows matched in order, each used once (row keys can repeat)
            match = next((e for e in rows if e["id"] not in used and any(norm(r[0]) in (norm(a.get("value")), norm(a.get("raw"))) for a in e["attributes"].values())), None)
            if match is not None:
                used.add(match["id"])
            for h, cell in zip(table["headers"], r):
                c["c_n"] += 1
                if match is None:
                    c["c_missed"] += 1
                    details.append((did, "cell missed (no row)", h, cell, r[0]))
                    continue
                a = next((a for a in match["attributes"].values() if sim(a.get("field_label") or "", h) >= 0.8), None)
                if a is None:
                    c["c_missed"] += 1
                    details.append((did, "cell missed (no column)", h, cell, r[0]))
                elif norm(a.get("value")) == norm(cell) or norm(a.get("raw")) == norm(cell) or date_eq(a.get("value"), cell):
                    c["c_ok"] += 1
                else:
                    silent = a.get("status") == "valid"
                    c[f"c_wrong_{'silent' if silent else 'flagged'}"] += 1
                    details.append((did, "cell wrong" + (" SILENT" if silent else ""), h, cell, a.get("value")))


stats = defaultdict(Counter)
details = []
types = defaultdict(Counter)
for it in items:
    ds = it["dataset"]
    jf = OUT / ds / f"{it['id']}.json"
    if not jf.exists() or ds in ("suite", "funsd"):
        continue
    res = json.loads(jf.read_text())
    c = stats[ds]
    c["docs"] += 1
    c["seconds"] += res["seconds"]
    if not res["ok"]:
        c["crash"] += 1
        details.append((it["id"], "CRASH", res.get("error"), "", ""))
        continue
    doc = res["docs"][0]
    dtype = doc["document"].get("document_type")
    kf = doc.get("key_facts") or {}
    types[ds][dtype] += 1
    if ds == "rvl":
        truth = next(r for r in json.load(open(C / "rvl" / "manifest.json")) if Path(r["file"]).stem == it["id"])["category"]
        pred = RVL_MAP.get(dtype or "", None)
        if dtype in (None, "unknown") and "almost no text" in (doc["document"].get("document_type_basis") or ""):
            pred = "file folder"
        c["type_n"] += 1
        c["type_ok"] += pred == truth
        types["rvl_confusion"][(truth, pred)] += 1
    elif ds == "sroie":
        t = json.loads((C / "sroie" / "repo" / "data" / "key" / f"{it['id']}.json").read_text())
        c["type_n"] += 1
        c["type_ok"] += dtype in ("receipt", "invoice")
        for fact, key, eq in (("total", "total", amount_eq), ("date", "date", date_eq), ("merchant", "company", text_eq)):
            r = fact_score(c, kf, fact, t.get(key), eq, fact)
            if r and r != "ok":
                details.append((it["id"], fact, r, "", ""))
    elif ds == "cord":
        t = next(r for r in json.load(open(C / "cord" / "manifest.json")) if Path(r["file"]).stem == it["id"])["truth"]
        c["type_n"] += 1
        c["type_ok"] += dtype in ("receipt", "invoice")
        tot = (t.get("total") or {}).get("total_price")
        r = fact_score(c, kf, "total", tot, amount_eq, "total")
        if r and r != "ok":
            details.append((it["id"], "total", r, "", ""))
    elif ds == "katanaml":
        t = next(r for r in json.load(open(C / "katanaml" / "manifest.json")) if Path(r["file"]).stem == it["id"])["truth"]
        c["type_n"] += 1
        c["type_ok"] += dtype == "invoice"
        h, s = t.get("header", {}), t.get("summary", {})
        for fact, val, eq in (("invoice_number", h.get("invoice_no"), lambda a, b: digits(a) == digits(b) and bool(digits(b))),
                              ("invoice_date", h.get("invoice_date"), date_eq), ("seller", h.get("seller"), text_eq),
                              ("buyer", h.get("client"), text_eq), ("total", s.get("total_gross_worth"), amount_eq)):
            r = fact_score(c, kf, fact, val, eq, fact)
            if r and r != "ok":
                details.append((it["id"], fact, r, "", ""))
    elif ds == "fatura":
        m = next(r for r in json.load(open(C / "fatura" / "manifest.json")) if Path(r["file"]).stem == it["id"])
        groups = defaultdict(list)
        for tok, tag in zip(m["tokens"], m["ner_tags"]):
            groups[tag].append(tok)
        c["type_n"] += 1
        c["type_ok"] += dtype == "invoice"

        def tagval(tag, rx):
            vals = [t for t in groups.get(tag, []) if re.search(rx, t)]
            return vals[0] if vals else None
        for fact, val, eq in (("total", tagval(1, r"\d"), amount_eq), ("invoice_date", tagval(3, r"\d"), date_eq),
                              ("due_date", tagval(4, r"\d"), date_eq),
                              ("invoice_number", tagval(12, r"\d"), lambda a, b: norm(a).replace(" ", "") == norm(b).replace(" ", ""))):
            r = fact_score(c, kf, fact, val, eq, fact)
            if r and r != "ok":
                details.append((it["id"], fact, r, "", ""))
    elif ds == "invoice2data":
        t = json.loads(Path(it["file"]).with_suffix(".json").read_text())
        t = t[0] if isinstance(t, list) else t
        c["type_n"] += 1
        c["type_ok"] += dtype == "invoice"
        for fact, val, eq in (("total", t.get("amount"), amount_eq), ("invoice_date", t.get("date"), date_eq),
                              ("invoice_number", t.get("invoice_number"), lambda a, b: norm(a).replace(" ", "") == norm(b).replace(" ", ""))):
            r = fact_score(c, kf, fact, val, eq, fact)
            if r and r != "ok":
                details.append((it["id"], fact, r, "", ""))
    elif ds == "gov":
        truth = json.loads(Path(it["file"]).with_suffix(".truth.json").read_text())
        attrs = [(e, a) for e in doc["entities"].values() for a in e["attributes"].values() if a.get("bbox")]
        for t in truth:
            c["g_n"] += 1
            x0, top, x1, bottom = t["rect"]
            here = [(e, a) for e, a in attrs if a.get("page") == t["page"]
                    and x0 - 3 <= (a["bbox"][0] + a["bbox"][2]) / 2 <= x1 + 3 and top - 3 <= (a["bbox"][1] + a["bbox"][3]) / 2 <= bottom + 3]
            good = [(e, a) for e, a in here if norm(a.get("value")) == norm(t["value"]) or norm(a.get("raw")) == norm(t["value"])
                    or date_eq(a.get("value"), t["value"]) and "/" in t["value"] or amount_eq(a.get("value"), t["value"]) and re.search(r"\d,\d|\.\d\d$", t["value"])]
            if good:
                c["g_ok"] += 1
                lab = norm(good[0][1].get("field_label"))
                words = {w for w in lab.split() if len(w) > 2}
                if words & set(norm(t["tooltip"] + " " + t["name"]).split()):
                    c["g_label_ok"] += 1
            elif here:
                silent = here[0][1].get("status") == "valid"
                c[f"g_wrong_{'silent' if silent else 'flagged'}"] += 1
                details.append((it["id"], "gov value wrong" + (" SILENT" if silent else ""), t["tooltip"][:40], t["value"], here[0][1].get("value")))
            else:
                c["g_missed"] += 1
    elif ds == "multi":
        tr = json.loads((C / "multi" / f"{it['id']}.truth.json").read_text())
        c["type_n"] += 1
        want = {"bank_statement": "bank statement", "utility_bill": "utility bill", "lab_report": "lab report",
                "discharge_summary": "discharge summary", "purchase_order": "purchase order", "minutes": "meeting minutes"}.get(tr["type"], tr["type"])
        c["type_ok"] += dtype == want
        types["multi_confusion"][(want, dtype)] += 1
        fields_score(c, doc, tr["fields"], tr["table"], details, it["id"])

for ds, c in sorted(stats.items()):
    line = f"{ds:13} docs {c['docs']:4}  crash {c['crash']}  s/doc {c['seconds'] / max(1, c['docs']):.1f}"
    if c["type_n"]:
        line += f"  type {c['type_ok']}/{c['type_n']} ({c['type_ok'] / c['type_n']:.0%})"
    for tag in ("total", "date", "merchant", "invoice_number", "invoice_date", "due_date", "seller", "buyer"):
        if c[f"{tag}_n"]:
            line += (f"  {tag} {c[tag + '_ok']}/{c[tag + '_n']} (silent {c[tag + '_wrong_silent']}, flag {c[tag + '_wrong_flagged']}, "
                     f"miss {c[tag + '_missed']})")
    if c["g_n"]:
        line += (f"  values {c['g_ok']}/{c['g_n']} ({c['g_ok'] / c['g_n']:.0%}) labels {c['g_label_ok']}/{c['g_ok']}"
                 f"  SILENT {c['g_wrong_silent']} flagged {c['g_wrong_flagged']} missed {c['g_missed']}")
    if c["f_n"]:
        line += (f"  fields {c['f_ok']}/{c['f_n']} ({c['f_ok'] / c['f_n']:.0%}) cells {c['c_ok']}/{c['c_n']}"
                 f"  SILENT {c['f_wrong_silent'] + c['f_mislabel_silent'] + c['c_wrong_silent']}"
                 f" flagged {c['f_wrong_flagged'] + c['f_mislabel_flagged'] + c['c_wrong_flagged']} missed {c['f_missed']}")
    print(line)
if args.v:
    for k, v in types.items():
        if "confusion" in k:
            print(k)
            for (t, p), n in sorted(v.items(), key=lambda x: -x[1])[:40]:
                print(f"   {n:3}  truth={t:24} predicted={p}")
        else:
            print(k, dict(v))
    for d in details[:args.v]:
        print("  ", d)
