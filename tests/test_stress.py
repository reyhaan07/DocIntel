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


# --------------------------------------------------------------------------- N: real-world variety
@pytest.fixture(scope="module")
def real():
    return process_pdf(STRESS / "intake_N_real_world.pdf", ocr=False)


def test_choices_ticked_inside_a_field(real):
    pat = real["entities"]["PAT_001"]["attributes"]
    assert pat["sex"]["value"] == "male" and pat["sex"]["status"] == "valid"  # "Sex: [ ] F [X] M"
    assert pat["marital_status"]["value"] == "married"  # "[ ] Single [X] Married [ ] Divorced [ ] Widowed"
    assert pat["sex"]["extraction_method"] == "layout_checkbox"


def test_symbol_font_check_boxes(real):
    # ZapfDingbats boxes: text extraction reads every glyph the same; the drawn glyph decides
    conds = {e["label"] for e in real["entities"].values() if e["type"] == "Condition"}
    assert conds == {"Asthma", "High cholesterol"}


def test_format_hints_in_labels(real):
    pat = real["entities"]["PAT_001"]["attributes"]
    assert pat["date_of_birth"]["value"] == "1975-02-28"  # "Date of Birth (MM/DD/YYYY):"
    assert pat["date_of_birth"]["field_label"] == "Date of Birth (MM/DD/YYYY)"
    # "Name (Last, First, MI): Nguyen, David T."
    assert (pat["first_name"]["value"], pat["last_name"]["value"], pat["middle_name"]["value"]) == ("David", "Nguyen", "T")


def test_real_world_sections_and_fields(real):
    assert real["document"]["status"] == "completed" and real["summary"]["review_items"] == 0
    pat = real["entities"]["PAT_001"]["attributes"]
    assert pat["ssn"]["value"] == "900-12-3456" and pat["preferred_language"]["value"] == "Vietnamese"
    assert pat["phone"]["value"] == "(312) 555-0147"  # "312–555–0147" with en dashes
    pol = ent_by(real, "InsurancePolicy", "Prairie Health Plan")["attributes"]  # "2. INSURANCE INFORMATION:"
    assert pol["member_id"]["value"] == "PHP-77120-03" and pol["group_number"]["value"] == "G-551"
    assert pol["policy_holder_relationship"]["value"] == "self"
    pharm = ent_by(real, "Pharmacy", "Walgreens #4471")
    assert rels(real, "USES_PHARMACY", "PAT_001", pharm["id"])


def test_nkda_is_an_answer_not_an_allergy(real):
    assert not any(e["type"] == "Allergy" for e in real["entities"].values())
    assert real["entities"]["PAT_001"]["attributes"]["allergies_status"]["value"] == "no known drug allergies"


def test_combined_and_unknown_columns_and_two_line_header(real):
    med = ent_by(real, "Medication", "Losartan")["attributes"]
    # "Dose/Frequency" is split; "Reason" is kept; "Prescribing / Physician" spans two lines
    assert (med["dosage"]["value"], med["frequency"]["value"]) == ("50 mg", "once daily")
    assert med["reason"]["value"] == "Blood pressure"
    assert med["prescribing_doctor"]["value"] == "Dr. Maria Lopez"
    assert len([e for e in real["entities"].values() if e["type"] == "Medication"]) == 2


def test_consent_signed_by_the_spouse_links_her(real):
    cft = ent_by(real, "Agreement", "Consent for Treatment")
    r = rels(real, "SIGNS", obj=cft["id"])[0]
    assert real["entities"][r["subject"]]["label"] == "Linh Nguyen" and "wife" in r["basis"]
    hipaa = ent_by(real, "Agreement", "Privacy Practices Acknowledgment")
    assert rels(real, "SIGNS", obj=hipaa["id"])[0]["subject"] == "PAT_001"  # "/s/ David Nguyen"


def test_contradicting_facts_go_to_review(tmp_path):
    from docintel.stress import make_real_world

    pdf = tmp_path / "bad.pdf"
    make_real_world(pdf, inconsistent=True)
    doc = process_pdf(pdf, ocr=False)
    pat = doc["entities"]["PAT_001"]["attributes"]
    check = next(c for c in doc["validation"]["checks"] if c["check_id"] == "cross_field_consistency")
    assert check["status"] == "review"
    assert pat["zip"]["status"] == "needs_review" and "does not belong to state IL" in pat["zip"]["notes"][-1]
    pol = ent_by(doc, "InsurancePolicy", "Prairie Health Plan")["attributes"]
    assert pol["policy_holder_dob"]["status"] == "needs_review"  # 1957 on the card, 1975 for the patient
    # two marital statuses ticked: kept for review, never chosen silently
    assert pat["marital_status"]["status"] == "needs_review" and "2 options are ticked" in pat["marital_status"]["notes"][-1]


# --------------------------------------------------------------------------- O: right-aligned invoice
def test_right_aligned_numbers_and_two_line_header():
    doc = process_pdf(STRESS / "invoice_O_right_aligned.pdf", ocr=False)
    assert doc["document"]["document_type"] == "invoice" and not doc["document"]["template_applied"]
    rows = {e["label"]: e["attributes"] for e in doc["entities"].values() if e["type"] == "TableRow"}
    assert set(rows) == {"Pipette tips, 1000 uL (case)", "Specimen cups, sterile", "Centrifuge tubes, 15 mL", "Cold packs"}
    pip = rows["Pipette tips, 1000 uL (case)"]
    assert (pip["qty"]["value"], pip["unit_price"]["value"], pip["amount"]["value"]) == ("3", "$84.00", "$252.00")
    assert rows["Centrifuge tubes, 15 mL"]["unit_price"]["value"] == "$0.85"
