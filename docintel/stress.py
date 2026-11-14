"""Stress documents: layouts and conditions that commonly break document readers.

Each one targets specific failure modes; tests/test_stress.py states, by hand, what a
correct reading must contain.  All data is synthetic.

    python -m docintel stress-samples          (writes samples/stress/)
"""
from __future__ import annotations

import io
import random
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from .samples import GRAY, _Pen, draw_standard_form, LINDQVIST, make_riverside, make_scanned

W, H = letter
X = 54.0
RR = 558.0
TEAL = HexColor("#0f5f6b")


def _kv(p: _Pen, label: str, value: str, x: float, baseline: float, size: float = 9.5) -> float:
    end = p.text(f"{label}:", x, baseline, size=size)
    return p.text(value, end + 3.0, baseline, size=size) if value else end


# --------------------------------------------------------------------------- F: tight labels
def make_tight_labels(path):
    """Single-spaced labels, qualified labels (Home/Work Phone), a value continued on a
    second line, check-box labels printed *before* their boxes, a row without prescriber."""
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle("Hillcrest new patient form")
    p = _Pen(c, "flattened", {})
    p.text("HILLCREST FAMILY PRACTICE", X, 58, size=15, bold=True, color=TEAL)
    p.text("New patient registration", X, 72, size=8.5, color=GRAY)

    p.heading("PATIENT INFORMATION", 90, X, RR, color=TEAL, size=11)
    p.text("Patient Name: Thomas Becker", X, 118, size=9.5)
    p.text("Date of Birth: 08/19/1964 Sex: M", X + 260, 118, size=9.5)
    p.text("Street Address: 1450 North Walnut Street", X, 134, size=9.5)
    # second address line, set tight under the value and aligned with it
    p.text("Unit 12", X + 72.6, 145, size=9.5)
    p.text("City: Bloomington State: IN Zip: 47401", X, 162, size=9.5)
    p.text("Home Phone: (812) 555-0134", X, 178, size=9.5)
    p.text("Work Phone: (812) 555-0199", X + 260, 178, size=9.5)
    p.text("Email: t.becker@example.com", X, 194, size=9.5)

    p.heading("EMERGENCY CONTACT", 212, X, RR, color=TEAL, size=11)
    p.text("Contact Name: Lisa Becker", X, 240, size=9.5)
    p.text("Relationship: Wife", X + 260, 240, size=9.5)
    p.text("Phone: (812) 555-0135", X, 256, size=9.5)
    p.text("Alt Phone: (812) 555-0136", X + 260, 256, size=9.5)

    p.heading("CURRENT MEDICATIONS", 274, X, RR, color=TEAL, size=11)
    cols = [X, X + 170, X + 260, X + 370]
    for x, h in zip(cols, ["Medication", "Dose", "Frequency", "Prescriber"]):
        p.text(h, x, 300, size=9.5, bold=True)
    for i, row in enumerate([("Atorvastatin", "40 mg", "Daily", "Dr. Karen Holt"),
                             ("Aspirin", "81 mg", "Daily", "")]):
        for x, v in zip(cols, row):
            if v:
                p.text(v, x, 318 + i * 17, size=9.5)

    p.heading("COMMUNICATION PREFERENCES", 362, X, RR, color=TEAL, size=11)
    for i, (q, yes, no) in enumerate([("May we leave a voicemail?", "[X]", "[ ]"),
                                      ("May we send text messages?", "[ ]", "[X]"),
                                      ("May we contact you by email?", "[X]", "[ ]")]):
        end = p.text(q, X, 388 + i * 16, size=9.5)
        p.text(f"Yes {yes}     No {no}", end + 14, 388 + i * 16, size=9.5)

    p.heading("CONSENT FOR TREATMENT", 446, X, RR, color=TEAL, size=11)
    p.text("I consent to examination and treatment by Hillcrest providers.", X, 472, size=8.5, color=GRAY)
    _kv(p, "Signature", "/s/ Thomas Becker", X, 496)
    _kv(p, "Print Name", "Thomas Becker", X + 230, 496)
    _kv(p, "Date", "03/10/2026", X + 400, 496)
    c.showPage()
    c.save()


