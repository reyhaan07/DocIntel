"""Layouts and conditions that commonly break document readers (samples/stress).

Each test states by hand what a correct reading must contain; the ground-truth suite
then checks every value and link and requires zero silent errors."""
from pathlib import Path

import pytest

from conftest import ent_by, rels
from docintel import ocr
from docintel.evaluate import evaluate_folder
from docintel.pipeline import process_file, process_pdf

STRESS = Path(__file__).resolve().parents[1] / "samples" / "stress"
needs_engine = pytest.mark.skipif(not ocr.available(), reason="tesseract OCR engine not installed")


def _field(doc, label):
    return next(e for e in doc["entities"].values() if e["type"] == "Field" and e["label"] == label)


def _files(tmp_path, name):
    return process_file(STRESS / name, lambda k, n, g: {"doc_id": f"DOC_{k:03d}", "source_path": tmp_path / f"{k}.pdf",
                                                        "standardized_path": tmp_path / f"{k}_std.pdf"})


@pytest.fixture(scope="module")
def tight():
    return process_pdf(STRESS / "intake_F_tight_labels.pdf", ocr=False)


def test_qualified_labels_are_not_the_patients(tight):
    pat = tight["entities"]["PAT_001"]["attributes"]
    assert pat["phone"]["value"] == "(812) 555-0134"  # Home Phone, not Work Phone
    assert _field(tight, "Work Phone")["attributes"]["value"]["value"] == "(812) 555-0199"
    assert tight["entities"]["EMC_001"]["attributes"]["phone"]["value"] == "(812) 555-0135"
    assert _field(tight, "Alt Phone")["section"] == "Emergency Contact"
    issues = {i["target"] for c in tight["validation"]["checks"] if c["check_id"] == "text_coverage" for i in c["issues"]}
    assert _field(tight, "Work Phone")["id"] in issues  # reported, not silently kept


def test_single_spaced_labels_and_second_address_line(tight):
    pat = tight["entities"]["PAT_001"]["attributes"]
    assert (pat["city"]["value"], pat["state"]["value"], pat["zip"]["value"]) == ("Bloomington", "IN", "47401")
    assert pat["address"]["value"] == "1450 North Walnut Street Unit 12"
    assert pat["address"]["status"] == "needs_review"  # joined lines are confirmed by a person


def test_labels_printed_before_their_boxes(tight):
    cons = {e["consent_key"]: e["attributes"]["decision"]["value"]
            for e in tight["entities"].values() if e["type"] == "Consent"}
    assert cons == {"voicemail": "yes", "text_message": "no", "email": "yes"}


def test_row_without_prescriber_is_reported(tight):
    aspirin = ent_by(tight, "Medication", "Aspirin")
    assert not rels(tight, "PRESCRIBED_BY", aspirin["id"])
    assert any(m["entity"] == aspirin["id"] for m in tight["missing"])


def test_two_patients_in_one_file_are_split(tmp_path):
    docs = _files(tmp_path, "intake_G_two_packets.pdf")
    assert len(docs) == 2
    first, second = docs
    assert first["entities"]["PAT_001"]["label"] == "Maria Rivera"
    assert second["entities"]["PAT_001"]["label"] == "Erik Lindqvist"
    assert {e["label"] for e in first["entities"].values() if e["type"] == "Medication"} == \
        {"Metformin", "Lisinopril", "Sertraline", "Vitamin D3"}
    assert {e["label"] for e in second["entities"].values() if e["type"] == "Medication"} == {"Levothyroxine", "Cetirizine"}
    assert second["document"]["packet"] == {"index": 2, "count": 2, "source_file": "intake_G_two_packets.pdf",
                                            "source_pages": [3, 4, 5],
                                            "source_sha256": second["document"]["packet"]["source_sha256"]}
    assert second["document"]["page_count"] == 3 and (tmp_path / "2.pdf").exists()
    # read as one document anyway, the mix is an error, never a silent merge
    whole = process_pdf(STRESS / "intake_G_two_packets.pdf", ocr=False)
    assert any(e["check"] == "single_packet" for e in whole["validation"]["errors"])


