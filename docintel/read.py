"""Stage 1 - Read.

Turns a PDF into positioned tokens per page:

* filled AcroForm fields are read directly from the form (value + widget rectangle),
* flattened pages are read word by word with their positions,
* ticked boxes are detected visually (ink inside small printed squares) or from
  printed markers such as ``[X]`` / ``[ ]``,
* drawn signatures are kept as ink marks,
* image-only (scanned) pages are flagged and, when an OCR engine is available and
  requested, read through OCR.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from .models import Mark, PageData, Token

CHECK_ON = {"[x]", "[✓]", "[✔]", "[v]", "☒", "☑", "✓", "✔", "■"}
CHECK_OFF = {"[ ]", "[]", "☐", "□"}
_OCR_BOX = re.compile(r"^[\[{(|lI]\s*([xXkK×]?)\s*[\]})|lI1J]$")
_BOX_PREFIX = re.compile(r"^(\[\s*[xX✓✔vV]?\s*\]|☒|☑|☐|□)(.+)$")

FOOTER_MARGIN = 36.0


def ocr_available() -> bool:
    try:
        import pytesseract  # noqa: F401
    except Exception:
        return False
    return shutil.which("tesseract") is not None


# --------------------------------------------------------------------------- text checkboxes
def _checkbox_state(text: str) -> bool | None:
    t = text.strip().lower().replace(" ", "")
    if t in {c.replace(" ", "") for c in CHECK_ON}:
        return True
    if t in {c.replace(" ", "") for c in CHECK_OFF}:
        return False
    return None


def _normalise_checkbox_tokens(tokens: list[Token]) -> list[Token]:
    # split "[X]Yes" style tokens
    split: list[Token] = []
    for t in tokens:
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
                out.append(Token(text, x0, top, x1, bottom, number, "form_field", field_name=name, conf=0.98))
            elif placeholders:
                out.append(Token("", x0, top, x1, bottom, number, "form_field", kind="placeholder", field_name=name))
    return out


# --------------------------------------------------------------------------- OCR
def _ocr_tokens(pdf_path: Path, number: int) -> list[Token]:
    import pytesseract

    from .render import render_page_gray

    scale = 300 / 72
    img = render_page_gray(pdf_path, number, scale=scale)
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config="--psm 11")
    out = []
    for i, text in enumerate(data["text"]):
        text = (text or "").strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1
        if not text or conf < 30:
            continue
        if re.fullmatch(r"[|_{}\[\]()\\/~`'\".,:;-]+", text) and text not in ("[]",):
            continue  # scanner noise / table rules
        box = _OCR_BOX.match(text)
        if box:
            text = "[X]" if box.group(1).strip() else "[ ]"
        if text.endswith(";") and text[:-1].isalpha():
            text = text[:-1] + ":"
        x0 = data["left"][i] / scale
        top = data["top"][i] / scale
        x1 = x0 + data["width"][i] / scale
        bottom = top + data["height"][i] / scale
        out.append(Token(text, x0, top, x1, bottom, number, "ocr", conf=conf / 100.0))
    return out


def _image_ink_marks(pdf_path: Path, number: int, tokens: list[Token]) -> list[Mark]:
    """Ink on a scanned page that OCR did not read as text (e.g. handwritten signatures)."""
    from .render import render_page_gray

    scale, cell = 1.5, 3.0
    img = render_page_gray(pdf_path, number, scale=scale)
    w, h = img.size
    px = img.load()
    cols, rows = int(w / (cell * scale)) + 1, int(h / (cell * scale)) + 1
    dark = [[False] * cols for _ in range(rows)]
    for y in range(0, h):
        for x in range(0, w):
            if px[x, y] < 110:
                dark[int(y / (cell * scale))][int(x / (cell * scale))] = True
    for t in tokens:  # text already explained by OCR is not ink
        for r in range(max(0, int((t.top - 2) / cell)), min(rows, int((t.bottom + 2) / cell) + 1)):
            for c in range(max(0, int((t.x0 - 2) / cell)), min(cols, int((t.x1 + 2) / cell) + 1)):
                dark[r][c] = False
    seen = [[False] * cols for _ in range(rows)]
    marks = []
    for r in range(rows):
        for c in range(cols):
            if not dark[r][c] or seen[r][c]:
                continue
            stack, cells = [(r, c)], []
            seen[r][c] = True
            while stack:
                y, x = stack.pop()
                cells.append((y, x))
                for dy in (-1, 0, 1):
                    for dx in (-2, -1, 0, 1, 2):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < rows and 0 <= nx < cols and dark[ny][nx] and not seen[ny][nx]:
                            seen[ny][nx] = True
                            stack.append((ny, nx))
            ys = [y for y, _ in cells]
            xs = [x for _, x in cells]
            x0, x1 = min(xs) * cell, (max(xs) + 1) * cell
            t0, t1 = min(ys) * cell, (max(ys) + 1) * cell
            if (x1 - x0) >= 30 and 7 <= (t1 - t0) <= 45 and len(cells) < 0.8 * ((max(xs) - min(xs) + 1) * (max(ys) - min(ys) + 1)):
                marks.append(Mark(number, x0, t0, x1, t1, kind="image"))
    return marks


# --------------------------------------------------------------------------- entry point
def read_pdf(path: str | Path, *, ocr: bool = False, placeholders: bool = False) -> list[PageData]:
    import pdfplumber
    from pypdf import PdfReader

    path = Path(path)
    reader = PdfReader(str(path))
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
            tokens = _normalise_checkbox_tokens(tokens)
            tokens += _visual_checkboxes(path, page, number, tokens)
            form = _form_tokens(reader, i, number, placeholders)
            pd.form_fields = len(form)
            # printed borders of form widgets are not separate checkboxes
            tokens = [t for t in tokens if not (t.source == "visual" and any(
                f.x0 - 2 <= t.cx <= f.x1 + 2 and f.top - 2 <= t.cy <= f.bottom + 2 for f in form))]
            tokens += form
            pd.marks = _ink_marks(page, number, W, H)
            if not pd.has_text and not form:
                big = [im for im in page.images
                       if (im["x1"] - im["x0"]) * (im["bottom"] - im["top"]) > 0.5 * W * H]
                if big:
                    pd.image_only = True
                    pd.marks = []
                    if ocr and ocr_available():
                        tokens = _normalise_checkbox_tokens(_ocr_tokens(path, number))
                        pd.marks = _image_ink_marks(path, number, tokens)
                        pd.ocr_used = True
            # drop running headers/footers in the outer margins
            tokens = [t for t in tokens if t.top < H - FOOTER_MARGIN or t.kind != "word"]
            pd.tokens = tokens
            pages.append(pd)
    return pages
