"""The template-free layer: any document is read, and nothing on the page is dropped."""
import pytest

from conftest import ent_by, rels
from docintel.pipeline import process_pdf
from docintel.samples import make_riverside


@pytest.fixture(scope="module")
def lab(samples_dir):
    return process_pdf(samples_dir / "lab_report_harper.pdf", "DOC_L")


@pytest.fixture(scope="module")
def invoice(samples_dir):
    return process_pdf(samples_dir / "invoice_northwind.pdf", "DOC_I")


def _field(doc, label, section=None):
    return next(e for e in doc["entities"].values() if e["type"] == "Field" and e["label"] == label
                and (section is None or e["section"] == section))


def test_unknown_document_type_is_read_without_a_template(lab):
    d = lab["document"]
    assert d["document_type"] == "unknown" and d["template_applied"] is False
    assert d["title"] == "City Lab Services"
    assert d["status"] == "completed"
    assert not any(e["type"] == "Patient" for e in lab["entities"].values())  # no intake meaning is invented
    assert lab["summary"]["text_coverage"] == 1.0
    assert lab["standardized"] is None


def test_unknown_document_fields_are_typed_and_traced(lab):
    dob = _field(lab, "DOB")["attributes"]["value"]
    assert dob["value"] == "1972-02-11" and dob["raw"] == "02/11/1972" and dob["field_label"] == "DOB"
    assert _field(lab, "DOB")["value_type"] == "date"
    assert _field(lab, "Phone")["attributes"]["value"]["value"] == "(217) 555-0148"
    assert _field(lab, "Ordering Physician")["section"] == "Order"
    for e in lab["entities"].values():
        for a in e["attributes"].values():
            assert a["page"] == 1 and a["bbox"]


def test_unknown_document_table_rows_keep_their_columns(lab):
    rows = [e for e in lab["entities"].values() if e["type"] == "TableRow"]
    assert [r["label"] for r in rows] == ["Glucose", "Hemoglobin A1c", "Total Cholesterol", "LDL Cholesterol",
                                          "HDL Cholesterol", "Creatinine"]
    glucose = rows[0]["attributes"]
    assert (glucose["result"]["value"], glucose["units"]["value"], glucose["reference_range"]["value"],
            glucose["flag"]["value"]) == ("112", "mg/dL", "70-99", "H")
    assert glucose["result"]["field_label"] == "Result"
    assert "flag" not in rows[2]["attributes"]  # an empty cell stays empty
    sec = next(e for e in lab["entities"].values() if e["type"] == "Section" and e["label"] == "Results")
    assert len(rels(lab, "CONTAINS", sec["id"])) == 6


def test_unknown_document_questions_and_signatures(lab, invoice):
    q = next(e for e in lab["entities"].values() if e["type"] == "Question")
    assert q["label"] == "Was the patient fasting" and q["attributes"]["answer"]["value"] == "yes"
    sig = next(e for e in lab["entities"].values() if e["type"] == "Signature")
    assert sig["label"] == "Reviewed by" and sig["attributes"]["signature"]["extraction_method"] == "layout_signature"
    dated = rels(lab, "DATED", sig["id"])
    assert dated and lab["entities"][dated[0]["object"]]["attributes"]["value"]["value"] == "2026-11-03"
    paid = next(e for e in invoice["entities"].values() if e["type"] == "Question")
    assert paid["attributes"]["answer"]["value"] == "no"


def test_invoice_amounts_and_items(invoice):
    total = _field(invoice, "Total Due")
    assert total["attributes"]["value"]["value"] == "$1,340.28" and total["value_type"] == "amount"
    items = [e for e in invoice["entities"].values() if e["type"] == "TableRow"]
    assert len(items) == 4
    assert items[1]["attributes"]["description"]["value"] == "Nitrile gloves, medium (box)"
    assert invoice["summary"]["validation_errors"] == 0


def test_known_forms_leave_nothing_unexplained(processed):
    for key in "ABC":
        doc = processed[key]
        assert doc["summary"]["text_coverage"] == 1.0
        check = next(c for c in doc["validation"]["checks"] if c["check_id"] == "text_coverage")
        assert check["status"] == "passed", check["issues"]
        assert not [e for e in doc["entities"].values() if e["type"] in ("Field", "TableRow", "Question")]


def test_unknown_parts_of_a_known_form_are_kept_and_reported(tmp_path):
    pdf = tmp_path / "riverside_extra.pdf"
    make_riverside(pdf, extras=True)
    doc = process_pdf(pdf, "DOC_X")
    assert doc["document"]["template_applied"]
    lang = _field(doc, "Preferred Language")
    assert lang["attributes"]["value"]["value"] == "Spanish" and lang["section"] == "Patient Information"
    pharmacy_phone = _field(doc, "Phone", "Preferred Pharmacy")
    assert pharmacy_phone["attributes"]["value"]["value"] == "(217) 555-0110"
    # the unknown section closes the agreement above it: nothing leaks into the template entities
    assert doc["entities"]["PAT_001"]["attributes"]["phone"]["value"] == "(217) 555-0143"
    fin = ent_by(doc, "Agreement", "Financial Responsibility Agreement")
    assert set(fin["attributes"]) == {"title", "signature", "printed_name", "date"}
    check = next(c for c in doc["validation"]["checks"] if c["check_id"] == "text_coverage")
    assert check["status"] == "review"
    targets = {i["target"] for i in check["issues"]}
    assert lang["id"] in targets and pharmacy_phone["id"] in targets
    assert doc["summary"]["text_coverage"] == 1.0
