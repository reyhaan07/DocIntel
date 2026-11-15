"""Turn the fetched datasets into the corpus: images and truth per dataset, the filled
government forms, the generated multi-format documents, and one manifest
(corpus.json) that fixes every document's split - decided by position, before any
result is looked at.

    python -I prepare.py <corpus folder> [<ocr_test_suite_200 folder>]

Needs pyarrow (to read the parquet files) and, for the generated documents, pandoc and
LibreOffice (soffice).  Run fetch.sh first.
"""
import csv
import io
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
C = Path(sys.argv[1]).resolve()
SUITE = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None
RVL = ["letter", "form", "email", "handwritten", "advertisement", "scientific report", "scientific publication",
       "specification", "file folder", "news article", "budget", "invoice", "presentation", "questionnaire", "resume",
       "memo"]


def parquet_sets():
    import pyarrow.parquet as pq
    from PIL import Image

    def save(raw, path):
        Image.open(io.BytesIO(raw)).convert("RGB").save(path)

    (C / "rvl").mkdir(exist_ok=True)
    man = []
    for i, r in enumerate(pq.read_table(C / "hf" / "rvl_test.parquet").to_pylist()):
        name = f"rvl_{i:03d}.png"
        save(r["image"]["bytes"], C / "rvl" / name)
        man.append({"file": name, "category": RVL[r["label"]], "split": "dev" if i % 2 == 0 else "heldout"})
    (C / "rvl" / "manifest.json").write_text(json.dumps(man, indent=0))
    for ds, n in (("cord", 100), ("katanaml", 26)):
        (C / ds).mkdir(exist_ok=True)
        man = []
        for i, r in enumerate(pq.read_table(C / "hf" / f"{ds}_test.parquet").to_pylist()[:n]):
            name = f"{ds}_{i:03d}.png"
            save(r["image"]["bytes"], C / ds / name)
            gt = json.loads(r["ground_truth"])
            man.append({"file": name, "truth": gt.get("gt_parse", gt), "split": "dev" if i % 2 == 0 else "heldout"})
        (C / ds / "manifest.json").write_text(json.dumps(man, indent=0))
    (C / "fatura").mkdir(exist_ok=True)
    man = []
    for i, r in enumerate(pq.read_table(C / "hf" / "fatura_test.parquet").slice(0, 100).to_pylist()):
        name = f"fatura_{i:03d}.png"
        save(r["image"]["bytes"], C / "fatura" / name)
        man.append({"file": name, "tokens": r["tokens"], "ner_tags": r["ner_tags"], "bboxes": r["bboxes"],
                    "split": "dev" if i % 2 == 0 else "heldout"})
    (C / "fatura" / "manifest.json").write_text(json.dumps(man))


def manifest():
    items = []
    if SUITE:
        for r in csv.DictReader(open(SUITE / "manifest.csv", encoding="utf-8-sig")):
            n = int(r["case_id"].rsplit("-", 1)[1])
            items.append({"dataset": "suite", "id": r["case_id"], "file": str(SUITE / r["image_path"]),
                          "split": "dev" if n % 2 else "heldout"})
    for sub, split in (("training_data", "dev"), ("testing_data", "heldout")):
        for p in sorted((C / "funsd" / "dataset" / sub / "images").glob("*.png")):
            items.append({"dataset": "funsd", "id": p.stem, "file": str(p), "split": split})
    for ds in ("rvl", "cord", "katanaml", "fatura"):
        for r in json.load(open(C / ds / "manifest.json")):
            items.append({"dataset": ds, "id": Path(r["file"]).stem, "file": str(C / ds / r["file"]), "split": r["split"]})
    for i, stem in enumerate((HERE / "sroie_pick.txt").read_text().split()):
        items.append({"dataset": "sroie", "id": stem, "file": str(C / "sroie" / "repo" / "data" / "img" / f"{stem}.jpg"),
                      "split": "dev" if i % 2 == 0 else "heldout"})
    for i, p in enumerate(sorted((C / "invoice2data" / "repo" / "tests" / "compare").glob("*.pdf"))):
        items.append({"dataset": "invoice2data", "id": p.stem, "file": str(p), "split": "dev" if i % 2 == 0 else "heldout"})
    forms = sorted({p.name.rsplit("_", 1)[0] for p in (C / "gov").glob("gov_*.pdf")})
    for p in sorted((C / "gov").glob("gov_*.pdf")):
        k = forms.index(p.name.rsplit("_", 1)[0])  # both copies of a form fall in the same half
        items.append({"dataset": "gov", "id": p.stem, "file": str(p), "split": "dev" if k % 2 == 0 else "heldout"})
    for t in sorted((C / "multi").glob("*.truth.json")):
        stem = t.name[:-len(".truth.json")]
        f = next(p for p in (C / "multi").glob(stem + ".*") if not p.name.endswith(".truth.json"))
        items.append({"dataset": "multi", "id": stem, "file": str(f), "split": json.loads(t.read_text())["split"]})
    (C / "corpus.json").write_text(json.dumps(items, indent=0))
    from collections import Counter
    print(len(items), "documents", dict(Counter(i["dataset"] for i in items)), dict(Counter(i["split"] for i in items)))


if __name__ == "__main__":
    parquet_sets()
    (C / "gov").mkdir(exist_ok=True)
    subprocess.run([sys.executable, "-I", str(HERE / "gov_fill.py"), str(C / "govraw"), str(C / "gov")], check=True)
    (C / "multi").mkdir(exist_ok=True)
    subprocess.run([sys.executable, "-I", str(HERE / "multi_gen.py"), str(C / "multi")], check=True)
    manifest()
