"""OCR: image helpers (pure numpy/PIL) and end-to-end reading of scanned packets."""
import numpy as np
import pytest
from PIL import Image, ImageDraw

from conftest import ent_by, rels
from docintel import ocr
from docintel.normalize import fix_dosage
from docintel.pipeline import process_pdf

S = ocr.SCALE
needs_engine = pytest.mark.skipif(not ocr.available(), reason="tesseract OCR engine not installed")


def _canvas(w_pt=300, h_pt=120):
    img = Image.new("L", (int(w_pt * S), int(h_pt * S)), 255)
    return img, ImageDraw.Draw(img)


def _pt(*v):
    return [int(x * S) for x in v]


# --------------------------------------------------------------------------- helpers
def test_unskew_is_identity_without_angle_and_rotates_with_one():
    box = [100.0, 200.0, 150.0, 210.0]
    assert ocr.unskew_bbox(box, 0.0, 612, 792) == box
    moved = ocr.unskew_bbox(box, 2.0, 612, 792)
    assert moved != box and abs((moved[2] - moved[0]) - 50) < 1.5


def test_skew_is_estimated():
    img, d = _canvas(400, 300)
    for i in range(12):
        d.rectangle(_pt(20, 20 + i * 22, 380, 26 + i * 22), fill=0)  # text-like lines
    rotated = img.rotate(1.5, resample=Image.BICUBIC, fillcolor=255)
    assert abs(ocr.estimate_skew(rotated) + 1.5) <= 0.2
    assert ocr.estimate_skew(img) == 0.0


def test_remove_lines_keeps_text_and_drops_box_borders():
    img, d = _canvas()
    d.rectangle(_pt(20, 20, 280, 40), outline=150, width=3)  # light-gray form box
    d.rectangle(_pt(30, 26, 34, 34), fill=0)  # a "letter" inside the box
    d.rectangle(_pt(40, 26, 44, 34), fill=0)
    arr = np.asarray(img)
    clean, n = ocr.remove_lines(arr)
    assert n > 0
    top_edge = clean[int(20 * S) - 1:int(20 * S) + 2, int(100 * S):int(200 * S)]
    assert top_edge.min() > 200  # border gone
    assert clean[int(30 * S), int(32 * S)] < 50  # letter kept


def test_drawn_checkboxes_are_found_with_their_state():
    img, d = _canvas()
    d.rectangle(_pt(20, 20, 30, 30), outline=120, width=3)  # empty
    d.rectangle(_pt(60, 20, 70, 30), outline=120, width=3)  # ticked
    d.line(_pt(62, 22, 68, 28), fill=0, width=5)
    d.line(_pt(62, 28, 68, 22), fill=0, width=5)
    boxes, _ = ocr.find_checkboxes(np.asarray(img), [], 1)
    found = sorted((round(b.x0), b.checked) for b in boxes)
    assert found == [(20, False), (60, True)]


def test_ocr_style_dosage_fixes():
    assert fix_dosage("75 meg") == ("75 mcg", True)
    assert fix_dosage("4o mg") == ("40 mg", True)
    assert fix_dosage("500 mg") == ("500 mg", True)
    assert fix_dosage("2 puffs")[1] is True
    assert fix_dosage("daily")[1] is False


def test_forcing_ocr_without_engine_fails(monkeypatch, samples_dir):
    monkeypatch.setattr(ocr, "available", lambda: False)
    with pytest.raises(RuntimeError):
        process_pdf(samples_dir / "intake_D_scanned_rivera.pdf", ocr=True)
    doc = process_pdf(samples_dir / "intake_D_scanned_rivera.pdf")  # auto: falls back to "needs OCR"
    assert doc["document"]["status"] == "needs_ocr"
    assert "no OCR engine" in doc["review_queue"][0]["reason"]


# --------------------------------------------------------------------------- end to end
@pytest.fixture(scope="module")
def scanned(samples_dir):
    return {
        "D": process_pdf(samples_dir / "intake_D_scanned_rivera.pdf", "DOC_004"),
        "E": process_pdf(samples_dir / "intake_E_scanned_lindqvist.pdf", "DOC_005"),
    }


