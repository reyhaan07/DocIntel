"""Sample intake PDFs and the standardized reference form.

Everything here is synthetic.  Four intake packets exercise the four ways a
PDF arrives in practice:

* ``intake_A_fillable_okafor.pdf``     - the reference form, filled in as AcroForm fields
* ``intake_B_flattened_lindqvist.pdf`` - the reference form, printed/flattened (no fields,
                                         ticked boxes are drawn, signatures are ink)
* ``intake_C_other_clinic_rivera.pdf`` - another clinic's layout with its own headings
* ``intake_D_scanned_rivera.pdf``      - a scan of packet C (image only, read through OCR)
* ``intake_E_scanned_lindqvist.pdf``   - a scan of packet B (drawn check boxes and ink on an image)

``patient_intake_v1.pdf`` (the blank fillable reference form) is written to the
package's template directory and is what standardized output is filled into.
"""
from __future__ import annotations

import io
import math
import random
from pathlib import Path

from reportlab.lib.colors import Color, HexColor, black, white
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

W, H = letter
L, R = 50.0, 562.0

BLUE = HexColor("#1f3a68")
GRAY = HexColor("#5b6472")
BOX = HexColor("#8a93a3")
RED = HexColor("#9b1c1c")

DRAWN = "~drawn~"  # marker: draw an ink signature instead of text


# --------------------------------------------------------------------------- helpers
class _Pen:
    """Small drawing helper that works in *top-left* coordinates."""

    def __init__(self, c: canvas.Canvas, mode: str, values: dict | None):
        self.c = c
        self.mode = mode  # "fillable" | "flattened"
        self.values = values or {}

    def y(self, top: float) -> float:
        return H - top

    def text(self, s, x, baseline, size=9.0, bold=False, color=black):
        self.c.setFillColor(color)
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        self.c.drawString(x, self.y(baseline), s)
        return x + stringWidth(s, "Helvetica-Bold" if bold else "Helvetica", size)

    def heading(self, s, top, x0=L, x1=R, color=BLUE, size=11.5):
        self.text(s, x0, top + 11, size=size, bold=True, color=color)
        self.c.setStrokeColor(color)
        self.c.setLineWidth(0.7)
        self.c.line(x0, self.y(top + 15), x1, self.y(top + 15))
        return top + 24

    def field(self, name, x, top, w, h=14.0, size=9.0):
        value = self.values.get(name, "")
        if self.mode == "fillable":
            self.c.acroForm.textfield(
                name=name, tooltip=name, x=x, y=self.y(top + h), width=w, height=h,
                value=value or "", fontName="Helvetica", fontSize=size, borderWidth=0.6,
                borderColor=BOX, fillColor=white, textColor=black, forceBorder=True,
            )
            return
        self.c.setStrokeColor(BOX)
        self.c.setLineWidth(0.6)
        if value == DRAWN:
            self.c.line(x, self.y(top + h), x + w, self.y(top + h))
            self.ink(x + 8, top + 1, min(w - 16, 120), h - 1)
            return
        self.c.rect(x, self.y(top + h), w, h, stroke=1, fill=0)
        if value:
            self.text(str(value), x + 2.5, top + 10.3, size=size)

    def labeled(self, label, name, x, top, total_w, h=14.0):
        end = self.text(label, x, top + 10.3, size=9)
        self.field(name, end + 3, top, max(20.0, x + total_w - end - 3), h)

    def checkbox(self, name, x, top, size=10.0):
        checked = bool(self.values.get(name))
        if self.mode == "fillable":
            self.c.acroForm.checkbox(
                name=name, tooltip=name, x=x, y=self.y(top + size), size=size, checked=checked,
                buttonStyle="cross", borderWidth=0.8, borderColor=BOX, fillColor=white,
                textColor=black, forceBorder=True,
            )
            return
        self.c.setStrokeColor(BOX)
        self.c.setLineWidth(0.8)
        self.c.rect(x, self.y(top + size), size, size, stroke=1, fill=0)
        if checked:
            self.c.setStrokeColor(black)
            self.c.setLineWidth(1.3)
            self.c.line(x + 2, self.y(top + 2), x + size - 2, self.y(top + size - 2))
            self.c.line(x + 2, self.y(top + size - 2), x + size - 2, self.y(top + 2))

    def ink(self, x, top, w, h, seed=7):
        """A handwritten-looking signature made of bezier curves."""
        rnd = random.Random(seed)
        c = self.c
        c.setStrokeColor(HexColor("#1c2b6b"))
        c.setLineWidth(1.1)
        p = c.beginPath()
        base = top + h * 0.65
        p.moveTo(x, self.y(base))
        steps = 6
        for i in range(steps):
            x0 = x + w * i / steps
            x1 = x + w * (i + 1) / steps
            up = top + rnd.uniform(0, h * 0.35)
            down = top + h * rnd.uniform(0.7, 1.0)
            p.curveTo(x0 + (x1 - x0) * 0.3, self.y(up), x0 + (x1 - x0) * 0.6, self.y(down), x1, self.y(base))
        c.drawPath(p, stroke=1, fill=0)
        p2 = c.beginPath()
        p2.moveTo(x + w * 0.15, self.y(top + h * 0.85))
        p2.curveTo(x + w * 0.4, self.y(top + h * 0.95), x + w * 0.7, self.y(top + h * 0.75), x + w * 0.95, self.y(top + h * 0.8))
        c.drawPath(p2, stroke=1, fill=0)

    def footer(self, s):
        self.text(s, L, 772, size=7.5, color=GRAY)