# --------------------------------------------------------------------------- G: two packets
def make_two_packets(path, tmpdir: Path):
    """Two different patients' packets scanned into one PDF (a classic batch-scan accident)."""
    from pypdf import PdfReader, PdfWriter

    first = tmpdir / "_g1.pdf"
    second = tmpdir / "_g2.pdf"
    make_riverside(first)
    draw_standard_form(second, "flattened", LINDQVIST)
    w = PdfWriter()
    for f in (first, second):
        for page in PdfReader(str(f)).pages:
            w.add_page(page)
    with open(path, "wb") as fh:
        w.write(fh)
    first.unlink()
    second.unlink()


# --------------------------------------------------------------------------- H: European letter
def make_eu_referral(path):
    """A referral letter: narrative paragraphs, day-first dates, a signature block."""
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle("Referral letter")
    p = _Pen(c, "flattened", {})
    p.text("NORTHGATE MEDICAL CENTRE", X, 58, size=15, bold=True, color=TEAL)
    p.text("12 Station Road, Leeds LS1 4AP  -  Tel +44 113 496 0000", X, 72, size=8.5, color=GRAY)
    _kv(p, "Date", "14/03/2026", X + 380, 100)
    p.heading("REFERRAL", 118, X, RR, color=TEAL, size=11)
    _kv(p, "Patient", "Anna Kowalski", X, 146)
    _kv(p, "Date of Birth", "05/04/1980", X + 260, 146)
    _kv(p, "NHS Number", "943 476 5919", X, 162)
    _kv(p, "Referred To", "Dr. Helen Ward, Cardiology", X + 260, 162)
    p.heading("REASON FOR REFERRAL", 184, X, RR, color=TEAL, size=11)
    para = ["Ms Kowalski reports intermittent palpitations over the past six weeks, worse on exertion.",
            "A resting ECG on 02/03/2026 showed sinus rhythm with occasional ectopic beats. Thyroid",
            "function and electrolytes were within normal limits. I would be grateful for your assessment",
            "and advice on further investigation."]
    for i, line in enumerate(para):
        p.text(line, X, 210 + i * 13, size=9.5)
    p.heading("CURRENT MEDICATION", 276, X, RR, color=TEAL, size=11)
    cols = [X, X + 180, X + 280]
    for x, h in zip(cols, ["Medicine", "Dose", "Instructions"]):
        p.text(h, x, 302, size=9.5, bold=True)
    for i, row in enumerate([("Bisoprolol", "2.5 mg", "Once each morning"), ("Cetirizine", "10 mg", "When needed")]):
        for x, v in zip(cols, row):
            p.text(v, x, 320 + i * 17, size=9.5)
    p.heading("SIGNED", 364, X, RR, color=TEAL, size=11)
    p.text("Referring GP:", X, 392, size=9.5)
    p.ink(X + 70, 378, 100, 18, seed=41)
    _kv(p, "Name", "Dr. Samuel Price", X + 260, 392)
    c.showPage()
    c.save()


