"""Make the ten demo documents - one per kind of document and file format.  Every name,
address and number in them is invented.

    python samples/demo/make_demo.py

    01_invoice.pdf               invoice, text PDF ('Seller:' / 'Client:' blocks, totals table)
    02_receipt_photo.jpg         cafe receipt, phone photo (tilted, uneven light)
    03_bank_statement.pdf        bank statement, text PDF
    04_payslip.docx              payslip, Word
    05_utility_bill_scan.png     electricity bill, scanned image
    06_discharge_summary.pdf     hospital discharge summary, text PDF
    07_prescription_scan.pdf     prescription, scanned PDF (no text layer)
    08_purchase_order.xlsx       purchase order, Excel
    09_payment_reminder.eml      e-mail that carries an invoice
    10_insurance_claim_form.pdf  insurance claim, fillable PDF form

Regenerating needs reportlab and Pillow (installed with docintel) and python-docx and
openpyxl (pip install python-docx openpyxl); the files themselves are in the repository.
"""
from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent


def _font(size: int, bold: bool = False):
    names = (["DejaVuSansMono-Bold.ttf", "courbd.ttf"] if bold else []) + ["DejaVuSansMono.ttf", "cour.ttf",
                                                                       "Courier New.ttf", "LiberationMono-Regular.ttf"]
    for n in names:
        for d in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation", "C:/Windows/Fonts",
                  "/Library/Fonts", "/System/Library/Fonts/Supplemental", ""):
            try:
                return ImageFont.truetype(str(Path(d) / n) if d else n, size)
            except OSError:
                continue
    return ImageFont.load_default()


def receipt_photo(dest: Path) -> None:
    lines = [
        ("KOPI SENJA CAFE", True), ("Jl. Melati No. 12, Bandung", False), ("Tel 022-555-0142", False), ("", False),
        ("Bill No: 0418-2207", False), ("Date: 14/03/2026  19:42", False), ("Cashier: Dewi", False),
        ("-" * 32, False),
        ("2 Iced Latte           58,000", False), ("1 Banana Bread         27,000", False),
        ("1 Mineral Water         9,000", False), ("-" * 32, False),
        ("SUBTOTAL               94,000", False), ("TAX 10%                 9,400", False),
        ("TOTAL                 103,400", True), ("CASH                  110,000", False),
        ("CHANGE                  6,600", False), ("-" * 32, False), ("THANK YOU - COME AGAIN", False),
    ]
    f, fb = _font(30), _font(34, bold=True)
    w, line_h = 640, 46
    paper = Image.new("L", (w, 60 + line_h * len(lines) + 60), 246)
    d = ImageDraw.Draw(paper)
    for i, (text, bold) in enumerate(lines):
        font = fb if bold else f
        tw = d.textlength(text, font=font)
        x = (w - tw) / 2 if bold or not text[:1].isdigit() and "  " not in text else 40
        d.text((x, 60 + i * line_h), text, fill=40, font=font)
    rnd = random.Random(7)
    for _ in range(4000):  # thermal paper grain
        x, y = rnd.randrange(paper.width), rnd.randrange(paper.height)
        paper.putpixel((x, y), max(0, paper.getpixel((x, y)) - rnd.randint(10, 40)))
    mask = Image.new("L", paper.size, 255).rotate(3.5, expand=True, fillcolor=0, resample=Image.BICUBIC)
    paper = paper.convert("RGB").rotate(3.5, expand=True, fillcolor=(0, 0, 0), resample=Image.BICUBIC)
    photo = Image.new("RGB", (paper.width + 260, paper.height + 260), (58, 46, 38))  # a wooden table
    td = ImageDraw.Draw(photo)
    for y in range(0, photo.height, 9):
        td.line([(0, y), (photo.width, y + rnd.randint(-4, 4))], fill=(66 + rnd.randint(-6, 6), 52, 42), width=4)
    photo.paste(paper, (130, 130), mask)
    # uneven light: brighter top left, a soft shadow lower right
    shade = Image.radial_gradient("L").resize(photo.size).point(lambda v: int(150 + v * 0.42))
    photo = Image.composite(photo, Image.new("RGB", photo.size, (0, 0, 0)), shade.point(lambda v: 255 - (v - 150)))
    photo = photo.filter(ImageFilter.GaussianBlur(0.8))
    photo.save(dest, quality=88)


