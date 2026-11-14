"""Accuracy against ground truth. The first goal is zero silent errors."""
import copy

import pytest

from docintel import ocr
from docintel.evaluate import compare, evaluate_folder, to_truth

TRUTH = "samples/ground_truth"


def test_text_documents_are_exact(samples_dir):
    rep = evaluate_folder(samples_dir, TRUTH, ocr=False)
    by = {d["document"]: d for d in rep["documents"]}
    for name in ("intake_A_fillable_okafor.pdf", "intake_B_flattened_lindqvist.pdf",
                 "intake_C_other_clinic_rivera.pdf", "lab_report_harper.pdf", "invoice_northwind.pdf"):
        d = by[name]
        assert d["value_accuracy"] == 1.0 and d["relationship_recall"] == 1.0, d["details"]
        assert d["silent_errors"] == 0 and d["flagged_errors"] == 0, d["details"]


@pytest.mark.skipif(not ocr.available(), reason="tesseract OCR engine not installed")
def test_scans_have_no_silent_errors(samples_dir):
    rep = evaluate_folder(samples_dir, TRUTH)
    for d in rep["documents"]:
        assert d["silent_errors"] == 0, (d["document"], d["details"])
        assert d["value_accuracy"] >= 0.95 and d["relationship_recall"] >= 0.95
    assert rep["silent_errors"] == 0


def test_compare_separates_silent_from_flagged_errors(processed):
    doc = copy.deepcopy(processed["C"])
    truth = to_truth(processed["C"])
    assert compare(doc, truth)["silent_errors"] == 0
    sert = next(e for e in doc["entities"].values() if e["label"] == "Sertraline")
    sert["attributes"]["dosage"]["value"] = "500 mg"  # wrong and trusted -> silent
    rep = compare(doc, truth)
    assert rep["silent_errors"] == 1 and rep["counts"]["wrong_silent"] == 1
    sert["attributes"]["dosage"]["status"] = "needs_review"  # wrong but flagged -> caught
    rep = compare(doc, truth)
    assert rep["silent_errors"] == 0 and rep["flagged_errors"] == 1
    doc["relationships"].append(dict(doc["relationships"][0], relationship_id="REL_999", object="ALG_001",
                                     predicate="HAS_SPOUSE"))  # an invented explicit link -> silent
    assert compare(doc, truth)["counts"]["rel_extra_silent"] == 1
