"""The demo files: a tilted phone photo of a receipt and a clean invoice with 'Seller:' /
'Client:' blocks.  Both once produced a wrong total that was not flagged."""
from pathlib import Path

import pytest

from docintel import ocr
from docintel.pipeline import process_file

DEMO = Path(__file__).resolve().parents[1] / "samples" / "demo"


def _run(name, tmp_path):
    return process_file(DEMO / name, lambda k, n, g: {"doc_id": f"DOC_{k:03d}", "source_path": tmp_path / f"{k}.pdf"})[0]


def test_invoice_total_is_the_gross_amount_of_the_total_row(tmp_path):
    doc = _run("invoice_seller_client.pdf", tmp_path)
    kf = doc["key_facts"]
    assert doc["document"]["document_type"] == "invoice"
    assert kf["invoice_number"]["value"] == "51840277" and kf["invoice_date"]["value"] == "2026-03-02"
    assert kf["seller"]["value"].startswith("Harbor Lab Supply Ltd, 41 Wharf Road")
    assert kf["buyer"]["value"].startswith("Riverside Family Clinic")
    # 'Total $ 203,59 $ 20,36 $ 224,95': the net amount must never pass as the total
    assert kf["total"]["value"].replace("$", "") == "224,95"


@pytest.mark.skipif(not ocr.available(), reason="tesseract OCR engine not installed")
def test_tilted_receipt_photo(tmp_path):
    doc = _run("receipt_photo.jpg", tmp_path)
    kf = doc["key_facts"]
    page = doc["document"]["pages"][0]
    assert doc["document"]["document_type"] == "receipt"
    assert abs(page["deskew_angle"]) > 2  # levelled from the words, not left tilted
    # the amount at the far end of the TOTAL line, not the CASH amount one line below it
    assert kf["total"]["value"] == "103,400"
    assert kf["subtotal"]["value"] == "94,000" and kf["cash"]["value"] == "110,000"
    assert kf["merchant"]["status"] == "needs_review"  # a name read by OCR with no label
