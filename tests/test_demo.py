"""The ten demo documents (samples/demo): one per kind of document and file format.  Each
key fact must come out right, and anything doubtful must be flagged - three of these
documents once produced a wrong value that was not flagged."""
from pathlib import Path

import pytest

from docintel import ocr
from docintel.pipeline import process_file

DEMO = Path(__file__).resolve().parents[1] / "samples" / "demo"
needs_engine = pytest.mark.skipif(not ocr.available(), reason="tesseract OCR engine not installed")


def _run(name, tmp_path):
    return process_file(DEMO / name, lambda k, n, g: {"doc_id": f"DOC_{k:03d}", "source_path": tmp_path / f"{k}.pdf"})[0]


def _facts(doc):
    return {k: v["value"] for k, v in (doc.get("key_facts") or {}).items()}


def test_invoice_total_is_the_gross_amount_of_the_total_row(tmp_path):
    doc = _run("01_invoice.pdf", tmp_path)
    kf = doc["key_facts"]
    assert doc["document"]["document_type"] == "invoice"
    assert kf["invoice_number"]["value"] == "51840277" and kf["invoice_date"]["value"] == "2026-03-02"
    assert kf["seller"]["value"].startswith("Harbor Lab Supply Ltd, 41 Wharf Road")
    assert kf["buyer"]["value"].startswith("Riverside Family Clinic")
    # 'Total $ 203,59 $ 20,36 $ 224,95': the net amount must never pass as the total
    assert kf["total"]["value"].replace("$", "") == "224,95"


@needs_engine
def test_tilted_receipt_photo(tmp_path):
    doc = _run("02_receipt_photo.jpg", tmp_path)
    kf = doc["key_facts"]
    page = doc["document"]["pages"][0]
    assert doc["document"]["document_type"] == "receipt"
    assert abs(page["deskew_angle"]) > 2  # levelled from the words, not left tilted
    # the amount at the far end of the TOTAL line, not the CASH amount one line below it; an
    # OCR version that reads only '103' of it gets it back from subtotal + tax = cash - change
    assert kf["total"]["value"] == "103,400" and kf["total"]["status"] == "valid"
    assert kf["subtotal"]["value"] == "94,000" and kf["cash"]["value"] == "110,000"
    assert kf["merchant"]["status"] == "needs_review"  # a name read by OCR with no label


def test_bank_statement(tmp_path):
    doc = _run("03_bank_statement.pdf", tmp_path)
    assert doc["document"]["document_type"] == "bank statement"
    assert _facts(doc) == {"account_holder": "Amara Okafor", "account_number": "4471 0092 5813",
                           "statement_period": "02/01/2026 to 02/28/2026", "opening_balance": "$3,240.18",
                           "closing_balance": "$4,105.62"}


def test_payslip_in_word(tmp_path):
    doc = _run("04_payslip.docx", tmp_path)
    assert doc["document"]["document_type"] == "payslip"
    assert _facts(doc) == {"employee_name": "Daniel Moreau", "employee_id": "NL-20417", "pay_period": "March 2026",
                           "pay_date": "2026-03-31", "gross_pay": "$4,665.00", "net_pay": "$3,648.50"}


@needs_engine
def test_scanned_utility_bill(tmp_path):
    doc = _run("05_utility_bill_scan.png", tmp_path)
    kf = _facts(doc)
    assert doc["document"]["document_type"] == "utility bill"
    assert kf["account_number"] == "88-301-4472" and kf["amount_due"] == "$128.47" and kf["due_date"] == "2026-03-20"
    assert kf["meter_number"] == "MTR-559102" and kf["usage"] == "612 kWh"


def test_discharge_summary(tmp_path):
    doc = _run("06_discharge_summary.pdf", tmp_path)
    assert doc["document"]["document_type"] == "discharge summary"
    assert _facts(doc) == {"patient_name": "Lena Harper", "admission_date": "2026-02-10", "discharge_date": "2026-02-14",
                           "attending_physician": "Dr. Omar Haddad", "diagnosis": "Community-acquired pneumonia"}


@needs_engine
def test_scanned_prescription(tmp_path):
    doc = _run("07_prescription_scan.pdf", tmp_path)
    assert doc["document"]["document_type"] == "prescription"
    kf = _facts(doc)
    assert kf["patient_name"] == "Mateo Silva" and kf["prescriber"] == "Dr. Priya Shah" and kf["date"] == "2026-03-05"


def test_purchase_order_in_excel(tmp_path):
    doc = _run("08_purchase_order.xlsx", tmp_path)
    assert doc["document"]["document_type"] == "purchase order"
    assert _facts(doc) == {"po_number": "PO-2026-0381", "order_date": "2026-03-09", "vendor": "Brightpath Supplies Inc",
                           "ship_to": "Pioneer Logistics, 9 Harbor Way, Tacoma, WA 98402", "total": "$1,284.00"}


def test_payment_reminder_email(tmp_path):
    doc = _run("09_payment_reminder.eml", tmp_path)
    kf = _facts(doc)
    assert kf["invoice_number"] == "SE-77120" and kf["total"] == "$128.47" and kf["due_date"] == "2026-03-20"


def test_fillable_insurance_claim(tmp_path):
    doc = _run("10_insurance_claim_form.pdf", tmp_path)
    assert doc["document"]["document_type"] == "insurance"
    assert doc["document"]["extraction_method"] == "form_fields"
    kf = _facts(doc)
    assert kf["policy_number"] == "EVG-55-210984" and kf["claim_number"] == "CLM-0091237" and kf["insured"] == "Amara Okafor"


def test_a_total_read_in_part_comes_back_from_the_receipts_sums():
    """Tesseract 5.4.0 reads the receipt's bold total '103,400' as '103'."""
    from docintel.profiles import _check_sums

    def f(v, st="valid"):
        return {"value": v, "status": st, "label": "x", "notes": []}

    out = {"subtotal": f("94,000"), "tax": f("9,400", "needs_review"), "total": f("103", "needs_review"),
           "cash": f("110,000"), "change": f("6,600")}
    _check_sums(out)
    assert out["total"]["value"] == "103,400" and out["total"]["status"] == "valid"  # two separate sums agree
    out = {"subtotal": f("94,000"), "tax": f("9,400"), "total": f("103", "needs_review")}
    _check_sums(out)
    assert out["total"]["value"] == "103,400" and out["total"]["status"] == "needs_review"  # one sum: review
    out = {"subtotal": f("94,000"), "tax": f("9,400"), "total": f("98,500")}
    _check_sums(out)
    assert out["total"]["value"] == "98,500"  # a different total is not a cut-off one: left as read