def test_day_first_dates_are_recognised_from_the_document():
    doc = process_pdf(STRESS / "referral_H_eu_letter.pdf", ocr=False)
    assert _field(doc, "Date")["attributes"]["value"]["value"] == "2026-03-14"
    assert _field(doc, "Date of Birth")["attributes"]["value"]["value"] == "1980-04-05"  # 5 April, not May 4
    assert _field(doc, "NHS Number")["attributes"]["value"]["value"] == "943 476 5919"  # an ID, not a phone
    text = [b for b in doc["blocks"] if b["type"] == "text"]
    assert any("palpitations" in b["text"] and "further investigation" in b["text"] for b in text)
    assert [b["type"] for b in doc["blocks"]][:2] == ["heading", "text"]


def test_ambiguous_dates_without_evidence_are_reviewed(tmp_path):
    from reportlab.pdfgen import canvas

    pdf = tmp_path / "ambiguous.pdf"
    c = canvas.Canvas(str(pdf))
    c.setFont("Helvetica-Bold", 12)
    c.drawString(54, 760, "VISIT NOTE")
    c.setFont("Helvetica", 10)
    c.drawString(54, 730, "Visit Date: 03/04/2026")
    c.drawString(54, 714, "Follow-up: 05/06/2026")
    c.save()
    doc = process_pdf(pdf, ocr=False)
    visit = _field(doc, "Visit Date")["attributes"]["value"]
    assert visit["status"] == "needs_review" and "day-first or month-first" in visit["notes"][0]


def test_labels_above_boxes_and_a_table_over_two_pages():
    doc = process_pdf(STRESS / "screening_I_stacked_two_pages.pdf", ocr=False)
    assert _field(doc, "Full name")["attributes"]["value"]["value"] == "Priya Raman"
    assert _field(doc, "Mobile")["attributes"]["value"]["value"] == "(312) 555-0172"
    rows = [e for e in doc["entities"].values() if e["type"] == "TableRow"]
    assert [r["label"] for r in rows][-3:] == ["MMR", "Varicella", "COVID-19 booster"]
    assert [r["row"] for r in rows] == list(range(1, 9))
    assert len([e for e in doc["entities"].values() if e["type"] == "Section" and e["label"] == "Vaccinations"]) == 1
    furniture = [b for b in doc["blocks"] if b["type"] == "page_furniture"]
    assert {b["page"] for b in furniture} == {1, 2}  # running header and footer, never data
    assert doc["summary"]["validation_errors"] == 0


def test_fillable_fields_without_printed_labels():
    doc = process_pdf(STRESS / "order_M_fillable_unlabeled.pdf", ocr=False)
    got = {e["label"]: e["attributes"]["value"]["value"] for e in doc["entities"].values() if e["type"] == "Field"}
    assert got == {"Customer name": "Riverside Family Clinic", "Account number": "RFC-00912",
                   "Deliver by date": "2026-12-01", "Contact phone": "(217) 555-0100"}


def test_encrypted_pdf_opens(tmp_path):
    doc = _files(tmp_path, "intake_L_encrypted.pdf")[0]
    assert doc["entities"]["PAT_001"]["label"] == "Thomas Becker"


@needs_engine
def test_sideways_photo_is_turned_upright(tmp_path):
    doc = _files(tmp_path, "photo_J_sideways.png")[0]
    page = doc["document"]["pages"][0]
    assert page["rotation"] == 90 and page["height"] > page["width"]
    assert doc["entities"]["PAT_001"]["attributes"]["date_of_birth"]["value"] == "1964-08-19"
    assert (tmp_path / "1.pdf").exists()  # the upright PDF used for viewing


@needs_engine
def test_garbage_text_layer_is_replaced_by_ocr(tmp_path):
    doc = _files(tmp_path, "scan_K_bad_text_layer.pdf")[0]
    assert doc["document"]["pages"][0]["text_layer"] == "unreadable"
    assert doc["document"]["extraction_method"] == "ocr"
    assert doc["entities"]["PAT_001"]["label"] == "Thomas Becker"


def test_stress_suite_has_no_silent_errors():
    rep = evaluate_folder(STRESS, STRESS / "ground_truth", ocr="auto" if ocr.available() else False)
    for d in rep["documents"]:
        if not ocr.available() and d["document"].startswith(("photo_J", "scan_K")):
            continue
        assert d["silent_errors"] == 0, (d["document"], d["details"])
