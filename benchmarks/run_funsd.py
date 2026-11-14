"""Benchmark docintel's label -> value linking on FUNSD (scanned real-world forms).

FUNSD (https://guillaumejaume.github.io/FUNSD/) marks, by hand, every question/answer
entity on 199 noisy scanned forms and which answer belongs to which question.  Download
and unzip it, then:

    python benchmarks/run_funsd.py <FUNSD folder containing dataset/> --split heldout

training_data is the development split, testing_data the held-out split.  Pairs are
matched by position, so OCR spelling does not decide whether a link is right:
  correct          docintel's label lies on FUNSD question Q, its value on answer A, Q -> A linked
  wrong link       label on a question, value on an answer, not linked to each other
  label as value   the value lies on a FUNSD question or header
A table row relates its row label to each cell.  SILENT = docintel marked the pair valid.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from run_suite import run_one  # noqa: E402


def pairs(doc):
    out = []
    for e in doc["entities"].values():
        rowkey = None
        if e["type"] == "TableRow":
            rowkey = next((a for a in e["attributes"].values() if str(a.get("value")) == e["label"] and a.get("bbox")), None)
        for a in e["attributes"].values():
            if a.get("value") in (None, "") or not a.get("bbox"):
                continue
            if rowkey is not None:
                if a is not rowkey:
                    out.append((a, rowkey["bbox"]))
            elif a.get("label_bbox"):
                out.append((a, a["label_bbox"]))
    return out


def inter(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def area(a):
    return max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))


def best(box, ents):
    c = [(inter(box, e["box"]) / min(area(box), area(e["box"])), e) for e in ents]
    c = [x for x in c if x[0] >= 0.5]
    return max(c, key=lambda x: x[0])[1] if c else None


def score(root: Path, out: Path, split: str):
    from PIL import Image

    sub = "training_data" if split == "dev" else "testing_data"
    tot = Counter()
    for jf in sorted(out.glob("*.json")):
        res = json.loads(jf.read_text())
        ann = json.loads((root / "dataset" / sub / "annotations" / (jf.stem + ".json")).read_text())["form"]
        byid = {e["id"]: e for e in ann}
        ents = [e for e in ann if e["text"].strip()]
        qa = {(l[0], l[1]) for e in ann for l in e["linking"]
              if byid[l[0]]["label"] == "question" and byid[l[1]]["label"] == "answer"}
        tot["links"] += len(qa)
        tot["docs"] += 1
        if not res["ok"]:
            tot["crash"] += 1
            continue
        doc = res["docs"][0]
        s = Image.open(root / "dataset" / sub / "images" / (jf.stem + ".png")).size[0] / doc["document"]["pages"][0]["width"]
        found = set()
        for a, lbox in pairs(doc):
            if a.get("page") != 1:
                continue
            ve, le = best([v * s for v in a["bbox"]], ents), best([v * s for v in lbox], ents)
            silent = a.get("status") == "valid"
            if ve is None or le is None:
                continue
            if ve["label"] == "answer" and le["label"] == "question":
                if (le["id"], ve["id"]) in qa:
                    tot["correct"] += 1
                    found.add((le["id"], ve["id"]))
                else:
                    tot["wrong_silent" if silent else "wrong_flagged"] += 1
            elif ve["label"] in ("question", "header"):
                tot["labelval_silent" if silent else "labelval_flagged"] += 1
        tot["found"] += len(found)
    stated = tot["correct"] + sum(tot[k] for k in ("wrong_silent", "wrong_flagged", "labelval_silent", "labelval_flagged"))
    print(f"docs {tot['docs']}  crashes {tot['crash']}  FUNSD links {tot['links']}")
    print(f"recall {tot['found'] / max(1, tot['links']):.3f}  precision {tot['correct'] / max(1, stated):.3f}")
    print(f"SILENT: wrong link {tot['wrong_silent']}, label read as value {tot['labelval_silent']};"
          f"  flagged: {tot['wrong_flagged'] + tot['labelval_flagged']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("funsd")
    ap.add_argument("--split", choices=["dev", "heldout"], default="heldout")
    ap.add_argument("--out", default="bench_out/funsd")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--score-only", action="store_true")
    a = ap.parse_args(argv)
    root, out = Path(a.funsd), Path(a.out) / a.split
    out.mkdir(parents=True, exist_ok=True)
    if not a.score_only:
        sub = "training_data" if a.split == "dev" else "testing_data"
        jobs = [(p, out / (p.stem + ".json")) for p in sorted((root / "dataset" / sub / "images").glob("*.png"))]
        with ProcessPoolExecutor(a.workers) as ex:
            ok = list(ex.map(run_one, jobs))
        print(f"{len(ok)} processed, {ok.count(False)} crashed")
    score(root, out, a.split)


if __name__ == "__main__":
    main()
