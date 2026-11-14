"""OCR for scanned (image-only) pages.

Everything runs locally: the page image is rendered from the PDF, straightened
(deskew, pure numpy/PIL), read by the Tesseract engine through ``pytesseract``,
and then analysed again for things OCR does not read as text - drawn check boxes
(ticked or empty) and ink signatures.  No network service and no language model
is involved.

Tokens come back in the coordinates of the *straightened* page so that lines
and table columns line up; :func:`unskew_bbox` maps any box back onto the
original scan for display and for the JSON output.
"""
from __future__ import annotations

import math
import re
import shutil
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .models import Mark, Token

DPI = 300
SCALE = DPI / 72.0
# Two page-segmentation modes read different words well on forms: 11 (sparse text)
# and 6 (uniform block).  Both run and are merged word by word.
TESSERACT_PASSES = ("--psm 11", "--psm 6")

_NOISE = re.compile(r"[|_{}\[\]()\\/~`'\".,:;\-—–=+*“”‘’>«»<]+")
_BOX = re.compile(r"^[\[{(|lI]\s*([xXkK×✓✔]?)\s*[\]})|lI1J]$")
_LEADING_JUNK = re.compile(r"^(?:[—–\-_~=|.,'`‘’“”]+(?=[\[{(])|[_~|`'‘’“”]+(?=[A-Za-z0-9(/]))")
_GLUED = re.compile(r"^([A-Za-z#][A-Za-z#.\s]*?:)\|?([A-Za-z0-9(/].*)$|^(.+?)\|(.+)$")


def available() -> bool:
    try:
        import pytesseract  # noqa: F401
    except Exception:
        return False
    return shutil.which("tesseract") is not None


def engine_name() -> str | None:
    if not available():
        return None
    try:
        import pytesseract

        return f"tesseract {pytesseract.get_tesseract_version()}"
    except Exception:  # pragma: no cover
        return "tesseract"


@dataclass
class OcrPage:
    tokens: list[Token]
    marks: list[Mark]
    angle: float  # degrees applied to straighten the page (PIL counter-clockwise)
    width: float
    height: float
    notes: list[str] = field(default_factory=list)
    rotation: int = 0  # quarter turns (clockwise degrees) applied before reading: 0/90/180/270


# --------------------------------------------------------------------------- deskew
def estimate_skew(img) -> float:
    """Angle (degrees) that straightens the text lines, found by maximising the
    sharpness of the horizontal ink profile.  Pure numpy/PIL."""
    import numpy as np
    from PIL import Image

    small = img.copy()
    small.thumbnail((900, 1200))
    ink = Image.fromarray(((np.asarray(small) < 140) * 255).astype("uint8"))

    def score(angle: float) -> float:
        r = np.asarray(ink.rotate(angle, resample=Image.NEAREST, fillcolor=0)) > 0
        prof = r.sum(axis=1).astype(float)
        return float(((prof[1:] - prof[:-1]) ** 2).sum())

    coarse = max((a / 10 for a in range(-40, 41, 2)), key=score)
    fine = max((coarse + a / 100 for a in range(-20, 21, 4)), key=score)
    return round(fine, 2) if abs(fine) >= 0.05 else 0.0


def unskew_bbox(bbox, angle: float, width: float, height: float) -> list[float]:
    """Map a box from the straightened page back onto the original page."""
    if not angle or not bbox:
        return bbox
    th = -math.radians(angle)
    c, s = math.cos(th), math.sin(th)
    cx, cy = width / 2, height / 2
    xs, ys = [], []
    for x, y in ((bbox[0], bbox[1]), (bbox[2], bbox[1]), (bbox[0], bbox[3]), (bbox[2], bbox[3])):
        xs.append(c * (x - cx) + s * (y - cy) + cx)
        ys.append(-s * (x - cx) + c * (y - cy) + cy)
    return [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)]