# --------------------------------------------------------------------------- reference form
MED_ROWS = 5
ALLERGY_ROWS = 4
SURGERY_ROWS = 3
RELEASE_ROWS = 2
FAMILY_ROWS = [("Mother", "mother"), ("Father", "father"), ("Sibling", "sibling")]
CONDITION_OPTIONS = [
    ("Diabetes", "diabetes"), ("Hypertension", "hypertension"), ("Heart disease", "heart_disease"),
    ("Asthma", "asthma"), ("Cancer", "cancer"), ("Depression/Anxiety", "depression_anxiety"),
    ("Thyroid disorder", "thyroid_disorder"), ("Arthritis", "arthritis"),
]
CONSENT_QUESTIONS = [
    ("May we leave a voicemail?", "voicemail"),
    ("May we send text messages?", "text"),
    ("May we contact you by email?", "email"),
]
AGREEMENTS = [
    ("Consent for Treatment", "cft", "I consent to evaluation and treatment by clinic providers."),
    ("Privacy Practices Acknowledgment", "npp", "I received the notice describing how my health information may be used."),
    ("Financial Responsibility Agreement", "fin", "I accept financial responsibility for charges not covered by insurance."),
]


def _std_page1(p: _Pen):
    p.text("PATIENT INTAKE FORM", L, 58, size=15, bold=True, color=BLUE)
    p.text("Standardized reference form  ·  patient_intake_v1  ·  please complete every section", L, 72, size=8, color=GRAY)
    c1, c2, c3 = L, L + 176, L + 346
    w1, w2, w3 = 168, 162, R - c3

    t = p.heading("Patient Information", 88)
    p.labeled("First Name:", "pt_first_name", c1, t, w1)
    p.labeled("Last Name:", "pt_last_name", c2, t, w2)
    p.labeled("Date of Birth:", "pt_dob", c3, t, w3)
    t += 20
    p.labeled("Sex:", "pt_sex", c1, t, w1)
    p.labeled("Marital Status:", "pt_marital", c2, t, w2)
    p.labeled("Phone:", "pt_phone", c3, t, w3)
    t += 20
    p.labeled("Street Address:", "pt_address", c1, t, R - c1)
    t += 20
    p.labeled("City:", "pt_city", c1, t, w1)
    p.labeled("State:", "pt_state", c2, t, w2)
    p.labeled("ZIP:", "pt_zip", c3, t, w3)
    t += 20
    p.labeled("Email:", "pt_email", c1, t, R - c1)

    t = p.heading("Spouse Information", 216)
    p.labeled("Spouse Name:", "sp_name", c1, t, w1 + 30)
    p.labeled("Date of Birth:", "sp_dob", c2 + 30, t, w2 - 30)
    p.labeled("Phone:", "sp_phone", c3, t, w3)

    t = p.heading("Emergency Contact", 264)
    p.labeled("Contact Name:", "ec_name", c1, t, w1 + 30)
    p.labeled("Relationship to Patient:", "ec_relationship", c2 + 30, t, w2 - 30)
    p.labeled("Phone:", "ec_phone", c3, t, w3)

    for top, title, pre in ((312, "Primary Insurance", "ins1"), (400, "Secondary Insurance", "ins2")):
        t = p.heading(title, top)
        p.labeled("Insurance Company:", f"{pre}_company", c1, t, 290)
        p.labeled("Insurance Phone:", f"{pre}_phone", c1 + 300, t, R - c1 - 300)
        t += 20
        p.labeled("Policy Holder Name:", f"{pre}_holder", c1, t, w1 + 30)
        p.labeled("Relationship to Patient:", f"{pre}_relationship", c2 + 30, t, w2 - 30)
        p.labeled("Holder DOB:", f"{pre}_holder_dob", c3, t, w3)
        t += 20
        p.labeled("Insurance ID:", f"{pre}_member_id", c1, t, 230)
        p.labeled("Group Number:", f"{pre}_group", c1 + 240, t, R - c1 - 240)

    p.heading("Current Medications", 488)
    p.text("List every prescription and over-the-counter medication you currently take.", L, 518, size=7.5, color=GRAY)
    cols = [(L, 172, "Medication Name", "name"), (L + 178, 96, "Dosage", "dose"),
            (L + 280, 112, "Frequency", "freq"), (L + 398, R - L - 398, "Prescribing Doctor", "doctor")]
    for x, _, label, _ in cols:
        p.text(label, x + 1, 532, size=8.5, bold=True)
    for i in range(MED_ROWS):
        top = 538 + i * 18
        for x, w, _, key in cols:
            p.field(f"med{i + 1}_{key}", x, top, w)
    p.footer("Form patient_intake_v1  ·  Page 1 of 3")


