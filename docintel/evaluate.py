"""Accuracy against ground truth - the yardstick on the way to 100 %.

A ground-truth file lists, for one PDF, every value and every relationship that a
perfect reading would produce.  Entities are addressed by meaning, not by ID
(``Medication[Sertraline].dosage``), so files survive changes in numbering.

The headline number is **silent errors**: a wrong value, an invented value or
link, or a missed value that the system did *not* flag for review.  A flagged
mistake costs a reviewer a click; a silent one reaches the record.  The goal is
zero silent errors first, then fewer flags.

    python -m docintel evaluate samples/input --truth samples/ground_truth
    python -m docintel truth output/DOC_003.json -o samples/ground_truth/my_doc.json
"""
from __future__ import annotations

import json
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

SINGLETONS = {"Patient", "Spouse", "EmergencyContact"}


# --------------------------------------------------------------------------- addressing
def entity_keys(doc: dict) -> dict[str, str]:
    """Entity ID -> stable key by meaning: 'Patient', 'Medication[Sertraline]', 'Field[DOB @ Patient]'."""
    ents = doc["entities"]
    counts = Counter((e["type"], e["label"]) for e in ents.values())
    out = {}
    for eid, e in ents.items():
        if e["type"] in SINGLETONS:
            out[eid] = e["type"]
        elif counts[(e["type"], e["label"])] > 1:
            out[eid] = f"{e['type']}[{e['label']} @ {e.get('section') or ''}]"
        else:
            out[eid] = f"{e['type']}[{e['label']}]"
    # keys must be unique; fall back to the row/order when a section repeats a label
    seen = Counter(out.values())
    for eid, k in list(out.items()):
        if seen[k] > 1:
            e = ents[eid]
            out[eid] = f"{k}#{e.get('row') or eid}"
    return out


def to_truth(doc: dict) -> dict:
    """Export a document's result as a ground-truth file (after a person has checked it)."""
    keys = entity_keys(doc)
    values = {}
    for eid, e in doc["entities"].items():
        for attr, a in e["attributes"].items():
            values[f"{keys[eid]}.{attr}"] = a.get("value")
    rels = sorted([keys.get(r["subject"], r["subject"]), r["predicate"], keys.get(r["object"], r["object"])]
                  for r in doc["relationships"])
    return {"document": doc["document"]["filename"], "document_type": doc["document"]["document_type"],
            "values": dict(sorted(values.items())), "relationships": rels}


def _norm(v) -> str:
    if v is None:
        return "<none>"
    if isinstance(v, list):
        return "|".join(sorted(_norm(x) for x in v))
    return re.sub(r"[^a-z0-9%$<>]", "", str(v).lower())


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