# --------------------------------------------------------------------------- I: stacked form over 2 pages
def make_stacked_form(path):
    """Labels printed *above* boxed values (no colons), a running header and footer on
    every page, and a table that continues onto the second page without a new header."""
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle("Volunteer health screening")
    p = _Pen(c, "flattened", {})

    def furniture(page_no):
        p.text("Lakeview Volunteer Services  -  Health Screening Form", X, 30, size=8, color=GRAY)
        p.text(f"Form LV-7  -  page {page_no} of 2", X, 772, size=7.5, color=GRAY)

    def box(label, value, x, top, w):
        p.text(label, x, top, size=8, color=GRAY)
        c.setStrokeColor(HexColor("#8a93a3"))
        c.setLineWidth(0.6)
        c.rect(x, H - (top + 21), w, 16, stroke=1, fill=0)
        if value:
            p.text(value, x + 3, top + 15.5, size=9.5)

    furniture(1)
    p.text("HEALTH SCREENING", X, 64, size=15, bold=True, color=TEAL)
    p.heading("VOLUNTEER", 84, X, RR, color=TEAL, size=11)
    box("Full name", "Priya Raman", X, 118, 220)
    box("Date of birth", "11/30/1991", X + 240, 118, 110)
    box("Volunteer ID", "LV-20931", X + 370, 118, 130)
    box("Mobile", "(312) 555-0172", X, 152, 220)
    box("Email", "priya.raman@example.com", X + 240, 152, 260)
    p.heading("VACCINATIONS", 196, X, RR, color=TEAL, size=11)
    cols = [X, X + 200, X + 330]
    for x, h in zip(cols, ["Vaccine", "Date Given", "Lot Number"]):
        p.text(h, x, 222, size=9.5, bold=True)
    rows = [("Influenza", "10/02/2025", "FL-2291"), ("Tetanus (Tdap)", "06/14/2021", "TD-0473"),
            ("Hepatitis B (dose 1)", "01/09/2019", "HB-1185"), ("Hepatitis B (dose 2)", "02/11/2019", "HB-1190"),
            ("Hepatitis B (dose 3)", "07/15/2019", "HB-1212"), ("MMR", "05/20/1993", "MM-0042"),
            ("Varicella", "08/03/1995", "VR-0388"), ("COVID-19 booster", "09/28/2025", "CV-7710")]
    top = 240
    for i, row in enumerate(rows[:5]):
        for x, v in zip(cols, row):
            p.text(v, x, top + i * 17, size=9.5)
    c.showPage()
    furniture(2)
    for i, row in enumerate(rows[5:]):
        for x, v in zip(cols, row):
            p.text(v, x, 70 + i * 17, size=9.5)
    p.heading("DECLARATION", 140, X, RR, color=TEAL, size=11)
    p.text("I confirm the information above is accurate.", X, 166, size=9)
    p.text("Signature:", X, 192, size=9.5)
    p.ink(X + 58, 178, 100, 18, seed=52)
    _kv(p, "Date", "10/06/2025", X + 300, 192)
    c.showPage()
    c.save()