def _std_page2(p: _Pen):
    t = p.heading("Allergies", 50)
    cols = [(L, 194, "Allergen", "allergen"), (L + 200, 154, "Reaction", "reaction"), (L + 360, R - L - 360, "Severity", "severity")]
    for x, _, label, _ in cols:
        p.text(label, x + 1, t + 6, size=8.5, bold=True)
    for i in range(ALLERGY_ROWS):
        top = t + 12 + i * 18
        for x, w, _, key in cols:
            p.field(f"alg{i + 1}_{key}", x, top, w)

    t = p.heading("Medical History", 166)
    p.text("Tick every condition you have been diagnosed with.", L, t + 4, size=7.5, color=GRAY)
    t += 12
    for idx, (label, key) in enumerate(CONDITION_OPTIONS):
        row, col = divmod(idx, 4)
        x = L + col * 128
        top = t + row * 18
        p.checkbox(f"hx_{key}", x, top + 2)
        p.text(label, x + 15, top + 10.3, size=9)
    p.labeled("Other:", "hx_other", L, t + 36, R - L)

    t = p.heading("Surgical History", 262)
    cols = [(L, 214, "Procedure", "procedure"), (L + 220, 70, "Year", "year"), (L + 296, R - L - 296, "Facility", "facility")]
    for x, _, label, _ in cols:
        p.text(label, x + 1, t + 6, size=8.5, bold=True)
    for i in range(SURGERY_ROWS):
        top = t + 12 + i * 18
        for x, w, _, key in cols:
            p.field(f"surg{i + 1}_{key}", x, top, w)

    t = p.heading("Family Medical History", 360)
    cols = [(L, 80, "Relation", None), (L + 86, 96, "Living Status", "status"), (L + 188, 46, "Age", "age"),
            (L + 240, R - L - 240, "Conditions", "conditions")]
    for x, _, label, _ in cols:
        p.text(label, x + 1, t + 6, size=8.5, bold=True)
    for i, (label, key) in enumerate(FAMILY_ROWS):
        top = t + 12 + i * 18
        p.text(label, L + 1, top + 10.3, size=9)
        for x, w, _, ck in cols[1:]:
            p.field(f"fam_{key}_{ck}", x, top, w)

    t = p.heading("Communication Consent", 458)
    for i, (q, key) in enumerate(CONSENT_QUESTIONS):
        top = t + i * 20
        p.text(q, L, top + 10.3, size=9)
        p.checkbox(f"cc_{key}_yes", L + 300, top + 2)
        p.text("Yes", L + 314, top + 10.3, size=9)
        p.checkbox(f"cc_{key}_no", L + 360, top + 2)
        p.text("No", L + 374, top + 10.3, size=9)
    p.footer("Form patient_intake_v1  ·  Page 2 of 3")


def _std_page3(p: _Pen):
    t = p.heading("Release of Information", 50)
    p.text("I authorize release of my health information to the individuals listed below:", L, t + 10.3, size=9)
    p.checkbox("roi_yes", L + 380, t + 2)
    p.text("Yes", L + 394, t + 10.3, size=9)
    p.checkbox("roi_no", L + 430, t + 2)
    p.text("No", L + 444, t + 10.3, size=9)
    t += 24
    cols = [(L, 214, "Name", "name"), (L + 220, 134, "Relationship", "relationship"), (L + 360, R - L - 360, "Phone", "phone")]
    for x, _, label, _ in cols:
        p.text(label, x + 1, t + 6, size=8.5, bold=True)
    for i in range(RELEASE_ROWS):
        top = t + 12 + i * 18
        for x, w, _, key in cols:
            p.field(f"roi{i + 1}_{key}", x, top, w)

    top = 150
    for title, key, blurb in AGREEMENTS:
        t = p.heading(title, top)
        p.text(blurb, L, t + 4, size=7.5, color=GRAY)
        t += 14
        p.labeled("Signature:", f"{key}_signature", L, t, 220, h=16)
        p.labeled("Print Name:", f"{key}_print_name", L + 230, t, 170, h=16)
        p.labeled("Date:", f"{key}_date", L + 410, t, R - L - 410, h=16)
        top += 72
    p.footer("Form patient_intake_v1  ·  Page 3 of 3")