def invoice_pdf(dest: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(dest), pagesize=A4)
    W, H = A4
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, H - 60, "Invoice no: 51840277")
    c.setFont("Helvetica", 11)
    c.drawString(50, H - 85, "Date of issue:")
    c.drawString(300, H - 85, "03/02/2026")
    c.setFont("Helvetica-Bold", 13)
    c.drawString(50, H - 150, "Seller:")
    c.drawString(320, H - 150, "Client:")
    c.setFont("Helvetica", 11)
    for i, (a, b) in enumerate([("Harbor Lab Supply Ltd", "Riverside Family Clinic"),
                                ("41 Wharf Road", "300 Elm Street, Suite 4"),
                                ("Portland, OR 97209", "Springfield, IL 62704")]):
        c.drawString(52, H - 172 - i * 16, a)
        c.drawString(322, H - 172 - i * 16, b)
    c.drawString(52, H - 235, "Tax Id: 912-44-7031")
    c.drawString(322, H - 235, "Tax Id: 877-10-5520")
    c.setFont("Helvetica-Bold", 13)
    c.drawString(50, H - 290, "ITEMS")
    cols = [(50, "No."), (90, "Description"), (300, "Qty"), (350, "Net price"), (430, "VAT [%]"), (500, "Gross worth")]
    c.setFont("Helvetica-Bold", 10)
    for x, t in cols:
        c.drawString(x, H - 315, t)
    rows = [("1.", "Nitrile gloves (box of 100)", "10", "12,50", "10%", "137,50"),
            ("2.", "Sharps container 5 L", "4", "9,00", "10%", "39,60"),
            ("3.", "Exam table paper roll", "6", "7,25", "10%", "47,85")]
    c.setFont("Helvetica", 10)
    for i, r in enumerate(rows):
        for (x, _), v in zip(cols, r):
            c.drawString(x, H - 335 - i * 18, v)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(50, H - 420, "SUMMARY")
    c.setFont("Helvetica-Bold", 10)
    for x, t in ((300, "Net worth"), (390, "VAT"), (470, "Gross worth")):
        c.drawString(x, H - 445, t)
    c.setFont("Helvetica", 10)
    for x, t in ((300, "203,59"), (390, "20,36"), (470, "224,95")):
        c.drawString(x, H - 463, t)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(200, H - 481, "Total")
    for x, t in ((300, "$ 203,59"), (390, "$ 20,36"), (470, "$ 224,95")):
        c.drawString(x, H - 481, t)
    c.save()



# --------------------------------------------------------------------------- shared helpers
def _pdf_page(dest: Path, draw) -> None:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(dest), pagesize=letter)
    draw(c, *letter)
    c.save()


def _table(c, x0, y, cols, rows, size=10, step=17, bold_header=True):
    c.setFont("Helvetica-Bold" if bold_header else "Helvetica", size)
    for x, t in cols:
        c.drawString(x0 + x, y, t)
    c.setLineWidth(0.6)
    c.line(x0, y - 5, x0 + cols[-1][0] + 90, y - 5)
    c.setFont("Helvetica", size)
    for i, r in enumerate(rows):
        for (x, _), v in zip(cols, r):
            c.drawString(x0 + x, y - (i + 1) * step - 2, v)
    return y - (len(rows) + 1) * step - 2


