"""Fillable-form details: radio groups and digital signature fields."""
import pypdf
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, TextStringObject
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from conftest import ent_by, rels
from docintel.pipeline import process_pdf


def _form(path, labelled=True, signed=True):
    c = canvas.Canvas(str(path), pagesize=letter)
    H = letter[1]

    def text(s, x, y, bold=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 11 if bold else 9.5)
        c.drawString(x, H - y, s)

    text("PATIENT INFORMATION", 54, 60, True)
    text("Patient Name:", 54, 90)
    c.acroForm.textfield(name="name", value="Nguyen, David T.", x=124, y=H - 94, width=150, height=14, borderWidth=0)
    text("Date of Birth:", 300, 90)
    c.acroForm.textfield(name="dob", value="02/28/1975", x=370, y=H - 94, width=80, height=14, borderWidth=0)
    text("Sex:", 54, 112)
    for k, (export, on) in enumerate([("Female", False), ("Male", True)]):
        x = 84 + k * 50
        c.acroForm.radio(name="sex", value=export, selected=on, x=x, y=H - 115, size=10, buttonStyle="circle")
        if labelled:
            text(export[0], x + 13, 112)
    text("EMERGENCY CONTACT", 54, 150, True)
    text("Name: Linh Nguyen", 54, 176)
    text("Phone: 312-555-0148", 300, 176)
    text("CONSENT FOR TREATMENT", 54, 214, True)
    text("I consent to examination and treatment.", 54, 236)
    text("Signature:", 54, 262)
    text("Date: 03/02/2026", 300, 262)
    c.save()
    r = pypdf.PdfReader(str(path))
    w = pypdf.PdfWriter(clone_from=r)
    page = w.pages[0]
    sig = DictionaryObject({NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Widget"),
                            NameObject("/FT"): NameObject("/Sig"), NameObject("/T"): TextStringObject("patient_sig"),
                            NameObject("/Rect"): ArrayObject([FloatObject(v) for v in (104, H - 268, 260, H - 252)])})
    if signed:
        sig[NameObject("/V")] = DictionaryObject({NameObject("/Type"): NameObject("/Sig"),
                                                  NameObject("/Name"): TextStringObject("David Nguyen"),
                                                  NameObject("/M"): TextStringObject("D:20260302100000Z")})
    ref = w._add_object(sig)
    page[NameObject("/Annots")].append(ref)
    w._root_object["/AcroForm"][NameObject("/Fields")].append(ref)
    with open(path, "wb") as fh:
        w.write(fh)


def test_radio_group_and_digital_signature(tmp_path):
    pdf = tmp_path / "radio.pdf"
    _form(pdf)
    doc = process_pdf(pdf, ocr=False)
    pat = doc["entities"]["PAT_001"]["attributes"]
    assert pat["sex"]["value"] == "male" and pat["sex"]["status"] == "valid"
    agr = ent_by(doc, "Agreement", "Consent for Treatment")
    assert agr["attributes"]["signature"]["value"] == "digitally signed by David Nguyen"
    assert rels(doc, "SIGNS", obj=agr["id"])[0]["subject"] == "PAT_001"


def test_unlabelled_radio_options_use_their_export_names(tmp_path):
    pdf = tmp_path / "radio_bare.pdf"
    _form(pdf, labelled=False, signed=False)
    doc = process_pdf(pdf, ocr=False)
    assert doc["entities"]["PAT_001"]["attributes"]["sex"]["value"] == "male"  # the option's export name
    agr = ent_by(doc, "Agreement", "Consent for Treatment")
    assert "signature" not in agr["attributes"]
    assert any(m["path"] == "consent_for_treatment.signature" for m in doc["missing"])