def draw_standard_form(path, mode: str = "fillable", values: dict | None = None, title: str = "Patient Intake Form"):
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle(title)
    c.setAuthor("docintel samples")
    pen = _Pen(c, mode, values)
    for draw in (_std_page1, _std_page2, _std_page3):
        draw(pen)
        c.showPage()
    c.save()


# --------------------------------------------------------------------------- sample data
OKAFOR = {
    "pt_first_name": "Chidi", "pt_last_name": "Okafor", "pt_dob": "03/02/1979", "pt_sex": "Male",
    "pt_marital": "Married", "pt_phone": "(312) 555-0118", "pt_address": "1180 Lakeview Avenue",
    "pt_city": "Chicago", "pt_state": "IL", "pt_zip": "60614", "pt_email": "chidi.okafor@example.com",
    "sp_name": "Amara Okafor", "sp_dob": "09/15/1981", "sp_phone": "(312) 555-0119",
    "ec_name": "Ngozi Okafor", "ec_relationship": "Sister", "ec_phone": "(312) 555-0175",
    "ins1_company": "Great Lakes Health Plan", "ins1_phone": "(800) 555-0144", "ins1_holder": "Chidi Okafor",
    "ins1_relationship": "Self", "ins1_holder_dob": "03/02/1979", "ins1_member_id": "GLH-5520184", "ins1_group": "GL-7710",
    "ins2_company": "Prairie Mutual", "ins2_phone": "(800) 555-0177", "ins2_holder": "Amara Okafor",
    "ins2_relationship": "Spouse", "ins2_holder_dob": "09/15/1981", "ins2_member_id": "PRM-302911", "ins2_group": "PM-118",
    "med1_name": "Atorvastatin", "med1_dose": "20 mg", "med1_freq": "Once daily", "med1_doctor": "Dr. Helen Park",
    "med2_name": "Amlodipine", "med2_dose": "5 mg", "med2_freq": "Once daily", "med2_doctor": "Dr. Helen Park",
    "med3_name": "Omeprazole", "med3_dose": "20 mg", "med3_freq": "Before breakfast", "med3_doctor": "Dr. Samuel Reyes",
    "med4_name": "Albuterol inhaler", "med4_dose": "2 puffs", "med4_freq": "As needed", "med4_doctor": "Dr. Samuel Reyes",
    "alg1_allergen": "Sulfa drugs", "alg1_reaction": "Rash", "alg1_severity": "Mild",
    "alg2_allergen": "Latex", "alg2_reaction": "Itching", "alg2_severity": "Moderate",
    "hx_hypertension": True, "hx_asthma": True, "hx_other": "High cholesterol",
    "surg1_procedure": "Knee arthroscopy", "surg1_year": "2015", "surg1_facility": "Northwestern Memorial Hospital",
    "surg2_procedure": "Tonsillectomy", "surg2_year": "1988", "surg2_facility": "Lagos University Teaching Hospital",
    "fam_mother_status": "Living", "fam_mother_age": "72", "fam_mother_conditions": "Hypertension, arthritis",
    "fam_father_status": "Deceased", "fam_father_age": "68", "fam_father_conditions": "Stroke",
    "cc_voicemail_yes": True, "cc_text_yes": True, "cc_email_yes": True,
    "roi_yes": True, "roi1_name": "Amara Okafor", "roi1_relationship": "Wife", "roi1_phone": "(312) 555-0119",
    "cft_signature": "/s/ Chidi Okafor", "cft_print_name": "Chidi Okafor", "cft_date": "11/04/2026",
    "npp_signature": "/s/ Chidi Okafor", "npp_print_name": "Chidi Okafor", "npp_date": "11/04/2026",
    "fin_signature": "/s/ Chidi Okafor", "fin_print_name": "Chidi Okafor", "fin_date": "11/04/2026",
}