@needs_engine
def test_scanned_other_clinic_reads_like_the_original(scanned, processed):
    doc, original = scanned["D"], processed["C"]
    assert doc["document"]["extraction_method"] == "ocr"
    assert doc["document"]["status"] == "needs_review"
    assert all(p["ocr_used"] for p in doc["document"]["pages"])
    assert doc["summary"]["entities"] == original["summary"]["entities"]
    assert doc["summary"]["relationships"] == original["summary"]["relationships"]
    assert doc["summary"]["validation_errors"] == 0
    pat = doc["entities"]["PAT_001"]["attributes"]
    assert pat["full_name"]["value"] == "Rivera, Maria L."
    assert pat["date_of_birth"]["value"] == "1985-07-14"
    assert pat["full_name"]["extraction_method"] == "ocr_key_value"
    sert = ent_by(doc, "Medication", "Sertraline")
    assert sert["attributes"]["dosage"]["value"] == "50 mg"
    assert rels(doc, "PRESCRIBED_BY", sert["id"])[0]["object"] == ent_by(doc, "Doctor", "Dr. Priya Nair")["id"]
    ids = {p["attributes"]["policy_type"]["value"]: p["attributes"]["member_id"]["value"]
           for p in doc["entities"].values() if p["type"] == "InsurancePolicy"}
    assert ids == {"primary": "BRH-4471920", "secondary": "LKM-88120"}
    mother = ent_by(doc, "FamilyMember", "Mother")
    assert mother["attributes"]["conditions"]["value"] == ["Type 2 diabetes", "hypertension"]
    cons = {e["consent_key"]: e["attributes"]["decision"]["value"] for e in doc["entities"].values() if e["type"] == "Consent"}
    assert cons["voicemail"] == "yes" and cons["text_message"] is None
    fin = ent_by(doc, "Agreement", "Financial Responsibility Agreement")
    signs = rels(doc, "SIGNS", obj=fin["id"])[0]
    assert doc["entities"][signs["subject"]]["type"] == "EmergencyContact" and signs["support"] == "explicit"
    vit = ent_by(doc, "Medication", "Vitamin D3")
    assert vit["attributes"]["frequency"]["status"] == "needs_review"


@needs_engine
def test_scanned_boxed_form_reads_drawn_checkboxes(scanned, processed):
    doc, original = scanned["E"], processed["B"]
    assert doc["summary"]["entities"] == original["summary"]["entities"]
    assert doc["summary"]["validation_errors"] == 0
    assert doc["entities"]["PAT_001"]["label"] == "Erik Lindqvist"
    cons = {e["consent_key"]: e["attributes"]["decision"]["value"] for e in doc["entities"].values() if e["type"] == "Consent"}
    assert cons == {"voicemail": "yes", "text_message": "no", "email": "yes", "release_of_information": "no"}
    conds = {e["label"] for e in doc["entities"].values() if e["type"] == "Condition" and e.get("owner_hint") == "patient"}
    assert conds == {"Asthma", "Thyroid disorder"}
    sigs = [e["attributes"].get("signature") for e in doc["entities"].values() if e["type"] == "Agreement"]
    assert len(sigs) == 3 and all(sigs)


@needs_engine
def test_doubtful_ocr_values_go_to_review_not_into_the_record(scanned):
    """Whatever OCR could not read confidently is flagged, never silently trusted."""
    doc = scanned["E"]
    flagged = [(e["id"], k, a) for e in doc["entities"].values() for k, a in e["attributes"].items()
               if a["status"] == "needs_review"]
    assert flagged
    queued = {r["target"] for r in doc["review_queue"] if r["kind"] == "attribute"}
    assert {f"{eid}.{k}" for eid, k, _ in flagged} <= queued
    for _, _, a in flagged:
        assert a["notes"]


@needs_engine
def test_light_text_on_a_dark_header_band(tmp_path):
    """White text on a dark table header is read (inverted and cleaned before OCR)."""
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    from docintel.samples import make_scanned

    src = tmp_path / "band.pdf"
    c = canvas.Canvas(str(src), pagesize=letter)
    H = letter[1]
    c.setFillColor(HexColor("#3d5470"))
    c.rect(54, H - 220, 500, 22, stroke=0, fill=1)
    c.setFillColor(HexColor("#ffffff"))
    c.setFont("Helvetica-Bold", 11)
    for x, w in ((64, "Date"), (190, "Description"), (340, "Debit"), (460, "Credit")):
        c.drawString(x, H - 213, w)
    c.setFillColor(HexColor("#000000"))
    c.setFont("Helvetica", 10)
    c.drawString(64, H - 240, "16-Sep-2026")
    c.save()
    scan = tmp_path / "band_scan.pdf"
    make_scanned(src, scan, dpi=150, seed=3, angles=[0.0])
    words = {t.text for t in ocr.ocr_page(scan, 1, 612, 792).tokens}
    assert {"Date", "Description", "Debit", "Credit"} <= words