# --------------------------------------------------------------------------- comparison
def compare(doc: dict, truth: dict) -> dict:
    keys = entity_keys(doc)
    ents = doc["entities"]
    truth_entities = {k.rsplit(".", 1)[0] for k in truth["values"]}
    doc_by_key = {k: eid for eid, k in keys.items()}
    # map doc entities onto truth entities: exact key, else the most similar label of the same type
    mapping: dict[str, str] = {}
    for tk in truth_entities:
        if tk in doc_by_key:
            mapping[tk] = doc_by_key[tk]
    free = {eid for eid in ents if eid not in mapping.values()}
    for tk in sorted(truth_entities - set(mapping)):
        ttype = tk.split("[", 1)[0]
        tlabel = tk[len(ttype) + 1:-1] if "[" in tk else ""
        cands = [(eid, _similar(ents[eid]["label"], tlabel)) for eid in free if ents[eid]["type"] == ttype]
        cands = [c for c in cands if c[1] >= 0.75]
        if cands:
            eid = max(cands, key=lambda c: c[1])[0]
            mapping[tk] = eid
            free.discard(eid)
    rev = {eid: tk for tk, eid in mapping.items()}

    reported = set()
    for item in doc.get("review_queue", []):
        for f in ("target", "entity", "subject", "object"):
            if item.get(f):
                reported.add(str(item[f]).split(".")[0])
    for m in doc.get("missing", []):
        if m.get("entity"):
            reported.add(m["entity"])

    res = Counter()
    details = {"wrong": [], "missed": [], "extra": [], "rel_missed": [], "rel_extra": []}
    for tkey, tval in truth["values"].items():
        ek, attr = tkey.rsplit(".", 1)
        eid = mapping.get(ek)
        a = ents[eid]["attributes"].get(attr) if eid else None
        res["values"] += 1
        if a is None:
            silent = not (eid and eid in reported)
            res["missed_silent" if silent else "missed_reported"] += 1
            details["missed"].append({"key": tkey, "expected": tval, "reported": not silent})
        elif _norm(a.get("value")) == _norm(tval):
            res["correct"] += 1
            if a.get("status") != "valid":
                res["correct_flagged"] += 1
        else:
            silent = a.get("status") == "valid"
            res["wrong_silent" if silent else "wrong_flagged"] += 1
            details["wrong"].append({"key": tkey, "expected": tval, "got": a.get("value"), "flagged": not silent})
    for eid, e in ents.items():
        tk = rev.get(eid, keys[eid])
        for attr, a in e["attributes"].items():
            if f"{tk}.{attr}" not in truth["values"]:
                silent = a.get("status") == "valid"
                res["extra_silent" if silent else "extra_flagged"] += 1
                details["extra"].append({"key": f"{tk}.{attr}", "got": a.get("value"), "flagged": not silent})

    truth_rels = {tuple(r) for r in truth["relationships"]}
    got = {}
    for r in doc["relationships"]:
        got[(rev.get(r["subject"], keys.get(r["subject"])), r["predicate"], rev.get(r["object"], keys.get(r["object"])))] = r
    for t in truth_rels:
        if t in got:
            res["rel_correct"] += 1
        else:
            res["rel_missed"] += 1
            details["rel_missed"].append(list(t))
    for t, r in got.items():
        if t not in truth_rels:
            silent = r["support"] == "explicit"
            res["rel_extra_silent" if silent else "rel_extra_flagged"] += 1
            details["rel_extra"].append({"relationship": list(t), "id": r["relationship_id"], "flagged": not silent})
    res["relationships"] = len(truth_rels)

    silent = res["wrong_silent"] + res["missed_silent"] + res["extra_silent"] + res["rel_extra_silent"]
    flagged = res["wrong_flagged"] + res["missed_reported"] + res["extra_flagged"] + res["rel_extra_flagged"]
    return {
        "document": doc["document"]["filename"],
        "status": doc["document"]["status"],
        "value_accuracy": round(res["correct"] / res["values"], 4) if res["values"] else 1.0,
        "relationship_recall": round(res["rel_correct"] / res["relationships"], 4) if res["relationships"] else 1.0,
        "silent_errors": silent,
        "flagged_errors": flagged,
        "counts": dict(res),
        "details": details,
    }


def evaluate_folder(input_dir: str | Path, truth_dir: str | Path, ocr="auto") -> dict:
    from .pipeline import process_pdf

    input_dir, truth_dir = Path(input_dir), Path(truth_dir)
    reports = []
    for pdf in sorted(input_dir.glob("*.pdf")):
        tfile = truth_dir / f"{pdf.stem}.json"
        if not tfile.exists():
            continue
        truth = json.loads(tfile.read_text(encoding="utf-8"))
        doc = process_pdf(pdf, ocr=ocr)
        reports.append(compare(doc, truth))
    total = Counter()
    for r in reports:
        total.update(r["counts"])
    return {
        "documents": reports,
        "value_accuracy": round(total["correct"] / total["values"], 4) if total["values"] else 1.0,
        "relationship_recall": round(total["rel_correct"] / total["relationships"], 4) if total["relationships"] else 1.0,
        "silent_errors": sum(r["silent_errors"] for r in reports),
        "flagged_errors": sum(r["flagged_errors"] for r in reports),
        "values": total["values"],
        "relationships": total["relationships"],
    }
