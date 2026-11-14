"""Stage 2 - Locate.

Groups tokens into lines, recognises section headings by meaning (template
aliases) and turns every heading into a rectangular page region.  Headings
printed side by side (e.g. primary and secondary insurance) each get their own
column region, so values from one column can never be bound to the other.
Tables inside a region are split into rows and columns using the document's
own header labels.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .models import Line, PageData, Region, Token
from .template import Template, canon_tokens, norm_tokens, strip_numbering


# --------------------------------------------------------------------------- lines
def build_lines(tokens: list[Token]) -> list[Line]:
    lines: list[list[Token]] = []
    for t in sorted((t for t in tokens if t.is_content), key=lambda t: (t.cy, t.x0)):
        best, best_d = None, None
        for ln in lines:
            ref_cy = sum(x.cy for x in ln) / len(ln)
            ref_h = min(min(x.height for x in ln), t.height)
            d = abs(ref_cy - t.cy)
            if d <= max(2.5, 0.5 * ref_h) and (best_d is None or d < best_d):
                best, best_d = ln, d
        if best is None:
            lines.append([t])
        else:
            best.append(t)
    out = [Line(sorted(ln, key=lambda t: t.x0)) for ln in lines]
    out.sort(key=lambda ln: (ln.page, ln.cy))
    return out


def segments(line: Line, gap: float = 22.0) -> list[list[Token]]:
    segs: list[list[Token]] = []
    for t in line.tokens:
        if segs and t.x0 - segs[-1][-1].x1 <= gap:
            segs[-1].append(t)
        else:
            segs.append([t])
    return segs


def join_tokens(tokens) -> str:
    """Text of a run of tokens.  OCR sometimes splits one word ('Appendectom' 'y'); pieces
    closer than a quarter of the text height are joined without a space."""
    out = ""
    prev = None
    for t in tokens:
        if not t.text:
            continue
        if prev is not None:
            same_line = abs(t.cy - prev.cy) < 0.5 * min(t.height, prev.height)
            gap = t.x0 - prev.x1
            glued = (t.source == "ocr" and prev.source == "ocr" and same_line and -1 <= gap < 0.25 * min(t.height, prev.height)
                     and t.text[:1].isalnum() and prev.text[-1:].isalnum())
            out += "" if glued else " "
        out += t.text
        prev = t
    return out.strip()


def bbox_of(tokens) -> list[float]:
    return [round(min(t.x0 for t in tokens), 1), round(min(t.top for t in tokens), 1),
            round(max(t.x1 for t in tokens), 1), round(max(t.bottom for t in tokens), 1)]


# --------------------------------------------------------------------------- headings & regions
@dataclass
class Heading:
    key: str
    text: str
    tokens: list[Token]
    page: int
    name: str = ""
    generic: bool = False  # recognised by its style, not by the template
    also: list = field(default_factory=list)  # further sections named by the same heading

    @property
    def x0(self):
        return min(t.x0 for t in self.tokens)

    @property
    def x1(self):
        return max(t.x1 for t in self.tokens)

    @property
    def top(self):
        return min(t.top for t in self.tokens)

    @property
    def bottom(self):
        return max(t.bottom for t in self.tokens)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "section"


def _median(values, default=0.0):
    v = sorted(values)
    return v[len(v) // 2] if v else default


def _page_style(lines: list[Line]) -> dict:
    words = [t for ln in lines for t in ln.tokens if t.kind == "word" and t.text.strip()]
    gaps = []
    for a, b in zip(lines, lines[1:]):
        if a.page == b.page and b.top > a.bottom:
            gaps.append(b.top - a.bottom)
    return {"size": _median([t.size for t in words if t.size], 0.0),
            "height": _median([t.height for t in words], 9.0),
            "gap": _median(gaps, 6.0)}


def _generic_heading(ln: Line, prev: Line | None, style: dict, nxt: Line | None = None) -> bool:
    """A heading recognised by how it is printed: short, alphabetic, on its own line, and
    set apart by weight, size, capitals or space above.  Used for sections the template
    does not know, so that they still close the section above them."""
    toks = ln.tokens
    if any(t.kind != "word" for t in toks) or len(segments(ln)) != 1:
        return False
    text = strip_numbering(" ".join(t.text for t in toks).strip())
    colon = text.endswith(":")
    text = text.rstrip(" :")
    words = re.findall(r"[A-Za-z][A-Za-z'&/-]*", text)
    if not words or len(toks) > 8 or text[-1:] in "?.,;" or not any(len(w) >= 3 for w in words):
        return False
    letters = sum(c.isalpha() for c in text)
    if letters < 0.75 * len(text.replace(" ", "")):
        return False
    caps = all(w.isupper() for w in words if len(w) > 1) and any(len(w) >= 4 for w in words)
    titled = all(w[0].isupper() for w in words if len(w) > 3)
    bold = all(t.bold for t in toks if t.source == "text") and any(t.source == "text" for t in toks)
    sizes = [t.size for t in toks if t.source == "text" and t.size]
    bigger = bool(style["size"] and sizes and min(sizes) >= style["size"] + 1.5) or \
        (all(t.source == "ocr" for t in toks) and _median([t.height for t in toks]) >= 1.2 * style["height"])
    gap_above = prev is None or prev.page != ln.page or (ln.top - prev.bottom) >= max(9.0, 1.6 * style["gap"])
    if prev is not None and prev.page == ln.page and ln.top - prev.bottom < 1.6 * _median([t.height for t in toks], 9.0) + 2:
        lx0, lx1 = min(t.x0 for t in toks), max(t.x1 for t in toks)
        above = [t for t in prev.tokens if t.x1 > lx0 - 6 and t.x0 < lx1 + 6]
        ptext = re.sub(r"[^A-Za-z]", "", " ".join(t.text for t in above))
        if above and ptext.isupper() and len(above) <= 5 and \
                _median([t.height for t in above], 9.0) < _median([t.height for t in toks], 9.0):
            return False  # set tight under a small capitals label ("RETURN STATUS"): it is that label's value
    if nxt is not None and nxt.page == ln.page and nxt.top - ln.bottom < 1.5 * _median([t.height for t in toks], 9.0) + 2 \
            and abs(nxt.tokens[0].x0 - toks[0].x0) <= 6 and all(t.kind == "word" and t.source != "form_field"
                                                                for t in nxt.tokens) and len(segments(nxt, gap=12)) == 1:
        # printed small over a larger line that starts where it starts: a label over its value
        mine = _median([t.size or t.height for t in toks], 0)
        theirs = _median([t.size or t.height for t in nxt.tokens], 0)
        if mine and theirs and theirs >= 1.25 * mine and len(nxt.tokens) <= 8 \
                and not " ".join(t.text for t in nxt.tokens).rstrip().endswith("."):
            return False
    if colon:  # "PATIENT INFORMATION:" alone on its line is a heading only when set apart by style
        return caps and (bold or bigger)
    if caps and (bold or bigger or gap_above):
        return True
    # bold *and* larger than the text is a heading even when set tight under a table; OCR has
    # no font weight, so there clearly larger text stands in for it
    much_bigger = all(t.source == "ocr" for t in toks) and _median([t.height for t in toks]) >= 1.3 * style["height"] \
        and (len(words) >= 2 or caps)  # one larger word on a scan is as often a value as a heading

    return titled and ((bold and bigger) or much_bigger or ((bold or bigger) and gap_above))


def _heading_print(words: list[Token], style: dict) -> bool:
    """Bold, capitals, larger than the body text, or read by OCR (which has no font)."""
    letters = "".join(ch for t in words for ch in t.text if ch.isalpha())
    return (all(t.bold for t in words) or (letters.isupper() and len(letters) > 2)
            or _median([t.height for t in words], 0) >= 1.15 * style.get("height", 9.0)
            or any(t.source == "ocr" for t in words))


def find_headings(lines: list[Line], template: Template, generic: bool = True) -> list[Heading]:
    found = []
    style = _page_style(lines)
    prev = None
    for li, ln in enumerate(lines):
        nxt = lines[li + 1] if li + 1 < len(lines) else None
        line_heads = []
        segs = segments(ln)
        for seg in segs:
            words = [t for t in seg if t.kind == "word"]
            if not words or len(words) != len(seg):
                break
            text = " ".join(t.text for t in words)
            # a heading may end in a colon ("1. PATIENT INFORMATION:") only when it is alone on its line
            if (text.rstrip().endswith(":") and len(segs) > 1) or len(words) > 8:
                break
            if re.search(r"[a-z]{2}\.$", text) and not re.search(r"\bcont\.$", text, re.I):
                break  # a sentence ("I consent to treatment.") is not a heading
            key = template.match_section(text, fuzzy=False)
            if not key:
                # a near match (an OCR typo) only counts when the words are printed like a heading
                key = template.match_section(text)
                if key and not _heading_print(words, style):
                    key = None
            also: list[str] = []
            if not key:
                # one heading for two sections: "Allergies and Family History", "Spouse / Emergency Contact"
                keys = template.match_sections(text)
                if len(keys) >= 2 and (_heading_print(words, style) or len(segs) == 1):
                    key, also = keys[0], keys[1:]
            if not key:
                break
            line_heads.append(Heading(key, text, words, ln.page, name=template.by_key[key]["name"], also=also))
        # a heading owns its whole line (or shares it only with other headings);
        # a lone matching word inside a table header row is not a heading
        if line_heads and len(line_heads) == len(segs):
            found.extend(line_heads)
        elif generic and _generic_heading(ln, prev, style, nxt):
            text = " ".join(t.text for t in ln.tokens)
            plain = strip_numbering(text).rstrip(" :")
            found.append(Heading("other:" + slug(plain), text, list(ln.tokens), ln.page,
                                 name=" ".join(w.capitalize() if w.isupper() else w for w in plain.split()),
                                 generic=True))
        prev = ln
    return found


def _same_row(a: "Heading", b: "Heading") -> bool:
    """Side-by-side headings: their text overlaps vertically (OCR boxes may include an underline)."""
    overlap = min(a.bottom, b.bottom) - max(a.top, b.top)
    smaller = min(a.bottom - a.top, b.bottom - b.top)
    return abs(a.top - b.top) < 4 or abs(a.bottom - b.bottom) < 4 or (smaller > 0 and overlap >= 0.6 * smaller)


def build_regions(pages: list[PageData], lines_by_page: dict[int, list[Line]], template: Template) -> list[Region]:
    regions: list[Region] = []
    counter = 0
    last_region: Region | None = None
    for pd in pages:
        heads = find_headings(lines_by_page.get(pd.number, []), template)
        heads.sort(key=lambda h: (h.top, h.x0))
        # rows of side-by-side headings
        rows: list[list[Heading]] = []
        for h in heads:
            if rows and any(_same_row(h, o) for o in rows[-1]):
                rows[-1].append(h)
            else:
                rows.append([h])
        spans = []  # (heading, x0, x1)
        for row in rows:
            row.sort(key=lambda h: h.x0)
            for i, h in enumerate(row):
                x0 = 0.0 if i == 0 else h.x0 - 6
                x1 = pd.width if i == len(row) - 1 else row[i + 1].x0 - 6
                spans.append((h, x0, x1))
        page_lines = lines_by_page.get(pd.number, [])
        # content above the first heading continues the previous page's last section
        if spans and last_region is not None:
            first_top = min(h.top for h, _, _ in spans)
            above = [ln for ln in page_lines if ln.bottom < first_top - 2]
            if above:
                counter += 1
                regions.append(Region(f"SEC_{counter:03d}", last_region.key, last_region.name, last_region.heading,
                                      pd.number, 0.0, 0.0, pd.width, first_top - 1, last_region.heading_bbox,
                                      continued=True, heading_page=last_region.hpage, also=list(last_region.also)))
        elif not spans and last_region is not None and page_lines:
            counter += 1
            regions.append(Region(f"SEC_{counter:03d}", last_region.key, last_region.name, last_region.heading,
                                  pd.number, 0.0, 0.0, pd.width, pd.height, last_region.heading_bbox, continued=True,
                                  heading_page=last_region.hpage, also=list(last_region.also)))
        for h, x0, x1 in spans:
            bottom = pd.height
            for h2, a0, a1 in spans:
                if h2.top > h.top and not _same_row(h, h2) and a0 < x1 and a1 > x0:
                    bottom = min(bottom, h2.top - 1)
            counter += 1
            r = Region(f"SEC_{counter:03d}", h.key, h.name, h.text, pd.number, x0, h.top - 1, x1, bottom,
                       bbox_of(h.tokens), also=list(h.also))
            regions.append(r)
        if spans:
            last = max(spans, key=lambda s: (s[0].top, s[0].x0))[0]
            last_region = next(r for r in reversed(regions) if r.page == pd.number and r.heading == last.text
                               and abs(r.top - (last.top - 1)) < 0.01)
    return regions


def region_lines(region: Region, lines: list[Line], heading_tokens: set[int]) -> list[Line]:
    """Lines restricted to the tokens that fall inside ``region`` (heading excluded)."""
    out = []
    for ln in lines:
        if ln.page != region.page:
            continue
        toks = [t for t in ln.tokens if region.contains(t) and id(t) not in heading_tokens]
        if toks:
            out.append(Line(toks))
    return out


# --------------------------------------------------------------------------- label matching
def _word_eq(a: str, b: str, fuzzy: bool) -> bool:
    if a == b:
        return True
    if not fuzzy or len(b) < 5:
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.85


def match_aliases(tokens: list[Token], start: int, table) -> tuple[int, dict] | None:
    """Longest alias (from ``Template.alias_table``) that matches tokens[start:].

    Words read by OCR are compared with a small tolerance ("Signatures" ~ "signature")."""
    words = []
    for t in tokens[start:start + 8]:
        if t.kind != "word":
            break
        words.append((canon_tokens(t.text), t.source == "ocr"))
    flat: list[str] = []
    fuzzy: list[bool] = []
    ends: list[int] = []  # flat index -> token count consumed
    for i, (w, f) in enumerate(words):
        for piece in w:
            flat.append(piece)
            fuzzy.append(f)
            ends.append(i + 1)
    for alias, spec in table:
        n = len(alias)
        if n <= len(flat) and all(_word_eq(flat[k], alias[k], fuzzy[k]) for k in range(n)):
            consumed = ends[n - 1]
            # the alias must end exactly at a token boundary
            if n == len(flat) or ends[n] != ends[n - 1]:
                return consumed, spec
    return None


# --------------------------------------------------------------------------- field / value tables
@dataclass
class KVRow:
    label: list[Token]
    value: list[Token]
    lines: list[Line]
    header: bool = False


_KV_HEAD_LEFT = re.compile(r"^(field|fields|item|items|question|questions|attribute|description|label|name|"
                           r"category|data|information|detail|details|parameter|property)$", re.I)
_KV_HEAD_RIGHT = re.compile(r"\b(value|values|answer|answers|response|responses|entry|details|information|"
                            r"result|data|sample|test value)\b", re.I)


def _kv_split_lines(lines: list[Line]):
    """(line, [label tokens, value tokens]) for lines made of a label, one wide gap and a value."""
    two = []
    for ln in lines:
        toks = ln.tokens
        if len(toks) < 2 or any(t.kind != "word" for t in toks):
            continue
        # the label/value split is the widest gap on the line; a second wide gap means more columns
        gaps = [(toks[i + 1].x0 - toks[i].x1, i + 1) for i in range(len(toks) - 1)]
        widest = max(gaps)
        if widest[0] < 12 or sum(1 for g, _ in gaps if g >= max(12.0, 0.4 * widest[0])) > 1:
            continue  # more than one wide gap: a row of three or more columns, not label | value
        segs = [toks[:widest[1]], toks[widest[1]:]]

        def label_like(t):  # OCR reads ';' as ':' - "Heart disease: Arthritis" is still one value
            return t.text.endswith(":") and not (t.source == "ocr" and t.text[:1].islower())

        if any(label_like(t) for t in segs[1]) or any(label_like(t) for t in segs[0][:-1]):
            continue
        two.append((ln, segs))
    return two


def _mode(xs):
    best, cnt = None, 0
    for x in xs:
        c = sum(1 for y in xs if abs(y - x) <= 3)
        if c > cnt:
            best, cnt = x, c
    return best, cnt


def kv_columns(lines: list[Line]) -> tuple[float, float] | None:
    """The label and value columns of field/value tables on a page (from all its lines)."""
    two = _kv_split_lines(lines)
    if len(two) < 3:
        return None
    xv, nv = _mode([segs[1][0].x0 for _, segs in two])
    xl, nl = _mode([segs[0][0].x0 for _, segs in two])
    if nv < 3 or nl < 3 or xv - xl < 40:
        return None
    return xl, xv


def kv_table(lines: list[Line], boxes: list | None = None, columns: tuple[float, float] | None = None,
             min_rows: int = 3) -> list[KVRow]:
    """A two-column table of labels and their values, one field per row:

        Field                     Sample test value
        First Name                Julian
        Permission to discuss     Yes
        medical condition
        with family

    Found from the columns themselves: at least three lines share a label column and a
    value column (a wide gap between them).  A row's label or value may wrap onto the
    following lines; a drawn row box, or a tight line gap, keeps them in one row.
    Returns the rows in order (the header row flagged), or [] when there is no such table."""
    if len(lines) < min_rows:
        return []
    if columns is None:
        columns = kv_columns(lines)
        if columns is None:
            return []
    xl, xv = columns
    two = _kv_split_lines(lines)
    h = _median([t.height for ln, _ in two for t in ln.tokens], 8.0)

    def box_of(ln):
        for b in boxes or []:
            if b[0] - 1 <= ln.x0 and ln.x1 <= b[2] + 1 and b[1] - 1 <= ln.cy <= b[3] + 1:
                return b
        return None

    rows: list[KVRow] = []
    started = False
    for ln in lines:
        lab = [t for t in ln.tokens if t.x0 < xv - 3]
        val = [t for t in ln.tokens if t.x0 >= xv - 3]
        gaps = [ln.tokens[i + 1].x0 - ln.tokens[i].x1 for i in range(len(ln.tokens) - 1)]
        wide = max(gaps) if gaps else 0
        if sum(1 for g in gaps if g >= max(12.0, 0.4 * wide)) > 1:  # three or more columns: a table row
            if started:
                break
            continue
        starts_label = bool(lab) and abs(lab[0].x0 - xl) <= 3
        starts_value = bool(val) and abs(val[0].x0 - xv) <= 3
        fits = (not lab or starts_label) and (not val or starts_value) and \
            not any(t.kind != "word" for t in ln.tokens) and (not lab or lab[-1].x1 < xv - 2)
        if not fits:
            if started:
                break
            continue
        prev = rows[-1] if rows else None
        same_row = False
        if prev is not None:
            last = prev.lines[-1]
            pb, lb = box_of(last), box_of(ln)
            if pb is not None and lb is not None:
                same_row = pb is lb
            else:
                same_row = ln.top - last.bottom < 0.6 * h
            # a continuation fills only the column(s) that wrap
            same_row = same_row and not (lab and val and prev.value and ln.top - last.bottom >= 0.6 * h)
        if same_row and prev is not None and (not lab or not prev.value or not val):
            prev.label += lab
            prev.value += val
            prev.lines.append(ln)
            continue
        if not lab and val and prev is None:
            continue
        rows.append(KVRow(lab, val, [ln]))
        started = True
    if len([r for r in rows if r.label and r.value]) < min_rows:
        return []
    first = rows[0]
    if first.label and first.value and (
            (all(t.bold for t in first.label + first.value) and not all(t.bold for r in rows[1:3] for t in r.label))
            or (_KV_HEAD_LEFT.match(join_tokens(first.label)) and _KV_HEAD_RIGHT.search(join_tokens(first.value)))):
        first.header = True
    return rows


def _caps_label(toks) -> bool:
    text = join_tokens([t for t in toks if t.kind == "word"])
    letters = re.sub(r"[^A-Za-z]", "", text)
    return len(letters) >= 3 and letters.isupper() and not re.search(r"\d", text)


def stacked_grid(rows: list[KVRow]) -> bool:
    """Rows that alternate between a row of labels and a row of values (labels printed
    above their values, two boxes side by side) are not label | value rows."""
    both = sum(1 for r in rows if r.label and r.value and _caps_label(r.label) and _caps_label(r.value))
    return both >= 2


def is_kv_table(rows: list[KVRow], known_label) -> bool:
    """A two-column table is a field/value table (not a list of records) when it says so
    in its header, or when most of its left cells are labels: known field names, or
    text ending in ':' or '?'."""
    if not rows or stacked_grid(rows):
        return False
    if rows[0].header and _KV_HEAD_LEFT.match(join_tokens(rows[0].label)):
        return True
    body = [r for r in rows if not r.header and r.label]
    labelish = sum(1 for r in body if known_label(r.label) or r.label[-1].text.endswith((":", "?")))
    return bool(body) and labelish >= 0.6 * len(body)


# --------------------------------------------------------------------------- labels under their line
def labels_below(lines: list[Line], k: int, table) -> list[tuple[dict, list[Token], list[Token]]]:
    """Labels printed *under* the line they name, as in a signature block:

        /s/ Ana Lopez                03/02/2026
        Signature of Patient         Date

    Every word group on line ``k`` must be a whole known label (no colon).  Each label
    takes the words of the line just above, between its left edge and the next label;
    that line must be close, hold no labels or sentences, and have every word taken.
    A signature block with nothing typed above (only ink, or blank) still yields its
    labels, with empty values, when one of them is a signature.  [(spec, label, value)]."""
    if k <= 0 or k >= len(lines):
        return []
    ln = lines[k]
    if any(t.kind != "word" or t.text.endswith(":") for t in ln.tokens):
        return []
    segs = segments(ln, gap=10)
    labels = []
    for seg in segs:
        m = match_aliases(seg, 0, table)
        if not m or m[0] != len(seg):
            return []
        labels.append((m[1], seg))
    empty = [(spec, seg, []) for spec, seg in labels] if any(sp.get("key") == "signature" for sp, _ in labels) else []
    prev = lines[k - 1]
    h = _median([t.height for t in prev.tokens], 9.0)
    if prev.page != ln.page or ln.top - prev.bottom > 1.6 * h + 4 or any(t.text.endswith(":") for t in prev.tokens):
        return empty
    out = []
    for si, (spec, seg) in enumerate(labels):
        x0 = seg[0].x0 - 12
        x1 = labels[si + 1][1][0].x0 - 6 if si + 1 < len(labels) else 1e9
        out.append((spec, seg, [t for t in prev.tokens if x0 <= t.x0 < x1]))
    # every word of the line above must belong to a label, and a sentence is text, not a value
    if sum(len(v) for _, _, v in out) != len([t for t in prev.tokens if t.kind in ("word", "checkbox")]) or any(
            len(v) > 4 and v[-1].text.endswith(".") for _, _, v in out):
        return empty
    return out


# --------------------------------------------------------------------------- multi-line values
def continuation_tokens(lines: list[Line], k: int, value_tokens: list[Token], right_limit: float) -> list[Token]:
    """Words on the next line that continue a value ("42 Elm Street" / "Apartment 3B").

    Only a line set tight under the value (closer than a normal line gap), starting where
    the value starts and carrying no label of its own qualifies."""
    vt = [t for t in value_tokens if t.kind == "word" and t.text]
    if not vt or k + 1 >= len(lines):
        return []
    ln, nxt = lines[k], lines[k + 1]
    if nxt.page != ln.page:
        return []
    height = max(t.height for t in vt)
    gap = nxt.top - max(t.bottom for t in vt)
    # OCR boxes hug the glyphs (shorter than font boxes), so the same leading reads as a wider gap
    limit = (0.6 if any(t.source == "ocr" for t in vt) else 0.45) * height
    if gap < -1 or gap > limit:
        return []
    x0 = min(t.x0 for t in vt)
    toks = [t for t in nxt.tokens if t.x0 >= x0 - 6 and t.x1 <= right_limit + 3]
    if not toks or abs(min(t.x0 for t in toks) - x0) > 6:
        return []
    # nothing else on that line may sit left of the value, and the words carry no label
    if any(t.x1 < x0 - 6 for t in nxt.tokens) or any(t.kind != "word" or t.text.endswith(":") for t in toks):
        return []
    return toks


# --------------------------------------------------------------------------- check boxes
def checkbox_options(tokens: list[Token]):
    """Pair every check box on a line with its printed option label.

    The side labels sit on is decided by spacing: a label is printed right next to its
    box, the next option further away ("[X] Yes   [ ] No" vs "Yes [X]   No [ ]").  This
    still holds when OCR misses a box or a word.  Returns (question tokens,
    [(box, label tokens)], trailing tokens after the last option)."""
    boxes = [i for i, t in enumerate(tokens) if t.kind == "checkbox"]
    if not boxes:
        return list(tokens), [], []
    n = len(tokens)

    def is_option_word(t):
        return t.kind == "word" and not t.text.endswith(("?", ":"))

    right = [tokens[i + 1].x0 - tokens[i].x1 for i in boxes if i + 1 < n and is_option_word(tokens[i + 1])]
    left = [tokens[i].x0 - tokens[i - 1].x1 for i in boxes if i > 0 and is_option_word(tokens[i - 1])]
    if right and left:
        on_left = min(left) + 0.5 < min(right) or (abs(min(left) - min(right)) <= 0.5 and tokens[-1].kind == "checkbox")
    else:
        on_left = bool(left) and not right
    opts: list[tuple[Token, list[Token]]] = []
    if not on_left:  # labels on the right
        trailing: list[Token] = []
        for k, bi in enumerate(boxes):
            end = boxes[k + 1] if k + 1 < len(boxes) else n
            lab: list[Token] = []
            j = bi + 1
            while j < end and tokens[j].kind == "word" and (not lab or tokens[j].x0 - lab[-1].x1 < 20):
                if tokens[j].text.endswith(":") and lab:  # "Other:" starts something new
                    break
                if not lab and tokens[j].x0 - tokens[bi].x1 > 20:
                    break
                lab.append(tokens[j])
                j += 1
            opts.append((tokens[bi], lab))
            if k == len(boxes) - 1:
                trailing = [t for t in tokens[j:]]
        return [t for t in tokens[:boxes[0]] if t.kind == "word"], opts, trailing
    # labels on the left: each box takes the closest words before it
    question_end = None
    for k, bi in enumerate(boxes):
        start = boxes[k - 1] + 1 if k else 0
        lab = []
        j = bi - 1
        while j >= start and tokens[j].kind == "word" and len(lab) < 3:
            if lab and lab[0].x0 - tokens[j].x1 > 8:
                break
            if tokens[j].text.endswith(("?", ":")):  # the question ends here
                break
            if not lab and tokens[bi].x0 - tokens[j].x1 > 20:
                break
            lab.insert(0, tokens[j])
            j -= 1
        if k == 0:
            question_end = j + 1
        opts.append((tokens[bi], lab))
    trailing = [t for t in tokens[boxes[-1] + 1:]]
    return [t for t in tokens[:question_end or 0] if t.kind == "word"], opts, trailing


# --------------------------------------------------------------------------- tables
@dataclass
class Cell:
    tokens: list[Token] = field(default_factory=list)
    continued: list[Token] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(x for x in (join_tokens(self.tokens), join_tokens(self.continued)) if x).strip()

    @property
    def all_tokens(self) -> list[Token]:
        return self.tokens + self.continued


@dataclass
class TableRow:
    index: int
    cells: dict[str, Cell]
    lines: list[Line]
    wrapped_columns: list[str] = field(default_factory=list)

    @property
    def wrapped(self) -> bool:
        return bool(self.wrapped_columns)


@dataclass
class Table:
    header: Line
    columns: list[tuple[dict, float, float, list[Token]]]  # (spec, x0, x1, header tokens)
    rows: list[TableRow]


def _overlap(a: Token, x0: float, x1: float) -> float:
    return min(a.x1, x1) - max(a.x0, x0)


def header_second_line(lines: list[Line], li: int) -> Line | None:
    """The second line of a column header printed over two lines ("Prescribing" over
    "Physician", "Unit" over "Price"): set tight under the first, words only, no digits,
    every word under a word of the first line."""
    if li + 1 >= len(lines):
        return None
    ln, nx = lines[li], lines[li + 1]
    if nx.page != ln.page or any(t.kind != "word" for t in nx.tokens):
        return None
    h = _median([t.height for t in ln.tokens], 8.0)
    if nx.top - ln.bottom > 0.6 * h or len(nx.tokens) > len(ln.tokens):
        return None
    if any(t.source == "text" for t in ln.tokens + nx.tokens):
        # printed text says how a header is set: bold like the line above, and tighter than a line gap
        if not (all(t.bold for t in ln.tokens) and all(t.bold for t in nx.tokens)) or nx.top - ln.bottom > 0.4 * h:
            return None
    if any(re.search(r"\d", t.text) or t.text.endswith(":") for t in nx.tokens):
        return None
    for t in nx.tokens:
        if not any(_overlap(t, u.x0, u.x1) > -2 or abs(t.x0 - u.x0) < 4 or abs(t.x1 - u.x1) < 4 for u in ln.tokens):
            return None
    return nx


def header_segments(ln: Line, nx: Line | None, gap: float | None = None) -> list[list[Token]]:
    """Column labels of a header: groups of first-line words, each joined by the
    second-line words printed under it."""
    h = _median([t.height for t in ln.tokens], 8.0)
    segs = segments(ln, gap=gap if gap is not None else max(4.0, 0.6 * h))
    if nx is None:
        return segs
    extra: list[list[Token]] = [[] for _ in segs]
    for t in sorted(nx.tokens, key=lambda t: t.x0):
        k = max(range(len(segs)), key=lambda k: (_overlap(t, segs[k][0].x0, segs[k][-1].x1),
                                                 -abs(t.x0 - segs[k][0].x0)))
        extra[k].append(t)
    return [seg + ex for seg, ex in zip(segs, extra)]


def merge_header(ln: Line, nx: Line) -> list[Token]:
    """Header words of two lines in reading order per column."""
    return [t for seg in header_segments(ln, nx) for t in seg]


_JOINERS = re.compile(r"\s*(?:/|&|\+|\band\b)\s*", re.I)


def _combined_header(toks: list[Token], i: int, alias_table) -> tuple[int, dict] | None:
    """One column printed for two fields: "Dose/Frequency", "Dose & Frequency"."""
    by_alias = {tuple(a): spec for a, spec in alias_table}
    for n in range(min(4, len(toks) - i), 0, -1):
        run = toks[i:i + n]
        if any(t.kind != "word" for t in run) or any(run[k + 1].x0 - run[k].x1 > 6 for k in range(n - 1)):
            continue
        text = " ".join(t.text for t in run)
        parts = [p for p in _JOINERS.split(text) if p.strip()]
        if len(parts) != 2 or not _JOINERS.search(text):
            continue
        specs = [by_alias.get(tuple(canon_tokens(p))) for p in parts]
        if all(specs) and specs[0]["key"] != specs[1]["key"]:
            a, b = specs
            return n, {"key": f"{a['key']}+{b['key']}", "label": text, "type": "combined", "combined": [a, b]}
    return None


def _header_hits(toks: list[Token], alias_table) -> list[tuple[dict, list[Token]]]:
    hits: list[tuple[dict, list[Token]]] = []
    taken: set[str] = set()
    i = 0
    while i < len(toks):
        c = _combined_header(toks, i, alias_table)
        if c and not ({s["key"] for s in c[1]["combined"]} & taken):
            hits.append((c[1], toks[i:i + c[0]]))
            taken |= {s["key"] for s in c[1]["combined"]}
            i += c[0]
            continue
        m = match_aliases(toks, i, alias_table)
        if m and not toks[i + m[0] - 1].text.endswith(":") and m[1]["key"] not in taken:
            hits.append((m[1], toks[i:i + m[0]]))
            taken.add(m[1]["key"])
            i += m[0]
        else:
            i += 1
    return hits


def _unknown_columns(toks: list[Token], hits) -> list[tuple[dict, list[Token]]] | None:
    """Header words that name no known column become columns of their own ("Reason"),
    provided they look like column labels.  None when they do not (a sentence)."""
    used = {id(t) for _, ht in hits for t in ht}
    rest = [t for t in toks if id(t) not in used and t.kind == "word"]
    if not rest:
        return []
    if any(re.search(r"\d", t.text) or t.text.endswith((":", ".", ",")) for t in rest):
        return None
    groups: list[list[Token]] = []
    for t in rest:  # neighbours in reading order that were also neighbours on the line
        k = toks.index(t)
        if groups and toks.index(groups[-1][-1]) == k - 1:
            groups[-1].append(t)
        else:
            groups.append([t])
    if len(groups) > len(hits) or any(len(g) > 3 for g in groups):
        return None
    return [({"key": slug(join_tokens(g)).replace("-", "_"), "label": join_tokens(g), "type": "text",
              "unknown": True}, g) for g in groups]


def _well_separated(cols: list[tuple[dict, list[Token]]]) -> bool:
    """Columns of a header stand apart; the words of a sentence do not."""
    spans = sorted((min(t.x0 for t in g), max(t.x1 for t in g)) for _, g in cols)
    h = 8.0
    return all(spans[k + 1][0] - spans[k][1] >= max(7.0, 0.7 * h) for k in range(len(spans) - 1))


def find_table(lines: list[Line], columns_spec: list[dict], region: Region, min_cols: int = 2) -> Table | None:
    """The section's table: a header naming at least two known columns (one of them the
    row key), possibly printed over two lines, combining two fields in one column
    ("Dose/Frequency"), or carrying columns the template does not know ("Reason")."""
    alias_table = Template.alias_table(columns_spec)
    row_key = next((c for c in columns_spec if c.get("row_key")), columns_spec[0])
    for li, ln in enumerate(lines):
        options = [(ln.tokens, li)]
        nx = header_second_line(lines, li)
        if nx is not None:
            options.insert(0, (merge_header(ln, nx), li + 1))
        best = None
        for toks, last in options:
            hits = _header_hits(toks, alias_table)
            keys = {k["key"] for h in hits for k in (h[0].get("combined") or [h[0]])}
            if len(hits) < min_cols or row_key["key"] not in keys:
                continue
            unknown = _unknown_columns(toks, hits)
            if unknown is None or (unknown and not _well_separated(hits + unknown)):
                continue
            if best is None or len(hits) > len(best[0]) or (len(hits) == len(best[0]) and len(unknown) < len(best[1])):
                best = (hits, unknown, toks, last)
        if best is None:
            continue
        hits, unknown, toks, last = best
        if last != li and last - 1 == li and len(_header_hits(ln.tokens, alias_table)) == len(hits) and not (
                all(t.bold for t in ln.tokens) and all(t.bold for t in lines[last].tokens)):
            last = li  # the second line added nothing and does not look like header print
        cols_in = sorted(hits + unknown, key=lambda h: min(t.x0 for t in h[1]))
        cols = []
        for k, (spec, htoks) in enumerate(cols_in):
            x0 = region.x0 if k == 0 else min(t.x0 for t in htoks) - 6
            x1 = region.x1 if k == len(cols_in) - 1 else min(t.x0 for t in cols_in[k + 1][1]) - 6
            cols.append((spec, x0, x1, htoks))
        header = Line(sorted([t for _, ht in cols_in for t in ht], key=lambda t: (t.top, t.x0))) if last != li else ln
        rows = table_rows(lines[last + 1:], cols, row_key["key"], lines[last].bottom)
        return Table(header, cols, rows)
    return None


def _column_of(t: Token, cols):
    """The column a cell word belongs to.  Its left edge decides (OCR boxes may start a
    few points early, so look a little into the word); a word that misses its column's
    header entirely but sits under exactly one other header is right-aligned or
    centred under that one ("$252.00" under "Amount")."""
    ax = t.x0 + (min(6.0, (t.x1 - t.x0) / 2) if t.source == "ocr" else 0.5)
    le = None
    for c in cols:
        spec, x0, x1, _ = c
        if x0 <= ax < x1 or (spec is cols[-1][0] and ax >= x0):
            le = c
            break
    def hspan(c):
        ht = c[3]
        return (min(u.x0 for u in ht), max(u.x1 for u in ht)) if ht else (c[1], c[2])
    if le is not None and _overlap(t, *hspan(le)) > 0:
        return le
    under = [c for c in cols if _overlap(t, *hspan(c)) > 0]
    if len(under) == 1:
        return under[0]
    return le


def table_rows(lines: list[Line], cols, key: str, after: float = -1e9) -> list[TableRow]:
    """Rows of a table whose columns are known (from its header, or from the same table
    on the previous page)."""
    rows: list[TableRow] = []
    for ln2 in lines:
        if ln2.top < after - 1:
            continue
        cells = {spec["key"]: Cell() for spec, *_ in cols}
        stray = False
        for t in ln2.tokens:
            c = _column_of(t, cols)
            if c is None:
                stray = True
            else:
                cells[c[0]["key"]].tokens.append(t)
        if stray and not any(c.tokens for c in cells.values()):
            continue
        has_key = bool(cells[key].tokens)
        others = [k for k, c in cells.items() if c.tokens and k != key]
        # a line made of a single "Label:" pair is not a table row
        if any(t.text.endswith(":") for c in cells.values() for t in c.tokens[:1]) and not has_key:
            break
        if has_key:
            rows.append(TableRow(len(rows) + 1, cells, [ln2]))
        elif others and rows:
            prev = rows[-1]
            for k in others:
                prev.cells[k].continued.extend(cells[k].tokens)
                if k not in prev.wrapped_columns:
                    prev.wrapped_columns.append(k)
            prev.lines.append(ln2)
    return rows


def continue_table(lines: list[Line], table: Table) -> Table | None:
    """The same table carried on from the previous page, without a repeated header:
    its first line must fill at least two of the known columns and carry no labels."""
    if not lines:
        return None
    first = lines[0]
    if any(t.text.endswith(":") for t in first.tokens):
        return None
    filled = set()
    for t in first.tokens:
        c = _column_of(t, table.columns)
        if c is not None:
            filled.add(c[0]["key"])
    if len(filled) < 2:
        return None
    key = next((spec["key"] for spec, *_ in table.columns if spec.get("row_key")), table.columns[0][0]["key"])
    rows = table_rows(lines, table.columns, key)
    return Table(table.header, table.columns, rows) if rows else None


# --------------------------------------------------------------------------- page furniture
_FURNITURE = re.compile(r"\bpage\s*\d+(\s*(of|/)\s*\d+)?\b|^\s*\d+\s*(of|/)\s*\d+\s*$|\bform\s+[a-z0-9_-]*\d|"
                        r"\brev(ision)?\.?\s*\d|©|\bconfidential\b|https?://|www\.", re.I)


def mark_furniture(pages: list[PageData]) -> int:
    """Running headers and footers (repeated on every page, or 'Page 2 of 3' / form
    numbers in the margins) are page furniture: kept, but never read as data."""
    bands: dict[tuple[str, str], set[int]] = {}
    lines_by_page = {}
    for pd in pages:
        lines = build_lines([t for t in pd.tokens if t.kind == "word"])
        lines_by_page[pd.number] = lines
        for ln in lines:
            band = "top" if ln.bottom < 0.09 * pd.height else "bottom" if ln.top > 0.91 * pd.height else None
            if band:
                key = re.sub(r"\d+", "#", " ".join(t.text for t in ln.tokens).lower())
                bands.setdefault((band, key), set()).add(pd.number)
    marked = 0
    for pd in pages:
        for ln in lines_by_page[pd.number]:
            band = "top" if ln.bottom < 0.09 * pd.height else "bottom" if ln.top > 0.91 * pd.height else None
            if not band:
                continue
            text = " ".join(t.text for t in ln.tokens)
            key = re.sub(r"\d+", "#", text.lower())
            if len(bands.get((band, key), ())) >= 2 or _FURNITURE.search(text):
                for t in ln.tokens:
                    t.kind = "furniture"
                    marked += 1
    return marked