def _scan(pdf: Path, dest: Path, angle: float, seed: int) -> None:
    """Render a page and make it look scanned: grey paper, speckle, a slight tilt."""
    import pypdfium2 as pdfium

    page = pdfium.PdfDocument(str(pdf))[0]
    img = page.render(scale=200 / 72).to_pil().convert("L")
    rnd = random.Random(seed)
    px = img.load()
    for _ in range(img.width * img.height // 400):
        x, y = rnd.randrange(img.width), rnd.randrange(img.height)
        px[x, y] = max(0, px[x, y] - rnd.randint(60, 140))
    img = img.point(lambda v: int(v * 0.93 + 8))
    img = img.rotate(angle, resample=Image.BICUBIC, fillcolor=236).filter(ImageFilter.GaussianBlur(0.5))
    if dest.suffix.lower() == ".pdf":
        img.save(dest, "PDF", resolution=200.0)
    else:
        img.save(dest, dpi=(200, 200))


# --------------------------------------------------------------------------- 03 bank statement
def bank_statement(dest: Path) -> None:
    def draw(c, W, H):
        c.setFont("Helvetica-Bold", 18)
        c.drawString(50, H - 60, "Cedar Valley Bank")
        c.setFont("Helvetica", 9)
        c.drawString(50, H - 74, "220 Main Street, Riverton, WY 82501  -  www.cedarvalley.example")
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, H - 110, "ACCOUNT STATEMENT")
        c.setFont("Helvetica", 10)
        for i, (k, v) in enumerate([("Account Holder:", "Amara Okafor"), ("Account Number:", "4471 0092 5813"),
                                    ("Statement Period:", "02/01/2026 to 02/28/2026"),
                                    ("Opening Balance:", "$3,240.18"), ("Closing Balance:", "$4,105.62")]):
            c.drawString(50, H - 140 - i * 16, k)
            c.drawString(170, H - 140 - i * 16, v)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, H - 240, "Transactions")
        rows = [("02/01/2026", "Salary - Northwind Logistics", "", "3,850.00", "7,090.18"),
                ("02/03/2026", "Rent - Lakeview Apartments", "1,950.00", "", "5,140.18"),
                ("02/09/2026", "Groceries - FreshMart", "186.40", "", "4,953.78"),
                ("02/14/2026", "Summit Energy - electricity", "112.66", "", "4,841.12"),
                ("02/20/2026", "Refund - Brightpath Supplies", "", "42.50", "4,883.62"),
                ("02/27/2026", "Transfer to savings", "778.00", "", "4,105.62")]
        _table(c, 50, H - 265, [(0, "Date"), (80, "Description"), (285, "Debit"), (355, "Credit"), (430, "Balance")], rows)
        c.setFont("Helvetica", 8)
        c.drawString(50, 50, "Questions about this statement? Call 1-800-555-0199. Page 1 of 1")
    _pdf_page(dest, draw)


# --------------------------------------------------------------------------- 04 payslip (Word)
def payslip(dest: Path) -> None:
    import docx

    d = docx.Document()
    d.add_heading("Northwind Logistics Ltd", level=1)
    d.add_paragraph("PAYSLIP")
    for k, v in [("Employee Name", "Daniel Moreau"), ("Employee ID", "NL-20417"), ("Department", "Warehouse Operations"),
                 ("Pay Period", "March 2026"), ("Pay Date", "03/31/2026")]:
        p = d.add_paragraph()
        p.add_run(f"{k}: ").bold = True
        p.add_run(v)
    d.add_heading("Earnings", level=2)
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Description", "Amount"
    for a, b in [("Basic salary", "$4,200.00"), ("Overtime", "$315.00"), ("Meal allowance", "$150.00")]:
        r = t.add_row().cells
        r[0].text, r[1].text = a, b
    d.add_heading("Deductions", level=2)
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Description", "Amount"
    for a, b in [("Income tax", "$698.25"), ("Pension", "$233.25"), ("Health insurance", "$85.00")]:
        r = t.add_row().cells
        r[0].text, r[1].text = a, b
    for k, v in [("Gross Pay", "$4,665.00"), ("Total Deductions", "$1,016.50"), ("Net Pay", "$3,648.50")]:
        p = d.add_paragraph()
        p.add_run(f"{k}: ").bold = True
        p.add_run(v)
    d.save(str(dest))


