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
    assert d["document_type"] == "lab report" and d["template_applied"] is False  # a guess from its words
    assert "reference range" in d["document_type_basis"]
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
    lang = _field(doc, "Referred By")
    assert lang["attributes"]["value"]["value"] == "Dr. Ellen Shaw" and lang["section"] == "Patient Information"
    pharmacy_phone = _field(doc, "Phone", "Transportation")
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


# --------------------------------------------------------------------------- labels over values, label lists
def _record_sheet(path):
    """Labels printed small over their values (two boxes per row, one alone), a list of
    labelled values without a header, and a real table."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=letter)
    H = letter[1]

    def t(s, x, y, size=10, bold=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(x, H - y, s)

    t("Account Activity Statement", 54, 60, 18, True)
    t("RECORD DETAILS", 60, 100, 11, True)
    for k, ((l1, v1), (l2, v2)) in enumerate([(("DOCUMENT REFERENCE", "FIN-0568"), ("ISSUED ON", "16-Sep-2026")),
                                              (("ACCOUNT HOLDER", "Kiran Pillai"), ("BRANCH", "Trichy"))]):
        y = 130 + k * 46
        t(l1, 64, y, 7, True); t(l2, 330, y, 7, True)
        t(v1, 64, y + 13, 11); t(v2, 330, y + 13, 11)
    t("CURRENCY", 64, 222, 7, True); t("INR", 64, 235, 11)
    t("SPECIFICATIONS", 60, 280, 11, True)
    for k, (a, b) in enumerate([("Size", "FULL PAGE"), ("Magazine", "TIME"), ("Field Date", "MARCH 25, 1974")]):
        t(a, 64, 305 + k * 15); t(b, 230, 305 + k * 15)
    t("ITEMISED DETAILS", 60, 380, 11, True)
    for k, row in enumerate([("Date", "Description", "Debit", "Credit"), ("16-Sep-2026", "Opening transfer", "-", "-"),
                             ("23-Sep-2026", "Service payment", "INR 1,551.00", "-"),
                             ("30-Sep-2026", "Refund", "-", "INR 1,267.00")]):
        for x, v in zip((64, 180, 330, 450), row):
            t(v, x, 405 + k * 18, 9, k == 0)
    c.save()


def test_labels_over_values_label_lists_and_tables(tmp_path):
    pdf = tmp_path / "sheet.pdf"
    _record_sheet(pdf)
    doc = process_pdf(pdf, ocr=False)
    fields = {e["label"]: e["attributes"]["value"] for e in doc["entities"].values() if e["type"] == "Field"}
    assert fields["DOCUMENT REFERENCE"]["value"] == "FIN-0568"
    assert fields["ACCOUNT HOLDER"]["value"] == "Kiran Pillai" and fields["BRANCH"]["value"] == "Trichy"
    assert fields["CURRENCY"]["value"] == "INR"  # a single box: label over value
    assert fields["Size"]["value"] == "FULL PAGE" and fields["Magazine"]["value"] == "TIME"  # a list, not a table
    rows = [e for e in doc["entities"].values() if e["type"] == "TableRow"]
    assert len(rows) == 3  # only the itemised table is a table
    pay = next(e for e in rows if e["label"] == "23-Sep-2026")["attributes"]
    assert pay["debit"]["value"] == "INR 1,551.00" and pay["description"]["value"] == "Service payment"


def test_value_and_label_heuristics():
    from docintel.generic import _reads_like_label, _value_like_header
    from docintel.ocr import fix_digit_letters

    assert fix_digit_letters("FIN-O600") == "FIN-0600" and fix_digit_letters("UTROO00000616") == "UTR0000000616"
    assert fix_digit_letters("Room") == "Room" and fix_digit_letters("INR") == "INR"
    assert _value_like_header([("Tobacco Rod Length", None), ("64 mm", None)])
    assert _value_like_header([("Written by", None), ("D. Schickedantz", None)])
    assert not _value_like_header([("Date", None), ("Description", None)])
    assert _reads_like_label("Authorized Signature") and _reads_like_label("Total Contract")
    assert not _reads_like_label("Kiran Pillai") and not _reads_like_label("Approved")
