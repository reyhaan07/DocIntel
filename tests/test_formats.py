"""Every supported file type goes through the same pipeline: the converted PDF keeps the
document's structure, so the same fields and table rows come out of each."""
from pathlib import Path

import pytest

from docintel.convert import read_blocks
from docintel.pipeline import process_file, supported_suffixes

FIX = Path(__file__).parent / "fixtures" / "formats"


def _run(path, tmp_path):
    return process_file(path, lambda k, n, g: {"doc_id": f"DOC_{k:03d}", "source_path": tmp_path / f"{k}.pdf"})[0]


@pytest.mark.parametrize("name", ["invoice.docx", "invoice.odt", "invoice.html", "invoice.md", "invoice.txt",
                                  "invoice.rtf", "invoice.pptx", "invoice.eml", "invoice.json"])
def test_invoice_in_every_format(name, tmp_path):
    doc = _run(FIX / name, tmp_path)
    d = doc["document"]
    assert d["source_format"] == name.rsplit(".", 1)[1] and d["converted_from"]
    if name == "invoice.eml":  # an e-mail that carries an invoice: both are reported
        assert d["document_type"] == "email" and d["carries"] == "invoice"
        assert doc["key_facts"]["total"]["value"] == "$307.80" and doc["key_facts"]["from"]["value"]
    else:
        assert d["document_type"] == "invoice"
    fields = {e["label"].lower(): e["attributes"]["value"]["value"] for e in doc["entities"].values() if e["type"] == "Field"}
    assert fields["invoice number"] == "INV-20931" and fields["total due"] == "$307.80"
    if name != "invoice.eml":
        rows = {e["label"]: e["attributes"] for e in doc["entities"].values() if e["type"] == "TableRow"}
        assert rows["Nitrile gloves (box)"]["amount"]["value"] == "$102.00"
        assert rows["Sharps container"]["qty"]["value"] == "4"
    assert doc["summary"]["validation_errors"] == 0


@pytest.mark.parametrize("name", ["items.csv", "items.xlsx", "items.ods"])
def test_spreadsheets_are_tables(name, tmp_path):
    doc = _run(FIX / name, tmp_path)
    rows = {e["label"]: e["attributes"] for e in doc["entities"].values() if e["type"] == "TableRow"}
    assert set(rows) == {"Nitrile gloves (box)", "Sharps container", "Exam table paper"}
    assert rows["Exam table paper"]["unit_price"]["value"] == "$21.00"


def test_email_headers_and_attachments():
    blocks = read_blocks(FIX / "invoice.eml")
    kv = {b.label: b.text for b in blocks if b.kind == "kv"}
    assert kv["Subject"] == "Invoice INV-20931" and "billing@harborlab.example" in kv["From"]
    assert any(b.kind == "item" and b.text == "INV-20931.pdf" for b in blocks)


def test_html_forms_and_tick_boxes(tmp_path):
    page = tmp_path / "form.html"
    page.write_text("""<html><head><title>Volunteer sign-up</title></head><body>
      <h1>Volunteer sign-up</h1>
      <label for="n">Full name</label><input id="n" value="Ana Lopez">
      <label for="p">Phone</label><input id="p" value="555-201-3344">
      <dl><dt>Shift</dt><dd>Saturday morning</dd></dl>
      <input type="checkbox" checked> First aid trained
      <p>Status: ☒ Active ☐ Inactive</p></body></html>""", encoding="utf-8")
    blocks = read_blocks(page)
    kv = {b.label: b.text for b in blocks if b.kind == "kv"}
    assert kv == {"Full name": "Ana Lopez", "Phone": "555-201-3344", "Shift": "Saturday morning"}
    assert any(b.kind == "check" and b.checked for b in blocks)
    assert any(b.kind == "para" and "[X] Active" in b.text for b in blocks)


def test_upload_types_are_listed():
    assert {".docx", ".xlsx", ".pptx", ".html", ".eml", ".csv", ".json", ".rtf", ".pdf", ".png"} <= supported_suffixes()
