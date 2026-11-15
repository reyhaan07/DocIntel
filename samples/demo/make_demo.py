"""Make the demo files that are not already among the samples: a phone photo of a
receipt and a clean invoice with 'Seller:' / 'Client:' blocks.  Every name, address and
number in them is invented.

    python samples/demo/make_demo.py
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


if __name__ == "__main__":
    receipt_photo(HERE / "receipt_photo.jpg")
    invoice_pdf(HERE / "invoice_seller_client.pdf")
    print("written:", HERE / "receipt_photo.jpg", HERE / "invoice_seller_client.pdf")
