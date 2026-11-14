"""Stage 2 - Locate.

Groups tokens into lines, recognises section headings by meaning (template
aliases) and turns every heading into a rectangular page region.  Headings
printed side by side (e.g. primary and secondary insurance) each get their own
column region, so values from one column can never be bound to the other.
Tables inside a region are split into rows and columns using the document's
own header labels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .models import Line, PageData, Region, Token
from .template import Template, norm_tokens


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
            glued = (t.source == "ocr" and prev.source == "ocr" and t.x0 - prev.x1 < 0.25 * min(t.height, prev.height)
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


def find_headings(lines: list[Line], template: Template) -> list[Heading]:
    found = []
    for ln in lines:
        line_heads = []
        segs = segments(ln)
        for seg in segs:
            words = [t for t in seg if t.kind == "word"]
            if not words or len(words) != len(seg):
                break
            text = " ".join(t.text for t in words)
            if text.rstrip().endswith(":") or len(words) > 7:
                break
            key = template.match_section(text)
            if not key:
                break
            line_heads.append(Heading(key, text, words, ln.page))
        # a heading owns its whole line (or shares it only with other headings);
        # a lone matching word inside a table header row is not a heading
        if line_heads and len(line_heads) == len(segs):
            found.extend(line_heads)
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
                                      continued=True))
        elif not spans and last_region is not None and page_lines:
            counter += 1
            regions.append(Region(f"SEC_{counter:03d}", last_region.key, last_region.name, last_region.heading,
                                  pd.number, 0.0, 0.0, pd.width, pd.height, last_region.heading_bbox, continued=True))
        for h, x0, x1 in spans:
            bottom = pd.height
            for h2, a0, a1 in spans:
                if h2.top > h.top and not _same_row(h, h2) and a0 < x1 and a1 > x0:
                    bottom = min(bottom, h2.top - 1)
            counter += 1
            sec = template.by_key[h.key]
            r = Region(f"SEC_{counter:03d}", h.key, sec["name"], h.text, pd.number, x0, h.top - 1, x1, bottom,
                       bbox_of(h.tokens))
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
        words.append((norm_tokens(t.text), t.source == "ocr"))
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


def find_table(lines: list[Line], columns_spec: list[dict], region: Region, min_cols: int = 2) -> Table | None:
    alias_table = Template.alias_table(columns_spec)
    row_key = next((c for c in columns_spec if c.get("row_key")), columns_spec[0])
    for li, ln in enumerate(lines):
        toks = ln.tokens
        hits: list[tuple[dict, list[Token]]] = []
        i = 0
        while i < len(toks):
            m = match_aliases(toks, i, alias_table)
            if m and not toks[i + m[0] - 1].text.endswith(":") and all(m[1]["key"] != h[0]["key"] for h in hits):
                hits.append((m[1], toks[i:i + m[0]]))
                i += m[0]
            else:
                i += 1
        if len(hits) < min_cols or not any(h[0]["key"] == row_key["key"] for h in hits):
            continue
        # every header token must belong to a column label (a sentence is not a header)
        if sum(len(h[1]) for h in hits) < len([t for t in toks if t.kind == "word"]):
            continue
        hits.sort(key=lambda h: h[1][0].x0)
        cols = []
        for k, (spec, htoks) in enumerate(hits):
            x0 = region.x0 if k == 0 else htoks[0].x0 - 6
            x1 = region.x1 if k == len(hits) - 1 else hits[k + 1][1][0].x0 - 6
            cols.append((spec, x0, x1, htoks))
        rows: list[TableRow] = []
        for ln2 in lines[li + 1:]:
            if ln2.top < ln.bottom - 1:
                continue
            cells = {spec["key"]: Cell() for spec, *_ in cols}
            stray = False
            for t in ln2.tokens:
                # the token's left edge decides its column; OCR boxes may start a few
                # points early, so look a little into the token (never past its middle)
                ax = t.x0 + (min(6.0, (t.x1 - t.x0) / 2) if t.source == "ocr" else 0.5)
                for spec, x0, x1, _ in cols:
                    if x0 <= ax < x1 or (spec is cols[-1][0] and ax >= x0):
                        cells[spec["key"]].tokens.append(t)
                        break
                else:
                    stray = True
            if stray and not any(c.tokens for c in cells.values()):
                continue
            has_key = bool(cells[row_key["key"]].tokens)
            others = [k for k, c in cells.items() if c.tokens and k != row_key["key"]]
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
        return Table(ln, cols, rows)
    return None