# --------------------------------------------------------------------------- J: photo / sideways scan
def make_sideways_photo(src_pdf, path_png):
    """A phone photo of a page: an image file, turned 90 degrees, slightly noisy."""
    import pypdfium2 as pdfium
    from PIL import Image, ImageFilter

    from .render import PDFIUM_LOCK

    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(str(src_pdf))
        img = doc[0].render(scale=170 / 72).to_pil().convert("L")
        doc.close()
    img = img.rotate(90, expand=True, fillcolor=255).filter(ImageFilter.GaussianBlur(0.4))
    rnd = random.Random(3)
    px = img.load()
    w, h = img.size
    for _ in range(w * h // 300):
        x, y = rnd.randrange(w), rnd.randrange(h)
        px[x, y] = max(0, px[x, y] - rnd.randrange(30, 90))
    img.save(path_png)


# --------------------------------------------------------------------------- K: bad text layer
def make_bad_text_layer(src_pdf, path):
    """A scanned page whose embedded (invisible) text layer is garbage, as produced by a
    poor scanner OCR.  The garbage must not be trusted; the page must be read again."""
    import pypdfium2 as pdfium
    from reportlab.lib.utils import ImageReader

    from .render import PDFIUM_LOCK

    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(str(src_pdf))
        img = doc[0].render(scale=150 / 72).to_pil().convert("L")
        doc.close()
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle("Scan with a broken text layer")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    buf.seek(0)
    c.drawImage(ImageReader(buf), 0, 0, width=W, height=H)
    rnd = random.Random(7)
    t = c.beginText()
    t.setTextRenderMode(3)  # invisible, like an OCR layer
    t.setFont("Helvetica", 9)
    junk = "Ãß¿Ð#~^¬¦§¤þ÷×"
    for row in range(40):
        t.setTextOrigin(54, H - 60 - row * 17)
        t.textLine(" ".join("".join(rnd.choice(junk) for _ in range(rnd.randint(2, 7))) for _ in range(8)))
    c.drawText(t)
    c.showPage()
    c.save()


# --------------------------------------------------------------------------- L: encrypted
def make_encrypted(src_pdf, path):
    """Opens without a password (empty user password) but is encrypted."""
    from pypdf import PdfReader, PdfWriter

    w = PdfWriter(clone_from=PdfReader(str(src_pdf)))
    w.encrypt(user_password="", owner_password="owner-secret", algorithm="AES-128")
    with open(path, "wb") as fh:
        w.write(fh)


def generate_stress(out_dir: str | Path = "samples/stress") -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = []
    f = out / "intake_F_tight_labels.pdf"
    make_tight_labels(f)
    g = out / "intake_G_two_packets.pdf"
    make_two_packets(g, out)
    h = out / "referral_H_eu_letter.pdf"
    make_eu_referral(h)
    i = out / "screening_I_stacked_two_pages.pdf"
    make_stacked_form(i)
    j = out / "photo_J_sideways.png"
    make_sideways_photo(f, j)
    k = out / "scan_K_bad_text_layer.pdf"
    make_bad_text_layer(f, k)
    enc = out / "intake_L_encrypted.pdf"
    make_encrypted(f, enc)
    m = out / "order_M_fillable_unlabeled.pdf"
    make_unlabeled_fillable(m)
    n = out / "intake_N_real_world.pdf"
    make_real_world(n)
    o = out / "invoice_O_right_aligned.pdf"
    make_right_aligned_invoice(o)
    from .samples import make_scanned

    scan = out / "scan_P_real_world.pdf"  # N on paper: symbol boxes and choices read from the image
    make_scanned(n, scan, seed=11, angles=[1.1, -0.8])
    q = out / "intake_Q_written_lists.pdf"
    make_written_lists(q)
    r = out / "intake_R_fill_lines_signature_blocks.pdf"
    make_fill_lines(r)
    sv = out / "intake_S_field_value_tables.pdf"
    make_field_value_tables(sv)
    tv = out / "scan_T_field_value_tables.pdf"  # S printed and scanned: no header rows, no bold
    make_scanned(sv, tv, dpi=150, seed=21, angles=[0.5, -0.4, 0.3])
    files += [f, g, h, i, j, k, enc, m, n, o, scan, q, r, sv, tv]
    return files


if __name__ == "__main__":  # pragma: no cover
    for f in generate_stress():
        print(f)


# --------------------------------------------------------------------------- M: fillable, no printed labels
def make_unlabeled_fillable(path):
    """A fillable order form whose boxes carry no printed labels - only the fields' own
    descriptions (tooltips) say what they hold."""
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle("Supply order")
    p = _Pen(c, "flattened", {})
    p.text("SUPPLY ORDER", X, 60, size=15, bold=True, color=TEAL)
    p.heading("ORDER", 84, X, RR, color=TEAL, size=11)
    fields = [("customer", "Customer name", "Riverside Family Clinic", X, 112, 240),
              ("acct", "Account number", "RFC-00912", X + 260, 112, 120),
              ("deliver_by", "Deliver by date", "12/01/2026", X + 400, 112, 104),
              ("contact_phone", "Contact phone", "(217) 555-0100", X, 140, 160)]
    for name, tip, value, x, top, w in fields:
        c.acroForm.textfield(name=name, tooltip=tip, x=x, y=H - (top + 16), width=w, height=16, value=value,
                             fontName="Helvetica", fontSize=9.5, borderWidth=0.6, forceBorder=True)
    c.showPage()
    c.save()


# --------------------------------------------------------------------------- N: real-world variety
def _dingbat(p: _Pen, ch: str, x: float, baseline: float, size: float = 9.5):
    p.c.setFillColor(HexColor("#000000"))
    p.c.setFont("ZapfDingbats", size)
    p.c.drawString(x, H - baseline, ch)


def make_real_world(path, inconsistent: bool = False):
    """The quirks of real intake packets in one form: numbered headings ending in a
    colon, labels with format hints, choices ticked inside a field, '#'/'No.' labels, a
    single insurance section, a combined dose/frequency column with a two-line header,
    NKDA, a pharmacy section, en dashes in a phone number, symbol-font check boxes, and a
    consent signed by the spouse.  ``inconsistent`` writes facts that contradict each other
    (insured's birth date, ZIP vs state, two marital statuses ticked) for the consistency tests."""
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle("Sunrise Medical Group registration")
    p = _Pen(c, "flattened", {})
    NAVY = HexColor("#24345c")

    def head(s, top):
        p.text(s, X, top + 11, size=11, bold=True, color=NAVY)
        return top + 24

    p.text("SUNRISE MEDICAL GROUP", X, 56, size=15, bold=True, color=NAVY)
    p.text("Patient registration - please complete both pages", X, 70, size=8.5, color=GRAY)

    head("1. PATIENT INFORMATION:", 86)
    p.text("Name (Last, First, MI): Nguyen, David T.", X, 122, size=9.5)
    p.text("Date of Birth (MM/DD/YYYY): 02/28/1975", X + 280, 122, size=9.5)
    p.text("Sex:  [ ] F   [X] M", X, 138, size=9.5)
    p.text(f"Marital Status:  [{'X' if inconsistent else ' '}] Single   [X] Married   [ ] Divorced   [ ] Widowed",
           X + 140, 138, size=9.5)
    p.text("Home Address: 88 Lakeshore Drive", X, 154, size=9.5)
    p.text(f"City: Chicago   State: IL   ZIP: {'90611' if inconsistent else '60611'}", X + 280, 154, size=9.5)
    p.text("Mobile: 312–555–0147", X, 170, size=9.5)
    p.text("SSN: 900-12-3456", X + 280, 170, size=9.5)
    p.text("Preferred Language: Vietnamese", X, 186, size=9.5)

    head("2. INSURANCE INFORMATION:", 204)
    p.text("Insurance Provider: Prairie Health Plan", X, 240, size=9.5)
    p.text("Policy No.: PHP-77120-03", X + 280, 240, size=9.5)
    p.text("Policyholder: Nguyen, David T.", X, 256, size=9.5)
    p.text("Relationship to Insured: Self", X + 280, 256, size=9.5)
    p.text(f"Insured's DOB: {'02/28/1957' if inconsistent else '02/28/1975'}", X, 272, size=9.5)
    p.text("Group No.: G-551", X + 280, 272, size=9.5)

    head("3. EMERGENCY CONTACT:", 290)
    p.text("Name: Linh Nguyen", X, 326, size=9.5)
    p.text("Relationship: Wife", X + 200, 326, size=9.5)
    p.text("Phone: 312-555-0148", X + 360, 326, size=9.5)

    head("4. CURRENT MEDICATIONS:", 344)
    cols = [X, X + 150, X + 290, X + 410]
    for x, h in zip(cols, ["Medication", "Dose/Frequency", "Reason", "Prescribing"]):
        p.text(h, x, 378, size=9, bold=True)
    p.text("Physician", cols[3], 389, size=9, bold=True)
    rows = [("Losartan", "50 mg once daily", "Blood pressure", "Dr. Maria Lopez"),
            ("Metoprolol", "25 mg twice daily", "Heart rate", "Dr. Maria Lopez")]
    for i, row in enumerate(rows):
        for x, v in zip(cols, row):
            p.text(v, x, 406 + i * 16, size=9.5)

    head("5. ALLERGIES:", 440)
    for x, h in zip([X, X + 200], ["Allergen", "Reaction"]):
        p.text(h, x, 474, size=9, bold=True)
    p.text("NKDA", X, 490, size=9.5)

    head("6. MEDICAL HISTORY:", 508)
    for k, (on, label) in enumerate([(True, "Asthma"), (False, "Diabetes"), (True, "High cholesterol"), (False, "Cancer")]):
        x = X + k * 120
        _dingbat(p, "\u25a0" if on else "\u2751", x, 542)  # ZapfDingbats n (filled) / q (empty)
        p.text(label, x + 14, 542, size=9.5)

    head("7. PREFERRED PHARMACY:", 560)
    p.text("Pharmacy Name: Walgreens #4471", X, 596, size=9.5)
    p.text("Pharmacy Phone: (312) 555-0190", X + 280, 596, size=9.5)
    p.text("Address: 22 Main Street, Chicago", X, 612, size=9.5)
    c.showPage()

    head("8. CONSENT TO TREAT:", 50)
    p.text("I consent to examination and treatment by Sunrise Medical Group.", X, 84, size=8.5, color=GRAY)
    p.text("Signature:", X, 108, size=9.5)
    p.ink(X + 58, 94, 100, 18, seed=61)
    p.text("Print Name: Linh Nguyen", X + 230, 108, size=9.5)
    p.text("Date: 03/02/2026", X + 400, 108, size=9.5)
    head("9. ACKNOWLEDGEMENT OF PRIVACY PRACTICES:", 128)
    p.text("Signature: /s/ David Nguyen", X, 166, size=9.5)
    p.text("Date: 03/02/2026", X + 400, 166, size=9.5)
    c.showPage()
    c.save()


# --------------------------------------------------------------------------- O: right-aligned invoice
def make_right_aligned_invoice(path):
    """Numbers right-aligned under their headers, and a header split over two lines."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle("Invoice 5512")
    p = _Pen(c, "flattened", {})
    p.text("HARBOR LAB SUPPLY", X, 58, size=15, bold=True, color=TEAL)
    p.heading("INVOICE", 80, X, RR, color=TEAL, size=11)
    _kv(p, "Invoice No", "5512", X, 108)
    _kv(p, "Invoice Date", "09/12/2026", X + 280, 108)
    p.heading("LINE ITEMS", 128, X, RR, color=TEAL, size=11)
    right = {"Qty": X + 330, "Unit": X + 420, "Amount": X + 500}

    def rtext(s, xr, baseline, bold=False):
        w = stringWidth(s, "Helvetica-Bold" if bold else "Helvetica", 9.5)
        p.text(s, xr - w, baseline, size=9.5, bold=bold)

    p.text("Description", X, 156, size=9.5, bold=True)
    rtext("Qty", right["Qty"], 156, True)
    rtext("Unit", right["Unit"], 156, True)
    rtext("Price", right["Unit"], 167, True)
    rtext("Amount", right["Amount"], 156, True)
    items = [("Pipette tips, 1000 uL (case)", "3", "$84.00", "$252.00"),
             ("Specimen cups, sterile", "12", "$9.50", "$114.00"),
             ("Centrifuge tubes, 15 mL", "100", "$0.85", "$85.00"),
             ("Cold packs", "6", "$12.25", "$73.50")]
    for i, (d, q, u, a) in enumerate(items):
        y = 186 + i * 17
        p.text(d, X, y, size=9.5)
        rtext(q, right["Qty"], y)
        rtext(u, right["Unit"], y)
        rtext(a, right["Amount"], y)
    p.heading("TOTALS", 262, X, RR, color=TEAL, size=11)
    _kv(p, "Total Due", "$524.50", X + 330, 290)
    c.showPage()
    c.save()


# --------------------------------------------------------------------------- Q: lists written as text
def make_written_lists(path):
    """A short clinic form where allergies, medications and surgeries are written on a
    line instead of in a table, with an instruction line in between."""
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle("Lakeside Family Practice")
    p = _Pen(c, "flattened", {})
    NAVY = HexColor("#24345c")

    def head(s, top):
        p.text(s, X, top + 11, size=11, bold=True, color=NAVY)

    p.text("LAKESIDE FAMILY PRACTICE", X, 56, size=15, bold=True, color=NAVY)
    head("PATIENT INFORMATION", 74)
    p.text("Patient Name: Grace Okonkwo", X, 110, size=9.5)
    p.text("Date of Birth: 11/09/1962", X + 280, 110, size=9.5)
    p.text("Phone: (614) 555-0182", X, 126, size=9.5)
    p.text("Drug Allergies: Penicillin (hives), Sulfa drugs (rash)", X, 142, size=9.5)

    head("CURRENT MEDICATIONS", 162)
    p.text("Please list every medicine you take, including vitamins.", X, 196, size=8.5, color=GRAY)
    p.text("Medications: Lisinopril 10 mg daily; Metformin 500 mg twice daily; Vitamin D", X, 212, size=9.5)

    head("SURGICAL HISTORY", 232)
    p.text("Appendectomy (1988), Knee arthroscopy (2019)", X, 266, size=9.5)

    head("EMERGENCY CONTACT", 286)
    p.text("Name: Samuel Okonkwo", X, 320, size=9.5)
    p.text("Relationship: Husband", X + 200, 320, size=9.5)
    p.text("Phone: (614) 555-0183", X + 360, 320, size=9.5)

    head("CONSENT TO TREAT", 340)
    p.text("I consent to examination and treatment.", X, 374, size=8.5, color=GRAY)
    p.text("Signature: /s/ Grace Okonkwo", X, 394, size=9.5)
    p.text("Date: 05/14/2026", X + 300, 394, size=9.5)
    c.showPage()
    c.save()


# --------------------------------------------------------------------------- R: fill lines, signature blocks
def make_fill_lines(path):
    """Values typed over underscores and dotted leaders, a consent sentence that reads
    like a heading, and signature blocks whose labels sit under the line."""
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle("Brookside Clinic intake")
    p = _Pen(c, "flattened", {})
    NAVY = HexColor("#24345c")

    def head(s, top):
        p.text(s, X, top + 11, size=11, bold=True, color=NAVY)

    def rule(x0, x1, y):
        c.setStrokeColor(HexColor("#000000"))
        c.setLineWidth(0.6)
        c.line(x0, H - y, x1, H - y)

    p.text("BROOKSIDE CLINIC", X, 56, size=15, bold=True, color=NAVY)
    head("PATIENT INFORMATION", 74)
    p.text("Name: ____Ana Lopez__________   DOB: __03/14/1990__", X, 110, size=9.5)
    p.text("Phone.........(555) 123-4567", X, 126, size=9.5)
    p.text("Address: 9 Birch Lane____________   City: Dayton   State: OH   ZIP: 45402", X, 142, size=9.5)

    head("EMERGENCY CONTACT", 162)
    p.text("Name: Rosa Lopez   Relationship: Mother   Phone: 555-123-9999", X, 196, size=9.5)

    head("CONSENT FOR TREATMENT", 216)
    p.text("I consent to treatment.", X, 250, size=9.5)
    p.text("/s/ Ana Lopez", X + 6, 288, size=9.5)
    p.text("03/02/2026", X + 306, 288, size=9.5)
    rule(X, X + 246, 292)
    rule(X + 296, X + 446, 292)
    p.text("Signature of Patient", X, 304, size=8)
    p.text("Date", X + 296, 304, size=8)
    p.text("Ana Lopez", X + 6, 328, size=9.5)
    rule(X, X + 246, 332)
    p.text("Printed Name", X, 344, size=8)

    head("FINANCIAL RESPONSIBILITY", 364)
    p.text("I accept responsibility for charges not covered by insurance.", X, 398, size=9.5)
    p.ink(X + 8, 414, 110, 20, seed=73)
    p.text("03/02/2026", X + 306, 432, size=9.5)
    rule(X, X + 246, 436)
    rule(X + 296, X + 446, 436)
    p.text("Signature of Patient", X, 448, size=8)
    p.text("Date", X + 296, 448, size=8)
    c.showPage()
    c.save()


# --------------------------------------------------------------------------- S: field / value tables
FV_SECTIONS = [
    ("1. Patient Information", [
        ("Patient ID", "QA-204"), ("First Name", "Priya"), ("Last Name", "Raman"), ("Date of Birth", "09/23/1981"),
        ("Sex", "Female"), ("Phone", "555-014-2040"), ("Email", "priya.raman@example.com"),
        ("Address", "27 Cedar Court"), ("City", "Austin"), ("State", "Texas"), ("ZIP Code", "78704"),
        ("Marital Status", "Married"), ("Spouse Name", "Arjun Raman"), ("Spouse Phone", "555-014-2041"),
        ("Emergency Contact", "Meera Iyer"), ("Relationship", "Sister"), ("Emergency Phone", "555-014-2042")]),
    ("2. Insurance Information", [
        ("Do you have insurance?", "Yes"), ("Primary Card Holder", "Self"),
        ("Primary Policy Holder Name", "Priya Raman"), ("Primary Insurance Company", "Lone Star Health Plan"),
        ("Primary ID Number", "LSH-55821"), ("Primary Group Number", "G-7710"),
        ("Do you have secondary insurance?", "Yes"), ("Secondary Card Holder", "Spouse"),
        ("Secondary Policy Holder Name", "Arjun Raman"), ("Secondary Insurance Company", "Hill Country Mutual"),
        ("Secondary ID Number", "HCM-30017"), ("Secondary Group Number", "Not applicable")]),
    ("3. Prescription Information", [("Pharmacy Name", "Cedar Court Pharmacy"), ("Pharmacy Phone", "555-014-2090")]),
    ("4. Allergies and Family History", [
        ("Allergies", "Penicillin; Shellfish"), ("Mother — Family history", "Hypertension"),
        ("Father — Family history", "Type 2 diabetes")]),
    ("5. Social History", [
        ("Alcohol", "Yes — Occasionally"), ("Smoking", "No"), ("Caffeine", "Yes — Daily"),
        ("Exercise", "Walking, 3 times a week")]),
    ("6. Surgical History", [
        ("Surgery / Hospitalization", "Tonsillectomy"), ("Year / Date", "1994"), ("Doctor", "Dr. Helen Ortiz"),
        ("Location", "Austin, Texas")]),
    ("7. Medical History", [("Selected medical conditions", "Asthma; Thyroid disorder")]),
    ("8. Current Medications", [
        ("Medication 1", "Levothyroxine"), ("Dosage 1", "50 mcg"), ("Prescribing Doctor 1", "Dr. Sam Patel"),
        ("Medication 2", "Albuterol inhaler"), ("Dosage 2", "2 puffs"), ("Prescribing Doctor 2", "Dr. Lena Brooks")]),
    ("9. HIPAA Consent Preferences", [
        ("Appointment confirmation by phone/email/text", "Yes"), ("Permission to leave voicemail", "No"),
        ("Permission to discuss medical condition with family", "Yes"), ("Authorized family member", "Arjun Raman"),
        ("Printed Name", "Priya Raman"), ("Signature", "/s/ Priya Raman"), ("Date", "04/18/2026")]),
    ("10. Medical Services Agreement", [
        ("Patient Name", "Priya Raman"), ("Medical Consent", "Acknowledged"), ("Financial Agreement", "Acknowledged"),
        ("Notice of Privacy Practices", "Acknowledged"), ("Signature", "/s/ Priya Raman"), ("Date", "04/18/2026")]),
    ("11. Physician–Patient Arbitration Agreement", [
        ("Patient Name", "Priya Raman"), ("Agreement", "Reviewed"), ("Patient Signature", "/s/ Priya Raman"),
        ("Date", "04/18/2026")]),
]


def make_field_value_tables(path):
    """Every section a two-column table of 'Field | Value' rows, as exported by many
    practice systems: wrapped labels, prefixed labels ('Spouse Phone', 'Secondary ID
    Number'), numbered medication rows, one heading for two sections, a combined
    insurance section and three signature blocks."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle("Practice export - QA-204")
    W, Hh = letter
    NAVY = HexColor("#15345b")
    LX, VX, X0, X1 = 61.0, 205.0, 57.0, 539.0
    size = 7.4
    lead = 8.6

    def text(s, x, y, bold=False, color="#000000", sz=size):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", sz)
        c.setFillColor(HexColor(color))
        c.drawString(x, Hh - y, s)

    def wrap(s, width):
        words, lines, cur = s.split(), [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if stringWidth(t, "Helvetica", size) > width and cur:
                lines.append(cur)
                cur = w
            else:
                cur = t
        return lines + ([cur] if cur else [])

    y = 48
    text("PRACTICE EXPORT — QA-204", X0, y, bold=True, sz=13)
    y += 16
    text("Generated record for quality checks. All data is fictional.", X0, y, color="#555555", sz=7.6)
    y += 22
    for heading, rows in FV_SECTIONS:
        need = 34 + sum(14.6 + lead * (len(wrap(a, 128)) - 1) for a, _ in rows)
        if y + need > Hh - 60:
            c.showPage()
            y = 48
        text(heading, X0, y + 8, bold=True, sz=10.5)
        y += 16
        c.setFillColor(NAVY)
        c.rect(X0, Hh - y - 14.6, X1 - X0, 14.6, stroke=0, fill=1)
        text("Field", LX, y + 9.6, bold=True, color="#ffffff")
        text("Value", VX, y + 9.6, bold=True, color="#ffffff")
        y += 14.6
        for k, (label, value) in enumerate(rows):
            lab = wrap(label, 128)
            h = 14.6 + lead * (len(lab) - 1)
            c.setFillColor(HexColor("#f5f8fb" if k % 2 else "#ffffff"))
            c.setStrokeColor(HexColor("#c9d3df"))
            c.rect(X0, Hh - y - h, X1 - X0, h, stroke=1, fill=1)
            for i, part in enumerate(lab):
                text(part, LX, y + 9.6 + i * lead)
            text(value, VX, y + 9.6)
            y += h
        y += 18
    c.showPage()
    c.save()