# --------------------------------------------------------------------------- 05 utility bill (scan)
def utility_bill_scan(dest: Path, tmp: Path) -> None:
    def draw(c, W, H):
        c.setFont("Helvetica-Bold", 20)
        c.drawString(50, H - 60, "Summit Energy")
        c.setFont("Helvetica-Bold", 13)
        c.drawString(50, H - 95, "ELECTRICITY BILL")
        c.setFont("Helvetica", 11)
        for i, (k, v) in enumerate([("Account Number:", "88-301-4472"), ("Customer:", "Amara Okafor"),
                                    ("Service Address:", "17 Lakeview Drive, Fairview, OR 97024"),
                                    ("Billing Period:", "02/01/2026 - 02/28/2026"), ("Meter Number:", "MTR-559102"),
                                    ("Usage:", "612 kWh")]):
            c.drawString(50, H - 130 - i * 20, k)
            c.drawString(180, H - 130 - i * 20, v)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, H - 270, "Charges")
        _table(c, 50, H - 292, [(0, "Description"), (260, "Amount")],
               [("Energy charge 612 kWh", "$97.92"), ("Delivery charge", "$22.40"), ("Taxes and fees", "$8.15")], size=11, step=19)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(50, H - 400, "Amount Due:")
        c.drawString(180, H - 400, "$128.47")
        c.drawString(50, H - 422, "Due Date:")
        c.drawString(180, H - 422, "03/20/2026")
        c.setFont("Helvetica", 9)
        c.drawString(50, 60, "Pay online at summitenergy.example or call 1-800-555-0144.")
    pdf = tmp / "05.pdf"
    _pdf_page(pdf, draw)
    _scan(pdf, dest, angle=0.8, seed=5)


# --------------------------------------------------------------------------- 06 discharge summary
def discharge_summary(dest: Path) -> None:
    def draw(c, W, H):
        c.setFont("Helvetica-Bold", 18)
        c.drawString(50, H - 60, "Oakridge General Hospital")
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, H - 90, "DISCHARGE SUMMARY")
        c.setFont("Helvetica", 10.5)
        for i, (k, v) in enumerate([("Patient Name:", "Lena Harper"), ("MRN:", "0042-8817"),
                                    ("Date of Birth:", "09/23/1979"), ("Admission Date:", "02/10/2026"),
                                    ("Discharge Date:", "02/14/2026"), ("Attending Physician:", "Dr. Omar Haddad"),
                                    ("Diagnosis:", "Community-acquired pneumonia")]):
            c.drawString(50, H - 120 - i * 17, k)
            c.drawString(190, H - 120 - i * 17, v)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, H - 255, "Hospital Course")
        c.setFont("Helvetica", 10.5)
        for i, ln in enumerate(["Admitted with fever, cough and shortness of breath. Chest X-ray confirmed right",
                                "lower lobe pneumonia. Treated with intravenous antibiotics, switched to oral",
                                "therapy on day 3. Afebrile for 48 hours before discharge."]):
            c.drawString(50, H - 275 - i * 15, ln)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, H - 340, "Discharge Medications")
        _table(c, 50, H - 362, [(0, "Medication"), (170, "Dose"), (260, "Frequency")],
               [("Amoxicillin", "500 mg", "three times daily for 5 days"), ("Paracetamol", "1 g", "every 6 hours as needed")])
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, H - 440, "Follow-up")
        c.setFont("Helvetica", 10.5)
        c.drawString(50, H - 460, "Review with Dr. Omar Haddad in 2 weeks. Repeat chest X-ray in 6 weeks.")
        c.drawString(50, H - 520, "Signature:")
        c.setLineWidth(1.2)
        p = c.beginPath()
        p.moveTo(120, H - 522)
        for k in range(1, 12):
            p.lineTo(120 + k * 9, H - 522 + (6 if k % 2 else -4))
        c.drawPath(p)
        c.drawString(300, H - 520, "Date: 02/14/2026")
    _pdf_page(dest, draw)