# --------------------------------------------------------------------------- ruled lines
def _covered_by_runs(ink, length: int):
    """Pixels that belong to a horizontal run of ``length`` or more ink pixels (numpy only)."""
    import numpy as np

    rows, cols = ink.shape
    if cols < length:
        return np.zeros_like(ink)
    cs = np.cumsum(np.pad(ink.astype(np.int32), ((0, 0), (1, 0))), axis=1)
    full = (cs[:, length:] - cs[:, :-length]) == length  # window [j, j+length) is all ink
    nfull = full.shape[1]
    cf = np.cumsum(np.pad(full.astype(np.int32), ((0, 0), (1, 0))), axis=1)
    k = np.arange(cols)
    hi = np.minimum(k, nfull - 1) + 1
    lo = np.maximum(0, k - length + 1)
    return (cf[:, hi] - cf[:, lo]) > 0


def remove_lines(arr, h_len_pt: float = 24, v_len_pt: float = 12):
    """Erase ruled lines and form-box borders so OCR sees only the text.

    A line is a long run of *thin* ink: blank about 1.5 pt on either side across
    it.  Text never qualifies (a baseline has letter bodies above it), so letters
    and small check boxes survive while rules and box sides are whitened."""
    import numpy as np

    ink = arr < 215
    off = max(2, int(round(1.5 * SCALE)))
    above = np.zeros_like(ink)
    below = np.zeros_like(ink)
    above[off:, :] = ink[:-off, :]
    below[:-off, :] = ink[off:, :]
    left = np.zeros_like(ink)
    right = np.zeros_like(ink)
    left[:, off:] = ink[:, :-off]
    right[:, :-off] = ink[:, off:]
    h = _covered_by_runs(ink & ~above & ~below, int(h_len_pt * SCALE))
    v = _covered_by_runs((ink & ~left & ~right).T, int(v_len_pt * SCALE)).T
    grown = h | v
    for d in range(1, off):  # widen to the anti-aliased edges of the stroke
        grown[d:, :] |= h[:-d, :]
        grown[:-d, :] |= h[d:, :]
        grown[:, d:] |= v[:, :-d]
        grown[:, :-d] |= v[:, d:]
    out = arr.copy()
    out[grown & (arr < 245)] = 255
    return out, int((h | v).sum())