LINDQVIST = {
    "pt_first_name": "Erik", "pt_last_name": "Lindqvist", "pt_dob": "11/21/1990", "pt_sex": "Male",
    "pt_marital": "Single", "pt_phone": "(608) 555-0123", "pt_address": "77 Birch Road",
    "pt_city": "Madison", "pt_state": "WI", "pt_zip": "53703", "pt_email": "erik.lindqvist@example.com",
    "ec_name": "Karin Lindqvist", "ec_relationship": "Mother", "ec_phone": "(608) 555-0161",
    "ins1_company": "Badger State Health", "ins1_phone": "(800) 555-0190", "ins1_holder": "Erik Lindqvist",
    "ins1_relationship": "Self", "ins1_holder_dob": "11/21/1990", "ins1_member_id": "BSH-889012", "ins1_group": "BS-404",
    "med1_name": "Levothyroxine", "med1_dose": "75 mcg", "med1_freq": "Once daily", "med1_doctor": "Dr. Maya Singh",
    "med2_name": "Cetirizine", "med2_dose": "10 mg", "med2_freq": "As needed", "med2_doctor": "Dr. Maya Singh",
    "alg1_allergen": "Peanuts", "alg1_reaction": "Anaphylaxis", "alg1_severity": "Severe",
    "hx_thyroid_disorder": True, "hx_asthma": True,
    "surg1_procedure": "Appendectomy", "surg1_year": "2008", "surg1_facility": "St. Luke's Hospital",
    "fam_mother_status": "Living", "fam_mother_age": "61", "fam_mother_conditions": "Thyroid disease",
    "fam_father_status": "Living", "fam_father_age": "63", "fam_father_conditions": "High blood pressure",
    "cc_voicemail_yes": True, "cc_text_no": True, "cc_email_yes": True,
    "roi_no": True,
    "cft_signature": DRAWN, "cft_print_name": "Erik Lindqvist", "cft_date": "10/28/2026",
    "npp_signature": DRAWN, "npp_print_name": "Erik Lindqvist", "npp_date": "10/28/2026",
    "fin_signature": DRAWN, "fin_print_name": "Karin Lindqvist", "fin_date": "10/28/2026",
}


