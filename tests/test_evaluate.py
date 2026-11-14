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


def test_value_helpers():
    from docintel.bind import date_hint, name_hint
    from docintel.normalize import middle_initial, none_answer, normalise, split_dose_frequency

    assert split_dose_frequency("50 mg once daily") == ("50 mg", "once daily", True)
    assert split_dose_frequency("1 tablet twice a day")[:2] == ("1 tablet", "twice a day")
    assert split_dose_frequency("as directed")[2] is False  # cannot be split: reviewed
    assert none_answer("NKDA") == "no known drug allergies" and none_answer("Penicillin") is None
    assert date_hint("Date of Birth (DD/MM/YYYY)") == "dmy" and date_hint("DOB (MM-DD-YY)") == "mdy"
    assert name_hint("Name (Last, First, MI)") == "last_first" and name_hint("Name") is None
    assert middle_initial("Rivera, Maria L.") == "L" and middle_initial("Mary Ann Smith") is None
    assert normalise("F M", "sex") == ("f m", False)  # two answers are not a sex
    assert normalise("Married", "marital") == ("married", True)
    assert normalise("Chicago", "marital")[1] is False
    assert normalise("900 12 3456", "ssn") == ("900-12-3456", True)


def test_choice_value_doubts():
    from docintel.bind import choice_value
    from docintel.models import Token

    def toks(spec):
        out, x = [], 100.0
        for text in spec.split():
            box = text in ("[X]", "[]")
            t = Token("[X]" if text == "[X]" else ("[ ]" if box else text), x, 100, x + (8 if box else 6 * len(text)),
                      110, 1, "text", kind="checkbox" if box else "word", checked=text == "[X]")
            out.append(t)
            x = t.x1 + (3 if box else 14)
        return out

    assert choice_value(toks("[] F [X] M"))[0] == "M"
    text, _, problems = choice_value(toks("[] F [] M"))
    assert text is None and "none of the options" in problems[0]
    text, _, problems = choice_value(toks("[X] F [X] M"))
    assert text == "F, M" and "2 options are ticked" in problems[0]
