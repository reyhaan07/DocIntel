"""Fill real fillable PDFs with chosen values (the truth), and flatten a copy."""
import io, json, random, re, sys
from pathlib import Path
import pypdf
from pypdf.generic import NameObject, BooleanObject
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth

RAW, OUT = Path(sys.argv[1]), Path(sys.argv[2])
FIRST = ["Jordan", "Avery", "Morgan", "Riley", "Casey", "Taylor", "Quinn", "Harper", "Rowan", "Elliot"]
LAST = ["Delgado", "Okafor", "Lindqvist", "Nakamura", "Brennan", "Castillo", "Haddad", "Petrov", "Osei", "Varga"]


def value_for(desc: str, n: int, rnd):
    d = desc.lower()
    if re.search(r"\bssn\b|social security", d):
        return f"9{rnd.randint(10,99)}-{rnd.randint(10,99)}-{rnd.randint(1000,9999)}"
    if re.search(r"\bein\b|employer identification", d):
        return f"{rnd.randint(10,98)}-{rnd.randint(1000000,9999999)}"
    if re.search(r"e-?mail", d):
        return f"{rnd.choice(FIRST).lower()}.{rnd.choice(LAST).lower()}@example.com"
    if re.search(r"phone|telephone|fax", d):
        return f"({rnd.randint(201,989)}) 555-{rnd.randint(1000,9999)}"
    if re.search(r"\bzip\b|postal", d):
        return f"{rnd.randint(10000,99999)}"
    if re.search(r"\bdate\b|\bdob\b|birth", d):
        return f"{rnd.randint(1,12):02d}/{rnd.randint(1,28):02d}/{rnd.randint(1950,2026)}"
    if re.search(r"\bcity\b|town", d):
        return rnd.choice(["Springfield", "Riverton", "Fairview", "Lakewood", "Oak Ridge"])
    if re.search(r"\bstate\b", d) and len(d) < 40:
        return rnd.choice(["IL", "TX", "OH", "WA", "GA"])
    if re.search(r"address|street", d):
        return f"{rnd.randint(10,9999)} {rnd.choice(['Elm', 'Cedar', 'Lake', 'Hill', 'Maple'])} {rnd.choice(['Street', 'Avenue', 'Road', 'Lane'])}"
    if re.search(r"\bname\b|signature of|print", d):
        return f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"
    if re.search(r"amount|\$|wages|tax|income|total|payment|balance|dollars", d):
        return f"{rnd.randint(100,99999):,}.{rnd.randint(0,99):02d}"
    if re.search(r"\bnumber\b|\bno\b|\bid\b|account", d):
        return f"{rnd.choice('ABCDEFGHJK')}{rnd.choice('LMNPQRSTUV')}-{rnd.randint(100000,999999)}"
    return f"Item{n:02d} {rnd.choice(['North', 'Delta', 'Summit', 'Harbor', 'Crest'])}"


for src in sorted(RAW.glob("*.pdf")):
    rnd = random.Random(src.name)
    try:
        r = pypdf.PdfReader(str(src))
        if r.is_encrypted:
            r.decrypt("")
    except Exception as e:
        print("skip", src.name, e); continue
    truth, widgets = [], []
    for pno, page in enumerate(r.pages[:2], start=1):
        for a in page.get("/Annots") or []:
            a = a.get_object()
            if a.get("/Subtype") != "/Widget":
                continue
            par = a.get("/Parent").get_object() if a.get("/Parent") else None
            ft = a.get("/FT") or (par.get("/FT") if par else None)
            name = a.get("/T") or (par.get("/T") if par else None)
            tip = a.get("/TU") or (par.get("/TU") if par else None)
            rect = [float(v) for v in a.get("/Rect")]
            x0, y0, x1, y1 = min(rect[0], rect[2]), min(rect[1], rect[3]), max(rect[0], rect[2]), max(rect[1], rect[3])
            maxlen = a.get("/MaxLen") or (par.get("/MaxLen") if par else None)
            if ft == "/Tx" and x1 - x0 >= 40 and y1 - y0 >= 8 and name and (maxlen is None or int(maxlen) >= 5):
                widgets.append((pno, page, a, par, str(name), str(tip or name), (x0, y0, x1, y1), maxlen))
    rnd.shuffle(widgets)
    widgets = sorted(widgets[:25], key=lambda w: (w[0], -w[6][1], w[6][0]))
    if len(widgets) < 5:
        print("too few fields", src.name, len(widgets)); continue
    w = pypdf.PdfWriter(clone_from=r)
    vals_by_page = {}
    for n, (pno, page, a, par, name, tip, rect, maxlen) in enumerate(widgets):
        v = value_for(tip + " " + name, n, rnd)
        if maxlen is not None and len(v) > int(maxlen):
            v = "".join(str(rnd.randint(0, 9)) for _ in range(int(maxlen)))
        H = float(r.pages[pno - 1].mediabox.top)
        truth.append({"name": name, "tooltip": tip, "value": v, "page": pno,
                      "rect": [rect[0], H - rect[3], rect[2], H - rect[1]]})
        vals_by_page.setdefault(pno, {})[name] = v
    for pno, vals in vals_by_page.items():
        w.update_page_form_field_values(w.pages[pno - 1], vals, auto_regenerate=False)
    w._root_object["/AcroForm"][NameObject("/NeedAppearances")] = BooleanObject(True)
    stem = src.stem.replace(" ", "_")
    fill = OUT / f"gov_{stem}_fillable.pdf"
    with open(fill, "wb") as fh:
        w.write(fh)
    # flattened copy: the values printed where the fields were, the fields removed
    r2 = pypdf.PdfReader(str(src))
    if r2.is_encrypted:
        r2.decrypt("")
    w2 = pypdf.PdfWriter()
    for pno, page in enumerate(r2.pages, start=1):
        mb = page.mediabox
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(float(mb.width), float(mb.height)))
        for t in truth:
            if t["page"] != pno:
                continue
            x0, top, x1, bottom = t["rect"]
            size = 9
            while stringWidth(t["value"], "Helvetica", size) > (x1 - x0 - 4) and size > 5:
                size -= 0.5
            c.setFont("Helvetica", size)
            c.drawString(x0 + 2, float(mb.top) - bottom + (bottom - top - size) / 2 + 1.5, t["value"])
        c.showPage()
        c.save()
        overlay = pypdf.PdfReader(io.BytesIO(buf.getvalue())).pages[0]
        if "/Annots" in page:
            del page[NameObject("/Annots")]
        page.merge_page(overlay)
        w2.add_page(page)
    flat = OUT / f"gov_{stem}_flattened.pdf"
    with open(flat, "wb") as fh:
        w2.write(fh)
    for f in (fill, flat):
        (OUT / (f.stem + ".truth.json")).write_text(json.dumps(truth, indent=1))
    print("ok", src.name, len(truth))