# --------------------------------------------------------------------------- 07 prescription (scanned PDF)
def prescription_scan(dest: Path, tmp: Path) -> None:
    def draw(c, W, H):
        c.setFont("Helvetica-Bold", 18)
        c.drawString(60, H - 70, "Lakeside Medical Clinic")
        c.setFont("Helvetica", 10)
        c.drawString(60, H - 86, "45 Harbor Road, Riverton, WY 82501  -  Tel (307) 555-0175")
        c.setFont("Helvetica-Bold", 15)
        c.drawString(60, H - 125, "PRESCRIPTION")
        c.setFont("Helvetica", 12)
        for i, (k, v) in enumerate([("Patient Name:", "Mateo Silva"), ("Date of Birth:", "11/02/1961"),
                                    ("Date:", "03/05/2026"), ("Prescriber:", "Dr. Priya Shah")]):
            c.drawString(60, H - 160 - i * 22, k)
            c.drawString(190, H - 160 - i * 22, v)
        c.setFont("Helvetica-Bold", 26)
        c.drawString(60, H - 275, "Rx")
        c.setFont("Helvetica", 12)
        for i, (k, v) in enumerate([("Medication:", "Lisinopril 10 mg tablets"), ("Sig:", "1 tablet by mouth once daily"),
                                    ("Dispense:", "30 tablets"), ("Refills:", "2")]):
            c.drawString(110, H - 275 - i * 22, k)
            c.drawString(210, H - 275 - i * 22, v)
        c.drawString(60, H - 420, "Signature:")
        c.setLineWidth(1.4)
        p = c.beginPath()
        p.moveTo(140, H - 422)
        for k in range(1, 14):
            p.lineTo(140 + k * 8, H - 422 + (7 if k % 2 else -5))
        c.drawPath(p)
    pdf = tmp / "07.pdf"
    _pdf_page(pdf, draw)
    _scan(pdf, dest, angle=-1.2, seed=7)


# --------------------------------------------------------------------------- 08 purchase order (Excel)
def purchase_order(dest: Path) -> None:
    import openpyxl
    from openpyxl.styles import Font

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Purchase Order"
    ws["A1"] = "Pioneer Logistics"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "PURCHASE ORDER"
    rows = [("PO Number", "PO-2026-0381"), ("Order Date", "03/09/2026"), ("Vendor", "Brightpath Supplies Inc"),
            ("Ship To", "Pioneer Logistics, 9 Harbor Way, Tacoma, WA 98402"), ("Delivery Date", "03/20/2026")]
    for i, (k, v) in enumerate(rows, start=4):
        ws.cell(row=i, column=1, value=k).font = Font(bold=True)
        ws.cell(row=i, column=2, value=v)
    head = ("Item", "Qty", "Unit Price", "Amount")
    for j, h in enumerate(head, start=1):
        ws.cell(row=11, column=j, value=h).font = Font(bold=True)
    items = [("Pallet wrap film", "12", "$18.50", "$222.00"), ("Packing tape (case)", "8", "$41.00", "$328.00"),
             ("Corrugated boxes (bundle)", "20", "$29.70", "$594.00"), ("Shipping labels (roll)", "10", "$14.00", "$140.00")]
    for i, r in enumerate(items, start=12):
        for j, v in enumerate(r, start=1):
            ws.cell(row=i, column=j, value=v)
    ws.cell(row=18, column=1, value="Total").font = Font(bold=True)
    ws.cell(row=18, column=2, value="$1,284.00")
    for col, w in zip("ABCD", (30, 48, 14, 14)):
        ws.column_dimensions[col].width = w
    wb.save(str(dest))