# --------------------------------------------------------------------------- other clinic layout
def make_riverside(path, title="Riverside New Patient Packet", extras: bool = False):
    """A different clinic's packet: its own headings, side-by-side insurance,
    drug/prescribed-by/dose/how-often medication table, printed [X] boxes."""
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle(title)
    c.setAuthor("docintel samples")
    p = _Pen(c, "flattened", {})
    X = 54.0
    RR = 558.0

    def kv(label, value, x, baseline, size=9.5):
        end = p.text(f"{label}:", x, baseline, size=size)
        if value:
            p.text(value, end + 3.5, baseline, size=size)

    def head(s, top, x0=X, x1=RR):
        return p.heading(s, top, x0, x1, color=RED, size=11)

    # ---- page 1
    p.text("EXAMPLE RIVERSIDE CLINIC", X, 60, size=15, bold=True, color=RED)
    p.text("New Patient Registration Packet  -  please print clearly", X, 73, size=8.5, color=GRAY)

    head("PATIENT DEMOGRAPHICS", 92)
    kv("Patient Name", "Rivera, Maria L.", X, 120); kv("DOB", "7/14/1985", X + 300, 120); kv("Gender", "Female", X + 410, 120)
    kv("Street Address", "42 Elm Street", X, 136); kv("Marital Status", "Married", X + 300, 136)
    kv("City", "Springfield", X, 152); kv("State", "IL", X + 92, 152); kv("Zip", "62704", X + 142, 152)
    if extras:  # a field the template does not know
        kv("Referred By", "Dr. Ellen Shaw", X + 300, 152)
    kv("Mobile Phone", "217.555.0143", X, 168); kv("E-mail", "maria.rivera@example.com", X + 300, 168)

    head("SPOUSE / PARTNER", 186)
    kv("Name", "Daniel Rivera", X, 212); kv("Date of Birth", "03-22-1983", X + 220, 212); kv("Phone", "(217) 555-0190", X + 400, 212)

    head("IN CASE OF EMERGENCY", 230)
    kv("Contact Name", "Ana Lopez", X, 256); kv("Relationship", "Sister", X + 220, 256); kv("Phone", "217-555-0177", X + 400, 256)

    head("PRIMARY INSURANCE", 274, X, X + 250)
    head("SECONDARY INSURANCE", 274, X + 282, RR)
    prim = [("Carrier", "Blue River Health"), ("Subscriber Name", "Maria Rivera"), ("Relationship to Patient", "Self"),
            ("Subscriber DOB", "07/14/1985"), ("Member ID", "BRH-4471920"), ("Group #", "GRP-2210"), ("Phone", "800-555-0101")]
    sec = [("Carrier", "Lakeside Mutual"), ("Subscriber Name", "Daniel Rivera"), ("Relationship to Patient", "Spouse"),
           ("Subscriber DOB", "03/22/1983"), ("Member ID", "LKM-88120"), ("Group #", "5590-A"), ("Phone", "800-555-0199")]
    for i, ((l1, v1), (l2, v2)) in enumerate(zip(prim, sec)):
        kv(l1, v1, X, 300 + i * 16)
        kv(l2, v2, X + 282, 300 + i * 16)

    head("MEDICATION LIST", 416)
    p.text("Please include vitamins and supplements.", X, 442, size=8.5, color=GRAY)
    mc = [X, X + 170, X + 290, X + 390]
    for x, h in zip(mc, ["Drug", "Prescribed By", "Dose", "How Often"]):
        p.text(h, x, 460, size=9.5, bold=True)
    meds = [("Metformin", "Dr. Alan Chen", "500 mg", "Twice daily"),
            ("Lisinopril", "Dr. Alan Chen", "10 mg", "Once daily"),
            ("Sertraline", "Dr. Priya Nair", "50 mg", "Once daily"),
            ("Vitamin D3", "", "1000 IU", "Daily")]
    for i, row in enumerate(meds):
        for x, v in zip(mc, row):
            if v:
                p.text(v, x, 478 + i * 18, size=9.5)
    p.text("(with breakfast)", mc[3], 478 + 3 * 18 + 12, size=9.5)

    head("DRUG ALLERGIES", 566)
    ac = [X, X + 170, X + 330]
    for x, h in zip(ac, ["Allergen", "Reaction", "Severity"]):
        p.text(h, x, 592, size=9.5, bold=True)
    for i, row in enumerate([("Penicillin", "Hives", "Moderate"), ("Shellfish", "Throat swelling", "Severe")]):
        for x, v in zip(ac, row):
            p.text(v, x, 610 + i * 18, size=9.5)

    head("MEDICAL CONDITIONS", 650)
    grid = [[("[X]", "Diabetes"), ("[X]", "Hypertension"), ("[ ]", "Heart disease"), ("[ ]", "Asthma")],
            [("[ ]", "Cancer"), ("[X]", "Depression/Anxiety"), ("[ ]", "Thyroid disorder")]]
    for r, row in enumerate(grid):
        for col, (box, label) in enumerate(row):
            x = X + col * 128
            p.text(f"{box}  {label}", x, 676 + r * 16, size=9.5)
    kv("Other", "Migraines", X, 708)
    p.text("Riverside registration packet", RR - 112, 772, size=7.5, color=GRAY)
    c.showPage()

    # ---- page 2
    p.c = c
    head("SURGICAL HISTORY", 54)
    sc = [X, X + 200, X + 270]
    for x, h in zip(sc, ["Surgery", "Year", "Facility"]):
        p.text(h, x, 80, size=9.5, bold=True)
    for i, row in enumerate([("Appendectomy", "2009", "Springfield General Hospital"),
                             ("Cesarean section", "2016", "St. Mary's Medical Center")]):
        for x, v in zip(sc, row):
            p.text(v, x, 98 + i * 18, size=9.5)

    head("FAMILY HISTORY", 140)
    kv("Mother", "Living, age 66 - Type 2 diabetes, hypertension", X, 166)
    kv("Father", "Deceased, age 70 - Heart disease, stroke", X, 182)

    head("COMMUNICATION PREFERENCES", 204)
    for i, (q, yes, no) in enumerate([("May we leave a voicemail?", "[X]", "[ ]"),
                                      ("May we send text messages?", "[X]", "[X]"),
                                      ("May we contact you by email?", "[ ]", "[X]")]):
        end = p.text(q, X, 230 + i * 16, size=9.5)
        p.text(f"{yes} Yes     {no} No", end + 10, 230 + i * 16, size=9.5)

    head("RELEASE OF INFORMATION", 284)
    end = p.text("I authorize release of my health information to the individuals listed below:", X, 310, size=9.5)
    p.text("[X] Yes     [ ] No", end + 10, 310, size=9.5)
    rc = [X, X + 200, X + 330]
    for x, h in zip(rc, ["Name", "Relationship", "Phone"]):
        p.text(h, x, 330, size=9.5, bold=True)
    for x, v in zip(rc, ["Daniel Rivera", "Husband", "217-555-0190"]):
        p.text(v, x, 348, size=9.5)

    head("CONSENT FOR TREATMENT", 372)
    p.text("I consent to evaluation and treatment by Riverside providers.", X, 398, size=8.5, color=GRAY)
    p.text("Patient Signature:", X, 424, size=9.5)
    p.ink(X + 96, 410, 110, 18, seed=3)
    kv("Print Name", "Maria Rivera", X + 250, 424)
    kv("Date", "11/03/2026", X + 400, 424)

    head("PRIVACY PRACTICES ACKNOWLEDGMENT", 446)
    p.text("I received the clinic's notice describing how my health information may be used.", X, 472, size=8.5, color=GRAY)
    kv("Signature", "/s/ Maria Rivera", X, 496)
    kv("Date", "11/03/2026", X + 400, 496)

    head("FINANCIAL POLICY", 518)
    p.text("I accept responsibility for charges not covered by insurance.", X, 544, size=8.5, color=GRAY)
    p.text("Signature:", X, 568, size=9.5)
    p.ink(X + 60, 554, 100, 18, seed=11)
    kv("Print Name", "Ana Lopez", X + 250, 568)
    kv("Date", "11/03/2026", X + 400, 568)
    if extras:  # a whole section the template does not know
        head("TRANSPORTATION", 600)
        kv("Driver Name", "Tom Rivera", X, 626)
        kv("Phone", "217-555-0110", X + 300, 626)
    p.text("Riverside registration packet", RR - 112, 772, size=7.5, color=GRAY)
    c.showPage()
    c.save()