# --------------------------------------------------------------------------- image analysis
def _components(dark, min_cells: int = 1):
    """Connected components of a boolean 2-D numpy array -> list of (r0, c0, r1, c1, n)."""
    import numpy as np

    rows, cols = dark.shape
    seen = np.zeros_like(dark, dtype=bool)
    out = []
    for r, c in zip(*np.nonzero(dark)):
        if seen[r, c]:
            continue
        q = deque([(r, c)])
        seen[r, c] = True
        r0 = r1 = r
        c0 = c1 = c
        n = 0
        while q:
            y, x = q.popleft()
            n += 1
            r0, r1, c0, c1 = min(r0, y), max(r1, y), min(c0, x), max(c1, x)
            for dy in (-1, 0, 1):
                ny = y + dy
                if ny < 0 or ny >= rows:
                    continue
                for dx in (-1, 0, 1):
                    nx = x + dx
                    if 0 <= nx < cols and dark[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        q.append((ny, nx))
        if n >= min_cells:
            out.append((int(r0), int(c0), int(r1), int(c1), n))
    return out


def _grid(arr, cell_px: float, thresh: int = 110):
    """Downsample a grayscale array to a boolean ink grid with cells of ``cell_px`` pixels."""
    import numpy as np

    h, w = arr.shape
    step = max(1, int(round(cell_px)))
    hh, ww = h // step * step, w // step * step
    ink = arr[:hh, :ww] < thresh
    return ink.reshape(hh // step, step, ww // step, step).any(axis=(1, 3)), step


def find_checkboxes(arr, tokens: list[Token], page: int) -> tuple[list[Token], list[Token]]:
    """Drawn check boxes on a scanned page.  Returns (checkbox tokens, OCR tokens to drop)."""
    import numpy as np

    grid, step = _grid(arr, SCALE * 0.5, thresh=200)  # 0.5 pt cells; printed boxes are often light gray
    pt = step / SCALE
    boxes, drop = [], []
    cands: list[tuple[Token, list[Token], bool]] = []
    for r0, c0, r1, c1, n in _components(grid, 20):
        # trim speckles that stick out of the outline (sparse edge rows/columns)
        for _ in range(3):
            if c1 - c0 > 4 and grid[r0:r1 + 1, c0].mean() < 0.3:
                c0 += 1
            if c1 - c0 > 4 and grid[r0:r1 + 1, c1].mean() < 0.3:
                c1 -= 1
            if r1 - r0 > 4 and grid[r0, c0:c1 + 1].mean() < 0.3:
                r0 += 1
            if r1 - r0 > 4 and grid[r1, c0:c1 + 1].mean() < 0.3:
                r1 -= 1
        w, h = (c1 - c0 + 1) * pt, (r1 - r0 + 1) * pt
        if not (6 <= w <= 16 and 6 <= h <= 16 and abs(w - h) <= 2.5):
            continue
        sub = grid[r0:r1 + 1, c0:c1 + 1]
        # a box has four (nearly) complete sides; letters do not.  Two cells of
        # tolerance absorb scanner speckles and small breaks in the outline.
        sides = (sub[:2, :].any(axis=0).mean(), sub[-2:, :].any(axis=0).mean(),
                 sub[:, :2].any(axis=1).mean(), sub[:, -2:].any(axis=1).mean())
        if min(sides) < 0.75:
            continue
        x0, top, x1, bottom = c0 * pt, r0 * pt, (c1 + 1) * pt, (r1 + 1) * pt
        # a letter inside an OCR'd word (the "O" of "INFORMATION") is not a box
        area = (x1 - x0) * (bottom - top)
        covering = [t for t in tokens if t.kind == "word"
                    and (min(x1, t.x1) - max(x0, t.x0)) > 0 and (min(bottom, t.bottom) - max(top, t.top)) > 0
                    and (min(x1, t.x1) - max(x0, t.x0)) * (min(bottom, t.bottom) - max(top, t.top)) > 0.3 * area]
        # ... and neither is a number or word OCR read there ("88", "IL"): two letters or digits
        # are text unless the reading itself looks like a printed box ("[X]", "[]")
        if any(len(re.sub(r"[^A-Za-z0-9]", "", t.text)) >= 2 and not re.search(r"[\[\]|]", t.text)
               for t in covering):
            continue
        # tokens OCR produced from the box itself ("O", "0", "[]", "X)" ...)
        inside = [t for t in covering if x0 - 1 <= t.cx <= x1 + 1 and top - 1 <= t.cy <= bottom + 1]
        X0, Y0 = int((x0 + 2.2) * SCALE), int((top + 2.2) * SCALE)
        X1, Y1 = int((x1 - 2.2) * SCALE), int((bottom - 2.2) * SCALE)
        interior = arr[Y0:Y1, X0:X1]
        ratio = float((interior < 140).mean()) if interior.size else 0.0
        checked = ratio > 0.05
        solid = float(sub.mean()) > 0.85  # a filled square: a tick ■, or just a bullet
        cands.append((Token("[X]" if checked else "[ ]", x0, top, x1, bottom, page, "ocr", kind="checkbox",
                            checked=checked, conf=0.85), inside, solid))
    # a filled square is a ticked box only on a page that also has empty boxes of its size;
    # on its own it is a bullet point
    for tok, inside, solid in cands:
        if solid and not any(not s2 and not t2.checked and abs(t2.width - tok.width) <= 2 and abs(t2.height - tok.height) <= 2
                             for t2, _, s2 in cands):
            continue
        drop.extend(inside)
        boxes.append(tok)
    return boxes, drop


def find_ink(arr, tokens: list[Token], page: int) -> list[Mark]:
    """Ink that OCR did not explain as text, e.g. handwritten signatures."""
    grid, step = _grid(arr, SCALE * 1.0)  # 1 pt cells
    pt = step / SCALE
    g = grid.copy()
    rows, cols = g.shape
    for t in tokens:
        if t.kind != "word" or not re.search(r"[A-Za-z0-9]{2,}", t.text):
            continue
        g[max(0, int((t.top - 1.5) / pt)):min(rows, int((t.bottom + 1.5) / pt) + 1),
          max(0, int((t.x0 - 1.5) / pt)):min(cols, int((t.x1 + 1.5) / pt) + 1)] = False
    # join pen strokes that are a few points apart
    import numpy as np

    joined = g.copy()
    for d in (1, 2, 3):
        joined[:, d:] |= g[:, :-d]
        joined[:, :-d] |= g[:, d:]
    joined[1:, :] |= g[:-1, :]
    joined[:-1, :] |= g[1:, :]
    marks = []
    for r0, c0, r1, c1, n in _components(joined, 12):
        w, h = (c1 - c0 + 1) * pt, (r1 - r0 + 1) * pt
        fill = n / max(1, (c1 - c0 + 1) * (r1 - r0 + 1))
        if w >= 30 and 6 <= h <= 45 and fill < 0.75:
            marks.append(Mark(page, c0 * pt, r0 * pt, (c1 + 1) * pt, (r1 + 1) * pt, kind="image"))
    return marks


# --------------------------------------------------------------------------- tokens
def _clean_text(text: str) -> tuple[str, float] | None:
    """-> (cleaned text, fraction of the box trimmed on the left) or None for noise."""
    text = text.strip()
    if not text:
        return None
    original = text
    text = _LEADING_JUNK.sub("", text)
    trimmed = (len(original) - len(text)) / max(1, len(original))
    text = text.rstrip("_|~")
    if not text or (_NOISE.fullmatch(text) and text not in ("[]",)):
        return None
    m = _BOX.match(text)
    if m:
        return ("[X]" if m.group(1).strip() else "[ ]"), trimmed
    if text.endswith(";") and text[:-1].isalpha():  # "Signature;" -> "Signature:"
        text = text[:-1] + ":"
    return text, trimmed


def _split_glued(text: str) -> list[tuple[str, float, float]]:
    """'Name:Karin' / 'Address:|77' / 'Lindqvist|Mother' -> pieces with their share of the box."""
    m = _GLUED.match(text)
    if not m or _BOX.match(text):
        return [(text, 0.0, 1.0)]
    a, b = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    a, b = a.strip("| "), b.strip("| ")
    if not a or not b:
        return [(text, 0.0, 1.0)]
    cut = len(a) / max(1, len(text))
    return [(a, 0.0, cut), (b, min(1.0, cut + 1 / max(1, len(text))), 1.0)]


def _tesseract_words(img, config: str, page_number: int) -> list[Token]:
    import os

    import pytesseract

    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config=config)
    out = []
    for i, raw in enumerate(data["text"]):
        cleaned = _clean_text(raw or "")
        if cleaned is None:
            continue
        text, trim = cleaned
        try:
            conf = max(0.0, float(data["conf"][i])) / 100.0
        except (TypeError, ValueError):
            conf = 0.0
        w = data["width"][i] / SCALE
        x0 = data["left"][i] / SCALE + w * trim
        w = w * (1 - trim)
        top = data["top"][i] / SCALE
        bottom = top + data["height"][i] / SCALE
        for piece, f0, f1 in _split_glued(text):
            out.append(Token(piece, x0 + w * f0, top, x0 + w * f1, bottom, page_number, "ocr", conf=conf))
    return out


def _merge_passes(passes: list[list[Token]]) -> list[Token]:
    """Keep, for every spot on the page, the reading with the highest confidence."""
    cands = sorted((t for p in passes for t in p), key=lambda t: -t.conf)
    kept: list[Token] = []
    for t in cands:
        area = max(1e-3, (t.x1 - t.x0) * (t.bottom - t.top))
        clash = False
        for k in kept:
            ix = min(t.x1, k.x1) - max(t.x0, k.x0)
            iy = min(t.bottom, k.bottom) - max(t.top, k.top)
            if ix > 0 and iy > 0:
                inter = ix * iy
                if inter / min(area, max(1e-3, (k.x1 - k.x0) * (k.bottom - k.top))) > 0.35:
                    clash = True
                    break
        if not clash:
            kept.append(t)
    # very low confidence leftovers are kept only when they look like words, and short
    # uncertain fragments standing alone on a line (border residue, specks) are dropped
    out = []
    for t in kept:
        core = len(re.sub(r"[^A-Za-z0-9]", "", t.text))
        if _BOX.match(t.text):
            out.append(t)
            continue
        if t.conf < 0.2 and core < 3:
            continue
        if t.conf < 0.6 and core <= 2 and not re.fullmatch(r"\d{2}", t.text):
            near = [k for k in kept if k is not t and min(t.bottom, k.bottom) - max(t.top, k.top) > 0
                    and (abs(k.x0 - t.x1) < 12 or abs(t.x0 - k.x1) < 12)
                    and (k.conf >= 0.6 or len(re.sub(r"[^A-Za-z0-9]", "", k.text)) >= 3)]
            if not near:
                continue
        if t.conf < 0.3:
            t.conf = 0.3
        out.append(t)
    return out


def detect_rotation(img) -> int:
    """Clockwise quarter turn that puts the text upright (0, 90, 180 or 270), from
    Tesseract's orientation detection when its data is installed."""
    import pytesseract

    small = img.copy()
    small.thumbnail((1400, 1400))
    try:
        osd = pytesseract.image_to_osd(small, config="--psm 0", output_type=pytesseract.Output.DICT)
    except Exception:  # no osd data, or too little text to decide
        return 0
    rot = int(osd.get("rotate", 0)) % 360
    return rot if rot in (90, 180, 270) and float(osd.get("orientation_conf", 0)) >= 2.0 else 0


def ocr_page(pdf_path: str | Path, page_number: int, width: float, height: float, *, deskew: bool = True,
             orient: bool = True) -> OcrPage:
    import numpy as np
    from PIL import Image

    from .render import render_page_gray

    img = render_page_gray(pdf_path, page_number, scale=SCALE)
    rotation = detect_rotation(img) if orient else 0
    if rotation:
        img = img.rotate(-rotation, expand=True, fillcolor=255)
        if rotation in (90, 270):
            width, height = height, width
    angle = estimate_skew(img) if deskew else 0.0
    if angle:
        img = img.rotate(angle, resample=Image.BICUBIC, fillcolor=255)
    page_arr = np.asarray(img)
    clean, line_px = remove_lines(page_arr)
    clean_img = Image.fromarray(clean)
    from concurrent.futures import ThreadPoolExecutor

    # each pass gets its own image object (PIL images are not thread-safe) and a
    # single-threaded engine, so the two passes run side by side without contention
    with ThreadPoolExecutor(max_workers=len(TESSERACT_PASSES)) as pool:
        passes = list(pool.map(lambda cfg: _tesseract_words(clean_img.copy(), cfg, page_number), TESSERACT_PASSES))
    tokens = _merge_passes(passes)
    boxes, drop = find_checkboxes(page_arr, tokens, page_number)
    drop_ids = {id(t) for t in drop}
    tokens = [t for t in tokens if id(t) not in drop_ids] + boxes
    marks = find_ink(clean, tokens, page_number)
    notes = [f"page straightened by {angle:+.2f} degrees before OCR"] if angle else []
    if rotation:
        notes.insert(0, f"page turned {rotation} degrees clockwise to read it upright")
    if line_px:
        notes.append("ruled lines and box borders removed before OCR")
    return OcrPage(tokens, marks, angle, width, height, notes, rotation)