# --------------------------------------------------------------------------- 09 payment reminder (e-mail)
def payment_reminder(dest: Path) -> None:
    from email.message import EmailMessage

    m = EmailMessage()
    m["From"] = "Summit Energy Accounts <accounts@summitenergy.example>"
    m["To"] = "Amara Okafor <amara.okafor@example.com>"
    m["Date"] = "Mon, 16 Mar 2026 09:12:00 +0000"
    m["Subject"] = "Payment reminder - Invoice SE-77120"
    m.set_content("Dear Amara Okafor,\n\nThis is a friendly reminder that the invoice below is due soon.\n\n"
                  "Invoice Number: SE-77120\nInvoice Date: 03/01/2026\nAccount Number: 88-301-4472\n"
                  "Amount Due: $128.47\nDue Date: 03/20/2026\n\n"
                  "You can pay online at summitenergy.example or by calling 1-800-555-0144.\n\n"
                  "Kind regards,\nSummit Energy Accounts Team\n")
    dest.write_bytes(bytes(m))


# --------------------------------------------------------------------------- 10 insurance claim (fillable PDF)
def insurance_claim(dest: Path) -> None:
    from reportlab.lib.colors import black, white

    def draw(c, W, H):
        c.setFont("Helvetica-Bold", 18)
        c.drawString(50, H - 60, "Evergreen Insurance")
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, H - 90, "HEALTH INSURANCE CLAIM FORM")
        c.setFont("Helvetica", 9)
        c.drawString(50, H - 106, "Please complete all fields. Attach itemised bills.")
        form = c.acroForm
        fields = [("Policy Number:", "policy_number", "EVG-55-210984"), ("Claim Number:", "claim_number", "CLM-0091237"),
                  ("Insured Name:", "insured_name", "Amara Okafor"), ("Date of Birth:", "date_of_birth", "07/14/1988"),
                  ("Phone:", "phone", "(503) 555-0186"), ("Date of Service:", "date_of_service", "02/14/2026"),
                  ("Provider:", "provider", "Oakridge General Hospital"), ("Diagnosis:", "diagnosis", "Pneumonia"),
                  ("Amount Claimed:", "amount_claimed", "$2,480.00")]
        c.setFont("Helvetica", 11)
        for i, (lab, name, val) in enumerate(fields):
            y = H - 145 - i * 30
            c.drawString(50, y, lab)
            form.textfield(name=name, tooltip=lab.rstrip(":"), x=170, y=y - 6, width=260, height=20, value=val,
                           borderColor=black, fillColor=white, textColor=black, fontSize=11, forceBorder=True)
        y = H - 145 - len(fields) * 30 - 10
        c.drawString(50, y, "Accident related?")
        c.drawString(205, y, "Yes")
        form.checkbox(name="accident_yes", x=180, y=y - 3, size=14, checked=False, buttonStyle="cross", borderColor=black)
        c.drawString(270, y, "No")
        form.checkbox(name="accident_no", x=245, y=y - 3, size=14, checked=True, buttonStyle="cross", borderColor=black)
        y -= 50
        c.drawString(50, y, "Signature:")
        form.textfield(name="signature", tooltip="Signature", x=170, y=y - 6, width=160, height=20, value="A. Okafor",
                       borderColor=black, fillColor=white, textColor=black, fontSize=11, forceBorder=True)
        c.drawString(345, y, "Date:")
        form.textfield(name="date_signed", tooltip="Date signed", x=385, y=y - 6, width=100, height=20, value="03/02/2026",
                       borderColor=black, fillColor=white, textColor=black, fontSize=11, forceBorder=True)
    _pdf_page(dest, draw)


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        invoice_pdf(HERE / "01_invoice.pdf")
        receipt_photo(HERE / "02_receipt_photo.jpg")
        bank_statement(HERE / "03_bank_statement.pdf")
        payslip(HERE / "04_payslip.docx")
        utility_bill_scan(HERE / "05_utility_bill_scan.png", tmp)
        discharge_summary(HERE / "06_discharge_summary.pdf")
        prescription_scan(HERE / "07_prescription_scan.pdf", tmp)
        purchase_order(HERE / "08_purchase_order.xlsx")
        payment_reminder(HERE / "09_payment_reminder.eml")
        insurance_claim(HERE / "10_insurance_claim_form.pdf")
    print("written to", HERE)
