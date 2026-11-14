from pathlib import Path

import pytest

from docintel.pipeline import process_pdf

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples" / "input"


@pytest.fixture(scope="session")
def samples_dir() -> Path:
    return SAMPLES


@pytest.fixture(scope="session")
def processed(tmp_path_factory):
    """Process every bundled sample once per test session."""
    out = tmp_path_factory.mktemp("processed")
    docs = {}
    for i, name in enumerate(["A_fillable_okafor", "B_flattened_lindqvist", "C_other_clinic_rivera",
                              "D_scanned_rivera"], start=1):
        doc_id = f"DOC_{i:03d}"
        # the scanned packet is processed without OCR here; tests/test_ocr.py covers OCR
        docs[name[0]] = process_pdf(SAMPLES / f"intake_{name}.pdf", doc_id, ocr=False if name[0] == "D" else "auto",
                                    standardized_path=out / f"{doc_id}_standardized.pdf")
    docs["_out"] = out
    return docs


def ent_by(doc, etype, label):
    return next(e for e in doc["entities"].values() if e["type"] == etype and e["label"] == label)


def rels(doc, predicate=None, subject=None, obj=None):
    return [r for r in doc["relationships"]
            if (predicate is None or r["predicate"] == predicate)
            and (subject is None or r["subject"] == subject)
            and (obj is None or r["object"] == obj)]