# --------------------------------------------------------------------------- scanned copy
def make_scanned(src, path, dpi: int = 110, seed: int = 5, angles: list[float] | None = None):
    """Rasterise ``src`` and wrap the page images in an image-only PDF."""
    import pypdfium2 as pdfium
    from PIL import Image, ImageFilter
    from reportlab.lib.utils import ImageReader

    from .render import PDFIUM_LOCK

    rnd = random.Random(seed)
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle("Scanned intake packet")
    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(str(src))
        images = []
        for i in range(len(doc)):
            img = doc[i].render(scale=dpi / 72).to_pil().convert("L")
            images.append(img)
        doc.close()
    for i, img in enumerate(images):
        angle = angles[i % len(angles)] if angles else rnd.uniform(-0.6, 0.6)
        img = img.rotate(angle, resample=Image.BICUBIC, fillcolor=255)
        px = img.load()
        w, h = img.size
        for _ in range(w * h // 180):
            x, y = rnd.randrange(w), rnd.randrange(h)
            px[x, y] = max(0, px[x, y] - rnd.randrange(40, 120))
        img = img.filter(ImageFilter.GaussianBlur(0.35))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=72)
        buf.seek(0)
        c.drawImage(ImageReader(buf), 0, 0, width=W, height=H)
        c.showPage()
    c.save()


# --------------------------------------------------------------------------- documents of other kinds
def _simple_doc(path, title: str, draw):
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle(title)
    c.setAuthor("docintel samples")
    p = _Pen(c, "flattened", {})
    draw(p)
    c.showPage()
    c.save()


def make_lab_report(path):
    """A laboratory report: not an intake form, read with the template-free structure."""
    GREEN = HexColor("#1d5c46")
    X = 54.0

    def kv(p, label, value, x, baseline):
        end = p.text(f"{label}:", x, baseline, size=9.5)
        p.text(value, end + 4, baseline, size=9.5)

    def draw(p):
        p.text("CITY LAB SERVICES", X, 60, size=16, bold=True, color=GREEN)
        p.text("Clinical Laboratory Report  -  1200 Grand Avenue, Springfield", X, 74, size=8.5, color=GRAY)
        p.heading("PATIENT", 96, X, 558, color=GREEN, size=11)
        kv(p, "Name", "Harper, Lena J.", X, 124); kv(p, "DOB", "02/11/1972", X + 230, 124); kv(p, "Sex", "F", X + 400, 124)
        kv(p, "MRN", "0042-8817", X, 140); kv(p, "Phone", "(217) 555-0148", X + 230, 140)
        p.heading("ORDER", 162, X, 558, color=GREEN, size=11)
        kv(p, "Ordering Physician", "Dr. Omar Haddad", X, 190); kv(p, "Specimen", "Serum", X + 300, 190)
        kv(p, "Collected", "11/02/2026", X, 206); kv(p, "Received", "11/02/2026", X + 300, 206)
        p.heading("RESULTS", 228, X, 558, color=GREEN, size=11)
        cols = [X, X + 160, X + 230, X + 300, X + 420]
        for x, h in zip(cols, ["Test", "Result", "Units", "Reference Range", "Flag"]):
            p.text(h, x, 256, size=9.5, bold=True)
        rows = [("Glucose", "112", "mg/dL", "70-99", "H"), ("Hemoglobin A1c", "6.1", "%", "4.0-5.6", "H"),
                ("Total Cholesterol", "182", "mg/dL", "< 200", ""), ("LDL Cholesterol", "104", "mg/dL", "< 100", "H"),
                ("HDL Cholesterol", "48", "mg/dL", "> 40", ""), ("Creatinine", "0.9", "mg/dL", "0.6-1.2", "")]
        for i, row in enumerate(rows):
            for x, v in zip(cols, row):
                if v:
                    p.text(v, x, 274 + i * 17, size=9.5)
        p.heading("COMMENTS", 392, X, 558, color=GREEN, size=11)
        p.text("Glucose and HbA1c are above the reference range. Repeat fasting glucose is recommended.", X, 418, size=9)
        end = p.text("Was the patient fasting?", X, 440, size=9.5)
        p.text("[X] Yes     [ ] No", end + 12, 440, size=9.5)
        p.heading("VERIFICATION", 462, X, 558, color=GREEN, size=11)
        p.text("Reviewed by:", X, 490, size=9.5)
        p.ink(X + 72, 476, 110, 18, seed=21)
        kv(p, "Date", "11/03/2026", X + 300, 490)
        p.text("City Lab Services - results are for the ordering clinician", 558 - 210, 772, size=7.5, color=GRAY)

    _simple_doc(path, "Laboratory report", draw)


