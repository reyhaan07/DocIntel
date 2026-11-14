"""Stage 1 - Read.

Turns a PDF into positioned tokens per page:

* filled AcroForm fields are read directly from the form (value + widget rectangle),
* flattened pages are read word by word with their positions,
* ticked boxes are detected visually (ink inside small printed squares) or from
  printed markers such as ``[X]`` / ``[ ]``,
* drawn signatures are kept as ink marks,
* image-only (scanned) pages are read through local OCR (see ``ocr.py``) when an
  OCR engine is installed, and flagged as needing OCR otherwise.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import ocr as ocr_engine
from .models import Mark, PageData, Token

CHECK_ON = {"[x]", "[✓]", "[✔]", "[v]", "☒", "☑", "✓", "✔", "■"}
CHECK_OFF = {"[ ]", "[]", "☐", "□"}
_BOX_SUFFIX = re.compile(r"^(.*?[A-Za-z?:.])(\[\s*[xX✓✔vV]?\s*\]|☒|☑|☐|□)$")
_BOX_PREFIX = re.compile(r"^(\[\s*[xX✓✔vV]?\s*\]|☒|☑|☐|□)(.+)$")



def ocr_available() -> bool:
    return ocr_engine.available()


# --------------------------------------------------------------------------- text checkboxes
def _checkbox_state(text: str) -> bool | None:
    t = text.strip().lower().replace(" ", "")
    if t in {c.replace(" ", "") for c in CHECK_ON}:
        return True
    if t in {c.replace(" ", "") for c in CHECK_OFF}:
        return False
    return None


def _normalise_checkbox_tokens(tokens: list[Token]) -> list[Token]:
    # split "[X]Yes" and "No[]" style tokens (OCR often glues a box to its label)
    split: list[Token] = []
    for t in tokens:
        ms = _BOX_SUFFIX.match(t.text) if t.kind == "word" else None
        if ms:
            word, box = ms.group(1), ms.group(2)
            frac = len(word) / max(1, len(t.text))
            xm = t.x0 + (t.x1 - t.x0) * frac
            split.append(Token(word, t.x0, t.top, xm - 1, t.bottom, t.page, t.source, conf=t.conf, size=t.size))
            split.append(Token(box, xm, t.top, t.x1, t.bottom, t.page, t.source, conf=t.conf, size=t.size))
            continue
        m = _BOX_PREFIX.match(t.text)
        if m and t.kind == "word":
            box, rest = m.group(1), m.group(2)
            frac = len(box) / max(1, len(t.text))
            xm = t.x0 + (t.x1 - t.x0) * frac
            split.append(Token(box, t.x0, t.top, xm, t.bottom, t.page, t.source, conf=t.conf, size=t.size))
            split.append(Token(rest, xm + 1, t.top, t.x1, t.bottom, t.page, t.source, conf=t.conf, size=t.size))
        else:
            split.append(t)
    # merge "[" + "]" printed with a space between them
    out: list[Token] = []
    i = 0
    while i < len(split):
        t = split[i]
        if t.text == "[" and i + 1 < len(split):
            n = split[i + 1]
            if n.text == "]" and abs(n.cy - t.cy) < 3 and 0 <= n.x0 - t.x1 < 9:
                out.append(Token("[ ]", t.x0, min(t.top, n.top), n.x1, max(t.bottom, n.bottom), t.page, t.source,
                                 kind="checkbox", checked=False, conf=t.conf, size=t.size))
                i += 2
                continue
        state = _checkbox_state(t.text) if t.kind == "word" else None
        if state is not None:
            t.kind = "checkbox"
            t.checked = state
            t.text = "[X]" if state else "[ ]"
        out.append(t)
        i += 1
    return out


# --------------------------------------------------------------------------- visual checkboxes
def _visual_checkboxes(pdf_path: Path, page, number: int, tokens: list[Token]) -> list[Token]:
    squares = []
    for r in page.rects:
        w, h = r["x1"] - r["x0"], r["bottom"] - r["top"]
        if 6 <= w <= 16 and 6 <= h <= 16 and abs(w - h) <= 2.5:
            squares.append((r["x0"], r["top"], r["x1"], r["bottom"]))
    if not squares:
        return []
    from .render import render_page_gray

    scale = 3.0
    img = render_page_gray(pdf_path, number, scale=scale)
    px = img.load()
    out = []
    for x0, top, x1, bottom in squares:
        inset = 2.0
        X0, Y0 = int((x0 + inset) * scale), int((top + inset) * scale)
        X1, Y1 = int((x1 - inset) * scale), int((bottom - inset) * scale)
        total = dark = 0
        for yy in range(max(0, Y0), min(img.size[1], Y1)):
            for xx in range(max(0, X0), min(img.size[0], X1)):
                total += 1
                if px[xx, yy] < 140:
                    dark += 1
        ratio = dark / total if total else 0.0
        checked = ratio > 0.06
        # a typed "X" inside the square also counts; drop that word so it is not read as text
        for t in list(tokens):
            if t.kind == "word" and t.text.strip().lower() in {"x", "✓", "✔"} and x0 - 1 <= t.cx <= x1 + 1 and top - 1 <= t.cy <= bottom + 1:
                tokens.remove(t)
                checked = True
        out.append(Token("[X]" if checked else "[ ]", x0, top, x1, bottom, number, "visual", kind="checkbox",
                         checked=checked, conf=0.9))
    return out


# --------------------------------------------------------------------------- ink marks
def _ink_marks(page, number: int, W: float, H: float) -> list[Mark]:
    boxes = []
    for c in page.curves:
        pts = [pt for seg in c.get("path") or [] for pt in seg[1:] if isinstance(pt, tuple)] or c.get("pts") or []
        if pts:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            boxes.append([min(xs), min(ys), max(xs), max(ys)])
        else:
            boxes.append([c["x0"], c["top"], c["x1"], c["bottom"]])
    marks: list[list[float]] = []
    for b in sorted(boxes, key=lambda b: b[0]):
        for m in marks:
            if b[0] <= m[2] + 8 and b[2] >= m[0] - 8 and b[1] <= m[3] + 8 and b[3] >= m[1] - 8:
                m[0], m[1], m[2], m[3] = min(m[0], b[0]), min(m[1], b[1]), max(m[2], b[2]), max(m[3], b[3])
                break
        else:
            marks.append(list(b))
    out = [Mark(number, *m, kind="drawn") for m in marks if (m[2] - m[0]) > 15]
    for im in page.images:
        w, h = im["x1"] - im["x0"], im["bottom"] - im["top"]
        if w * h < 0.25 * W * H and w > 20 and h > 6:
            out.append(Mark(number, im["x0"], im["top"], im["x1"], im["bottom"], kind="image"))
    return out


# --------------------------------------------------------------------------- form fields
def _inherited(obj, key):
    seen = 0
    while obj is not None and seen < 20:
        if key in obj:
            return obj[key]
        obj = obj.get("/Parent")
        obj = obj.get_object() if obj is not None else None
        seen += 1
    return None


def _full_name(annot) -> str:
    parts = []
    obj = annot
    seen = 0
    while obj is not None and seen < 20:
        if "/T" in obj:
            parts.append(str(obj["/T"]))
        obj = obj.get("/Parent")
        obj = obj.get_object() if obj is not None else None
        seen += 1
    return ".".join(reversed(parts))


def _form_tokens(reader, page_index: int, number: int, placeholders: bool) -> list[Token]:
    page = reader.pages[page_index]
    annots = page.get("/Annots")
    if not annots:
        return []
    mb = page.mediabox
    top_y = float(mb.top)
    out = []
    for ref in annots.get_object():
        a = ref.get_object()
        if a.get("/Subtype") != "/Widget":
            continue
        rect = [float(v) for v in a.get("/Rect", [0, 0, 0, 0])]
        x0, x1 = min(rect[0], rect[2]), max(rect[0], rect[2])
        y0, y1 = min(rect[1], rect[3]), max(rect[1], rect[3])
        top, bottom = top_y - y1, top_y - y0
        name = _full_name(a)
        ft = _inherited(a, "/FT")
        if ft == "/Btn":
            flags = int(_inherited(a, "/Ff") or 0)
            if flags & (1 << 16):  # push button
                continue
            state = a.get("/AS")
            if state is None:
                v = _inherited(a, "/V")
                state = v
            checked = state is not None and str(state) not in ("/Off", "Off", "")
            out.append(Token("[X]" if checked else "[ ]", x0, top, x1, bottom, number, "form_field", kind="checkbox",
                             checked=checked, field_name=name, conf=0.98))
        elif ft in ("/Tx", "/Ch"):
            v = _inherited(a, "/V")
            text = str(v).strip() if v is not None else ""
            if isinstance(v, list):
                text = ", ".join(str(x) for x in v)
            if text:
                tip = _inherited(a, "/TU")
                out.append(Token(text, x0, top, x1, bottom, number, "form_field", field_name=name, conf=0.98,
                                 hint=str(tip).strip() if tip else None))
            elif placeholders:
                out.append(Token("", x0, top, x1, bottom, number, "form_field", kind="placeholder", field_name=name))
    return out


# --------------------------------------------------------------------------- text-layer quality
_WORDLIKE = re.compile(r"^[\[\(\"'“‘]*[A-Za-z0-9][A-Za-z0-9'’.,:;/()&%$#@+\-–—!?\]\"”]*$")


def _unreadable(tokens: list[Token]) -> bool:
    """True when most 'words' of a text layer are not words (garbage OCR layer, broken font encoding)."""
    words = [t.text for t in tokens if t.kind == "word"]
    if len(words) < 8:
        return False
    if sum("(cid:" in w or "\ufffd" in w for w in words) > 0.2 * len(words):
        return True
    good = sum(1 for w in words if _WORDLIKE.match(w) and sum(c.isalnum() for c in w) >= max(1, len(w) // 2))
    return good < 0.5 * len(words)


# --------------------------------------------------------------------------- entry point
def read_pdf(path: str | Path, *, ocr: bool | str = "auto", placeholders: bool = False) -> list[PageData]:
    """``ocr``: "auto" (default) reads scanned pages when an OCR engine is installed,
    True forces OCR (error if no engine), False never runs OCR."""
    import pdfplumber
    from pypdf import PdfReader

    path = Path(path)
    if ocr is True and not ocr_engine.available():
        raise RuntimeError("OCR was requested but no OCR engine is installed "
                           "(pip install pytesseract, and install the tesseract program)")
    run_ocr = bool(ocr) and ocr_engine.available()
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            ok = reader.decrypt("")
        except Exception:
            ok = 0
        if not ok:
            raise RuntimeError("this PDF is password-protected; it cannot be read without its password")
    pages: list[PageData] = []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages):
            number = i + 1
            W, H = float(page.width), float(page.height)
            pd = PageData(number=number, width=W, height=H)
            words = page.extract_words(extra_attrs=["fontname", "size"], x_tolerance=1.5, y_tolerance=2,
                                       keep_blank_chars=False, use_text_flow=False)
            tokens = [
                Token(w["text"], float(w["x0"]), float(w["top"]), float(w["x1"]), float(w["bottom"]), number,
                      "text", bold="bold" in str(w.get("fontname", "")).lower(), size=float(w.get("size") or 0))
                for w in words
            ]
            pd.has_text = bool(tokens)
            pd.text_layer = "good" if tokens else "none"
            if tokens and _unreadable(tokens):
                # a garbage text layer (bad scanner OCR, broken font encoding) is not trusted
                tokens = []
                pd.has_text = False
                pd.text_layer = "unreadable"
            tokens = _normalise_checkbox_tokens(tokens)
            tokens += _visual_checkboxes(path, page, number, tokens)
            form = _form_tokens(reader, i, number, placeholders)
            pd.form_fields = len(form)
            # printed borders of form widgets are not separate checkboxes
            tokens = [t for t in tokens if not (t.source == "visual" and any(
                f.x0 - 2 <= t.cx <= f.x1 + 2 and f.top - 2 <= t.cy <= f.bottom + 2 for f in form))]
            tokens += form
            pd.marks = _ink_marks(page, number, W, H)
            # drawn boxes that hold (or could hold) a value: wide, one text line tall
            pd.boxes = [(r["x0"], r["top"], r["x1"], r["bottom"]) for r in page.rects
                        if r["x1"] - r["x0"] >= 20 and 9 <= r["bottom"] - r["top"] <= 40
                        and r["x1"] - r["x0"] < 0.95 * W]
            if not pd.has_text and not form:
                big = [im for im in page.images
                       if (im["x1"] - im["x0"]) * (im["bottom"] - im["top"]) > 0.5 * W * H]
                if big or pd.text_layer == "unreadable":
                    pd.image_only = True
                    pd.marks = []
                    if run_ocr:
                        res = ocr_engine.ocr_page(path, number, W, H)
                        tokens = _normalise_checkbox_tokens(res.tokens)
                        pd.marks = res.marks
                        pd.deskew_angle = res.angle
                        pd.rotation = res.rotation
                        pd.width, pd.height = res.width, res.height
                        pd.ocr_used = True
            elif run_ocr and pd.has_text:
                # a digital page carrying an embedded scan: read the scan too
                scans = [im for im in page.images
                         if (im["x1"] - im["x0"]) * (im["bottom"] - im["top"]) > 0.25 * W * H]
                for im in scans:
                    inside = [t for t in tokens if im["x0"] <= t.cx <= im["x1"] and im["top"] <= t.cy <= im["bottom"]]
                    if len(inside) >= 5:
                        continue
                    res = ocr_engine.ocr_page(path, number, W, H, deskew=False, orient=False)
                    extra = [t for t in res.tokens if im["x0"] <= t.cx <= im["x1"] and im["top"] <= t.cy <= im["bottom"]
                             and not any(o.x0 <= t.cx <= o.x1 and o.top <= t.cy <= o.bottom for o in tokens)]
                    tokens += _normalise_checkbox_tokens(extra)
                    pd.marks += [m for m in res.marks if im["x0"] <= (m.x0 + m.x1) / 2 <= im["x1"]
                                 and im["top"] <= m.cy <= im["bottom"]]
                    pd.ocr_regions += 1
                    pd.ocr_used = True
            pd.tokens = tokens
            pages.append(pd)
    # running headers and footers are kept but marked, so they are never read as data
    from .layout import mark_furniture

    mark_furniture(pages)
    return pages