def make_invoice(path):
    """A supplier invoice: a document outside healthcare intake entirely."""
    NAVY = HexColor("#22304f")
    X = 54.0

    def kv(p, label, value, x, baseline, bold=False):
        end = p.text(f"{label}:", x, baseline, size=9.5)
        p.text(value, end + 4, baseline, size=9.5, bold=bold)

    def draw(p):
        p.text("NORTHWIND OFFICE SUPPLY", X, 60, size=16, bold=True, color=NAVY)
        p.text("44 Harbor Street, Portland, OR 97204  -  billing@northwind.example", X, 74, size=8.5, color=GRAY)
        p.heading("INVOICE", 96, X, 558, color=NAVY, size=11)
        kv(p, "Invoice No", "INV-20817", X, 124); kv(p, "Invoice Date", "10/30/2026", X + 280, 124)
        kv(p, "PO Number", "4471", X, 140); kv(p, "Due Date", "11/29/2026", X + 280, 140)
        p.heading("BILL TO", 162, X, 558, color=NAVY, size=11)
        kv(p, "Company", "Riverside Family Clinic", X, 190); kv(p, "Attention", "Accounts Payable", X + 280, 190)
        kv(p, "Address", "18 River Road, Springfield, IL 62704", X, 206)
        p.heading("ITEMS", 228, X, 558, color=NAVY, size=11)
        cols = [X, X + 70, X + 300, X + 350, X + 430]
        for x, h in zip(cols, ["Item", "Description", "Qty", "Unit Price", "Amount"]):
            p.text(h, x, 256, size=9.5, bold=True)
        rows = [("P-1001", "Exam table paper, 21 in", "12", "$18.50", "$222.00"),
                ("P-2040", "Nitrile gloves, medium (box)", "20", "$9.75", "$195.00"),
                ("P-3302", "Printer toner, black", "4", "$89.00", "$356.00"),
                ("P-4410", "Clipboards, letter size", "30", "$15.60", "$468.00")]
        for i, row in enumerate(rows):
            for x, v in zip(cols, row):
                p.text(v, x, 274 + i * 17, size=9.5)
        p.heading("TOTALS", 356, X, 558, color=NAVY, size=11)
        kv(p, "Subtotal", "$1,241.00", X + 300, 384)
        kv(p, "Tax", "$99.28", X + 300, 400)
        kv(p, "Total Due", "$1,340.28", X + 300, 416, bold=True)
        p.heading("PAYMENT", 438, X, 558, color=NAVY, size=11)
        end = p.text("Paid by check?", X, 466, size=9.5)
        p.text("[ ] Yes     [X] No", end + 12, 466, size=9.5)
        p.text("Authorized Signature:", X, 490, size=9.5)
        p.ink(X + 112, 476, 100, 18, seed=33)
        kv(p, "Date", "10/30/2026", X + 300, 490)

    _simple_doc(path, "Invoice INV-20817", draw)


# --------------------------------------------------------------------------- entry point
def reference_form_path() -> Path:
    return Path(__file__).parent / "templates" / "patient_intake_v1.pdf"


def generate_all(input_dir: str | Path = "samples/input", upload_dir: str | Path | None = "samples/upload",
                 reference: bool = True) -> list[Path]:
    input_dir = Path(input_dir)
    input_dir.mkdir(parents=True, exist_ok=True)
    out = []
    if reference:
        draw_standard_form(reference_form_path(), "fillable", {}, title="Patient Intake Form (patient_intake_v1)")
        out.append(reference_form_path())
    a = input_dir / "intake_A_fillable_okafor.pdf"
    draw_standard_form(a, "fillable", OKAFOR)
    b = input_dir / "intake_B_flattened_lindqvist.pdf"
    draw_standard_form(b, "flattened", LINDQVIST)
    cc = input_dir / "intake_C_other_clinic_rivera.pdf"
    make_riverside(cc)
    d = input_dir / "intake_D_scanned_rivera.pdf"
    make_scanned(cc, d)
    e = input_dir / "intake_E_scanned_lindqvist.pdf"
    make_scanned(b, e, seed=9)
    lab = input_dir / "lab_report_harper.pdf"
    make_lab_report(lab)
    inv = input_dir / "invoice_northwind.pdf"
    make_invoice(inv)
    out += [a, b, cc, d, e, lab, inv]
    if upload_dir:
        upload_dir = Path(upload_dir)
        upload_dir.mkdir(parents=True, exist_ok=True)
        n = upload_dir / "new_patient_riverside.pdf"
        make_riverside(n, title="New patient - Riverside")
        out.append(n)
    return out


if __name__ == "__main__":  # pragma: no cover
    for f in generate_all():
        print(f)
