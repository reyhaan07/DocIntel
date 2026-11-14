"""Template-free structure: works on any document.

Every region of every page is read for the structures a person sees without
knowing the form: labelled fields (``Label: value``), tables (a header row with
aligned rows below), questions answered with check boxes, signatures, and plain
text.  Each piece of text on the page ends up in exactly one of those roles, so
nothing on the page is silently dropped.

When a template applies, these structures are compared with what the template
bound: anything the template did not capture is kept as a generic entity and
reported.  When no template applies (an unknown kind of document), the generic
entities *are* the result.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .layout import (Cell, Table, TableRow, bbox_of, continuation_tokens, continue_table, find_table,
                     header_second_line, header_segments, join_tokens, segments, slug)
from .models import Attribute, Entity, Line, Region, Relationship, Evidence, Token
from .normalize import clean, format_phone, is_ambiguous_date, label_text, parse_date
from .template import norm

GENERIC_TYPES = {
    "Section": ("SCT", "Sections"),
    "Field": ("FLD", "Fields"),
    "TableRow": ("ROW", "Table rows"),
    "Question": ("QST", "Questions"),
    "Signature": ("SIG", "Signatures"),
}
GENERIC_TYPE_NAMES = {"Section": "Section", "Field": "Field", "TableRow": "Table row", "Question": "Question",
                      "Signature": "Signature"}
SIGNATURE_WORDS = re.compile(r"\b(signature|signed|sign here)\b", re.I)


# --------------------------------------------------------------------------- value typing
PHONE_LABEL = re.compile(r"\b(phone|tel|telephone|mobile|cell|fax|contact number)\b", re.I)
DATE_LABEL = re.compile(r"\b(date|dob|d\.o\.b|birth|born|due|expir\w*|issued|collected|received|signed|given|"
                        r"admitted|discharged|visit|service|start|end|from|to|until)\b", re.I)
ID_LABEL = re.compile(r"\b(id|no|number|nr|#|mrn|nhs|ssn|account|policy|member|group|invoice|po|order|lot|ref)\b", re.I)


def detect_value(raw: str, date_order: str = "mdy", label: str = ""):
    """-> (normalised value, value type).  Unknown documents still get typed values.

    The label decides between look-alikes: ten digits are a phone number only under a
    phone label, never under an ID or number label (an NHS number is not a phone)."""
    v = clean(raw)
    if not v:
        return None, "empty"
    iso = parse_date(v, date_order)
    if iso and (not label or DATE_LABEL.search(label) or not ID_LABEL.search(label)):
        return iso, "date"
    if label and ID_LABEL.search(label) and not PHONE_LABEL.search(label):
        return v, "identifier"
    if re.fullmatch(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", v.replace(" ", "")):
        return v.replace(" ", "").lower(), "email"
    digits = re.sub(r"\D", "", v)
    if re.fullmatch(r"[\d\s().+-]{10,18}", v) and len(digits) in (10, 11):
        if PHONE_LABEL.search(label or ""):
            return format_phone(v), "phone"
        return v, "number"
    if re.fullmatch(r"[-+]?[$€£]\s?\d[\d,]*(\.\d+)?|[-+]?\d[\d,]*(\.\d{2})\s?(USD|EUR|GBP)?", v):
        return v, "amount"
    if re.fullmatch(r"[-+]?\d+([.,]\d+)?\s?%?", v):
        return v, "number"
    if v.lower() in ("yes", "no", "y", "n", "true", "false"):
        return v.lower()[0] in "yt" and "yes" or "no", "yes_no"
    return v, "text"


def _generic_flags(binder, attr: Attribute, raw: str, vtype: str, continued: bool) -> None:
    if vtype == "date" and binder.date_order not in ("mdy", "dmy") and is_ambiguous_date(raw):
        attr.notes.append(f"'{raw}' could be read day-first or month-first and nothing else on the document "
                          f"settles it; read as {attr.value}")
        attr.status = "needs_review"
    if continued:
        attr.notes.append("value continues on the next line; the two lines were joined - confirm")
        attr.status = "needs_review"


# --------------------------------------------------------------------------- structures
@dataclass
class GField:
    region: Region
    label_tokens: list[Token]
    value_tokens: list[Token]
    label: str
    raw: str
    signature_mark: object = None
    continued: bool = False
    named_by_field: bool = False  # label taken from the form field's tooltip/name, not printed

    @property
    def is_signature(self) -> bool:
        return bool(SIGNATURE_WORDS.search(self.label)) or (self.signature_mark is not None and not self.raw)


@dataclass
class GQuestion:
    region: Region
    question_tokens: list[Token]
    options: list[tuple[Token, list[Token]]]

    @property
    def text(self) -> str:
        return label_text(join_tokens(self.question_tokens))


@dataclass
class GTable:
    region: Region
    header: list[tuple[str, list[Token]]]
    rows: list[TableRow]
    table: Table


@dataclass
class Structure:
    fields: list[GField] = field(default_factory=list)
    tables: list[GTable] = field(default_factory=list)
    questions: list[GQuestion] = field(default_factory=list)
    text: list[tuple[Region, list[Token]]] = field(default_factory=list)
    roles: dict[int, str] = field(default_factory=dict)  # id(token) -> role
    pseudo_regions: list[Region] = field(default_factory=list)
    tokens_total: int = 0


def _assign(st: Structure, tokens, role: str):
    for t in tokens:
        st.roles.setdefault(id(t), role)


def _generic_table(lines: list[Line], region: Region, start: int, binder_boxes: dict | None = None):
    """A header row (2+ separated short labels, no colons) with aligned rows below it."""
    ln = lines[start]
    if any(t.kind != "word" or t.text.endswith(":") for t in ln.tokens):
        return None
    second = header_second_line(lines, start)  # "Unit" over "Price"
    segs = header_segments(ln, second, gap=12)
    if len(segs) < 2 or any(len(s) > 4 + (1 if second else 0) for s in segs):
        return None
    texts = [join_tokens(s) for s in segs]
    if any(not re.search(r"[A-Za-z]{2,}", tx) for tx in texts):
        return None
    first_data = start + (2 if second else 1)
    if first_data >= len(lines):
        return None
    nxt = lines[first_data]
    starts = [min(t.x0 for t in s) for s in segs]
    hit_cols = {i for t in nxt.tokens for i, x in enumerate(starts) if x - 8 <= t.x0 < (starts[i + 1] - 6 if i + 1 < len(starts) else 1e9)}
    if len(hit_cols) < 2 or any(t.text.endswith(":") for t in nxt.tokens[:1]):
        return None
    specs = [{"key": f"c{i}", "label": tx, "aliases": [tx], "row_key": i == 0} for i, tx in enumerate(texts)]
    table = find_table(lines[start:], specs, region)
    if not table or not table.rows:
        return None
    # rows end at the first large vertical gap (the table is over), or where the print
    # style changes back to the header's (a new row of labels starts something else)
    def size(toks):
        sz = [t.size for t in toks if t.size]
        return sorted(sz)[len(sz) // 2] if sz else 0.0

    header_size = size(ln.tokens)
    first_size = size([t for l in table.rows[0].lines for t in l.tokens])
    rows, prev_bottom = [], table.header.bottom
    gaps = []
    for row in table.rows:
        top = min(l.top for l in row.lines)
        gap = top - prev_bottom
        typical = sorted(gaps)[len(gaps) // 2] if gaps else 8.0
        if gap > max(14.0, 2.2 * typical):
            break
        rs = size([t for l in row.lines for t in l.tokens])
        if rows and header_size and first_size and abs(header_size - first_size) > 0.8 and abs(rs - header_size) < 0.3:
            break
        gaps.append(gap)
        rows.append(row)
        prev_bottom = max(l.bottom for l in row.lines)
    if not rows:
        return None
    # labels printed above value boxes ("Full name" over a box, then "Mobile" over the
    # next box) are fields, not a table: the row after the boxed row is not boxed
    boxes = binder_boxes.get(region.page, []) if binder_boxes else []
    if boxes:
        def boxed(toks):
            return toks and all(any(b[0] - 1 <= t.cx <= b[2] + 1 and b[1] - 1 <= t.cy <= b[3] + 1 for b in boxes)
                                for t in toks)
        first = [t for c in rows[0].cells.values() for t in c.all_tokens]
        if boxed(first):
            # a boxed table stacks rows of boxes; a row of labelled boxes stands alone
            holders = [b for b in boxes if any(b[0] - 1 <= t.cx <= b[2] + 1 and b[1] - 1 <= t.cy <= b[3] + 1
                                               for t in first)]
            stacked = any(o is not b and abs(o[0] - b[0]) < 3 and -1 <= o[1] - b[3] <= 8
                          for b in holders for o in boxes)
            if not stacked:
                return None
    table.rows = rows
    return GTable(region, list(zip(texts, segs)), rows, table)


def _box_fields(st: "Structure", binder, region: Region, lines: list[Line]) -> None:
    """Values printed inside drawn boxes, labelled by the words just left of the box
    or just above it (labels above boxes often carry no colon)."""
    pd = binder.pages[region.page - 1]
    words = [t for ln in lines for t in ln.tokens if t.kind == "word"]
    for (bx0, btop, bx1, bbot) in sorted(pd.boxes, key=lambda b: (b[1], b[0])):
        cx, cy = (bx0 + bx1) / 2, (btop + bbot) / 2
        if not (region.x0 <= cx <= region.x1 and region.top <= cy <= region.bottom):
            continue
        inside = [t for t in words if bx0 - 1 <= t.cx <= bx1 + 1 and btop - 1 <= t.cy <= bbot + 1]
        if any(id(t) in st.roles for t in inside):
            continue  # already read (a table cell)
        free = [t for t in words if id(t) not in st.roles and t not in inside]
        # label on the left, on the same line
        left = sorted([t for t in free if abs(t.cy - cy) < 5 and t.x1 <= bx0 + 1], key=lambda t: t.x0)
        label: list[Token] = []
        if left and bx0 - left[-1].x1 <= 15:
            label = [left[-1]]
            for t in reversed(left[:-1]):
                if label[0].x0 - t.x1 < 6 and len(label) < 6 and not t.text.endswith(":"):
                    label.insert(0, t)
                else:
                    break
        else:  # label above the box
            above = sorted([t for t in free if 0 <= btop - t.bottom <= 12 and bx0 - 3 <= t.x0 <= bx1 - 4],
                           key=lambda t: t.x0)
            if above and abs(above[0].x0 - bx0) <= 20:
                label = [above[0]]
                for t in above[1:]:
                    if t.x0 - label[-1].x1 < 6 and abs(t.cy - label[0].cy) < 3:
                        label.append(t)
                    else:
                        break
        if not label:
            continue
        value = sorted(inside, key=lambda t: (round(t.cy), t.x0))
        f = GField(region, label, value, label_text(join_tokens(label)),
                   clean(join_tokens([t for t in value if t.kind == "word"])))
        st.fields.append(f)
        _assign(st, label, "label")
        _assign(st, value, "value")


def _empty_table_header(lines: list[Line], i: int, binder) -> bool:
    """A column-header row with no rows under it (an empty table on a blank form).

    Accepted only when it is printed bold or every column is a known template column,
    so a stray data row can never be mistaken for a header and dropped."""
    ln = lines[i]
    segs = segments(ln, gap=12)
    if len(segs) < 2 or any(t.kind != "word" or t.text.endswith(":") for t in ln.tokens) or any(len(s) > 4 for s in segs):
        return False
    texts = [join_tokens(s) for s in segs]
    if any(not re.fullmatch(r"[A-Za-z][A-Za-z /&#().-]*", tx) for tx in texts):
        return False
    if i + 1 < len(lines) and lines[i + 1].top - ln.bottom < 14:
        nxt = lines[i + 1]
        starts = [s[0].x0 for s in segs]
        if sum(1 for t in nxt.tokens if any(abs(t.x0 - x) < 8 for x in starts)) >= 2:
            return False  # rows follow: a real table that _generic_table could not read
    bold = all(t.bold for t in ln.tokens) and all(t.source == "text" for t in ln.tokens)
    known = set()
    for sec in binder.template.sections:
        for col in sec.get("columns", []):
            known.update(norm(a) for a in [col.get("label", ""), *col.get("aliases", [])])
    return bold or all(norm(tx) in known for tx in texts)


def extract_structure(binder) -> Structure:
    """Read the template-free structure of every region (plus untitled page areas)."""
    from .bind import _parse_kv_line

    st = Structure()
    regions = list(binder.regions)
    # page areas outside every titled region (document header, untitled pages)
    counter = len(regions)
    for pd in binder.pages:
        lines = binder.lines_by_page.get(pd.number, [])
        free = [ln for ln in lines if not any(r.contains(t) for r in regions for t in ln.tokens)]
        groups: list[list[Line]] = []
        for ln in free:
            if groups and ln.top - groups[-1][-1].bottom < 30:
                groups[-1].append(ln)
            else:
                groups.append([ln])
        for g in groups:
            counter += 1
            toks = [t for ln in g for t in ln.tokens]
            name = "Document header" if pd.number == 1 and not any(r.page == 1 and r.top < g[0].top for r in regions) \
                else f"Page {pd.number}"
            r = Region(f"SEC_{counter:03d}", "other:" + slug(name), name, "", pd.number,
                       min(t.x0 for t in toks) - 1, min(t.top for t in toks) - 1, max(t.x1 for t in toks) + 1,
                       max(t.bottom for t in toks) + 1, bbox_of(g[0].tokens))
            st.pseudo_regions.append(r)
    for r in regions:
        if not r.continued:
            _assign(st, [t for t in binder.pages[r.page - 1].tokens if id(t) in binder.heading_ids
                         and r.heading_bbox[0] - 1 <= t.cx <= r.heading_bbox[2] + 1
                         and r.heading_bbox[1] - 1 <= t.cy <= r.heading_bbox[3] + 1], "heading")

    last_table: dict[str, GTable] = {}
    boxes_by_page = {p.number: p.boxes for p in binder.pages}
    for region in regions + st.pseudo_regions:
        lines = binder.lines(region)
        used: set[int] = set()
        # a table carried on from the previous page without its header
        if region.continued and region.key in last_table:
            prev = last_table[region.key]
            t = continue_table(lines, prev.table)
            if t:
                for row in t.rows:  # numbering carries on from the previous page
                    row.index += len(prev.rows) + (prev.rows[0].index - 1 if prev.rows else 0)
                gt = GTable(region, prev.header, t.rows, t)
                st.tables.append(gt)
                for row in t.rows:
                    for c in row.cells.values():
                        _assign(st, c.all_tokens, "table_cell")
                    used |= {k for k, l in enumerate(lines) if any(l is rl for rl in row.lines)}
                last_table[region.key] = gt
        # tables
        i = 0
        while i < len(lines):
            gt = _generic_table(lines, region, i, boxes_by_page) if i not in used else None
            if gt:
                st.tables.append(gt)
                last_table[region.key] = gt
                _assign(st, [t for _, seg in gt.header for t in seg], "table_header")
                consumed = {id(lines[i])}
                for row in gt.rows:
                    for c in row.cells.values():
                        _assign(st, c.all_tokens, "table_cell")
                for j in range(i + 1, len(lines)):
                    if any(id(t) in st.roles for t in lines[j].tokens) and all(
                            st.roles.get(id(t)) in ("table_cell",) for t in lines[j].tokens):
                        consumed.add(id(lines[j]))
                used |= {k for k in range(len(lines)) if id(lines[k]) in consumed}
                last = max(k for k in range(len(lines)) if id(lines[k]) in consumed)
                i = last + 1
                continue
            if _empty_table_header(lines, i, binder):
                _assign(st, lines[i].tokens, "table_header")
                used.add(i)
            i += 1
        _box_fields(st, binder, region, lines)
        for k, ln in enumerate(lines):
            if k in used:
                continue
            toks = [t for t in ln.tokens if id(t) not in st.roles]
            if not toks:
                continue
            # questions answered with check boxes
            if any(t.kind == "checkbox" for t in toks):
                from .layout import checkbox_options

                # several labelled choices on one line ("Sex: [ ] F [X] M   Marital Status: [X] Single")
                # are one question each; plain labelled fields between them stay fields
                pairs = _parse_kv_line(toks, [])
                groups: list[tuple[list[Token], list[Token]]] = []
                if pairs and any(any(v.kind == "checkbox" for v in vt) for _, _, vt in pairs):
                    lead = toks[:toks.index(pairs[0][1][0])]
                    if any(t.kind == "checkbox" for t in lead):
                        groups.append(([], lead))
                    rest = [t for t in lead if t.kind != "checkbox"] if not groups else []
                    for _, ltoks, vtoks in pairs:
                        if any(v.kind == "checkbox" for v in vtoks):
                            groups.append((ltoks, vtoks))
                        else:
                            rest += ltoks + vtoks
                else:
                    groups.append(([], toks))
                    rest = None
                trailing_all: list[Token] = []
                for ltoks, vtoks in groups:
                    question, opts, trailing = checkbox_options(vtoks)
                    question = ltoks + question
                    st.questions.append(GQuestion(region, question, opts))
                    _assign(st, question, "question")
                    for b, lab in opts:
                        _assign(st, [b], "checkbox")
                        _assign(st, lab, "option")
                    trailing_all += trailing
                # "Other: ___" after the boxes, and plain fields beside the choices, are fields of their own
                toks = [t for t in (rest if rest is not None else []) + trailing_all if id(t) not in st.roles]
                toks.sort(key=lambda t: t.x0)
                if not toks:
                    continue
            # labelled fields
            pairs = _parse_kv_line(toks, [])
            if pairs:
                first_label = pairs[0][1][0]
                lead = [t for t in toks[:toks.index(first_label)] if t.kind == "word"]
                if lead:
                    st.text.append((region, lead))
                    _assign(st, lead, "text")
                for n, (_, ltoks, vtoks) in enumerate(pairs):
                    vtoks = [t for t in vtoks if t.kind != "checkbox"]
                    continued = False
                    if vtoks:
                        right = pairs[n + 1][1][0].x0 - 4 if n + 1 < len(pairs) else region.x1
                        extra = [t for t in continuation_tokens(lines, k, vtoks, right) if id(t) not in st.roles]
                        if extra:
                            vtoks = vtoks + extra
                            continued = True
                    f = GField(region, ltoks, vtoks, label_text(join_tokens(ltoks)),
                               clean(join_tokens([t for t in vtoks if t.kind == "word"])), continued=continued)
                    st.fields.append(f)
                    _assign(st, ltoks, "label")
                    _assign(st, f.value_tokens, "value")
                continue
            # filled form fields with no printed label are named by the field itself
            for t in [t for t in toks if t.source == "form_field" and t.kind == "word" and id(t) not in st.roles]:
                name = t.hint or re.sub(r"[_.\-]+", " ", (t.field_name or "field").split(".")[-1]).strip()
                st.fields.append(GField(region, [], [t], name[:1].upper() + name[1:], clean(t.text), named_by_field=True))
                _assign(st, [t], "value")
            words = [t for t in toks if t.kind == "word" and id(t) not in st.roles]
            if words:
                st.text.append((region, words))
                _assign(st, words, "text")
        # signatures: ink on the line of an empty label ("Signature:", "Reviewed by:" ...)
        for f in [f for f in st.fields if f.region is region and not f.raw]:
            line_cy = sum(t.cy for t in f.label_tokens) / len(f.label_tokens)
            label_end = max(t.x1 for t in f.label_tokens)
            for mk in binder.marks:
                if mk.page == region.page and region.contains(mk) and abs(mk.cy - line_cy) < 14 and mk.x0 >= label_end - 4:
                    f.signature_mark = mk
                    break
    st.tokens_total = sum(1 for p in binder.pages for t in p.tokens if t.is_content and t.kind != "placeholder")
    return st


# --------------------------------------------------------------------------- comparison with the template
def _covered(tokens, boxes) -> bool:
    """True when (nearly) every token of a value lies inside something the template bound."""
    tokens = [t for t in tokens if t.kind != "placeholder"]
    if not tokens or not boxes:
        return not tokens
    inside = sum(1 for t in tokens if any(p == t.page and b[0] - 1.5 <= t.cx <= b[2] + 1.5
                                          and b[1] - 1.5 <= t.cy <= b[3] + 1.5 for p, b in boxes))
    return inside >= 0.6 * len(tokens)


def _template_boxes(binder) -> list:
    boxes = []
    for e in binder.entities.values():
        for a in e.attributes.values():
            if a.page and a.bbox:
                boxes.append((a.page, a.bbox))
            if a.page and a.label_bbox:
                boxes.append((a.page, a.label_bbox))
    return boxes


# --------------------------------------------------------------------------- generic entities
def build_generic(binder, st: Structure, template_used: bool, start_rel: int) -> tuple[list[Relationship], list[dict], dict]:
    """Turn structures into entities.  With a template, only what the template did not
    capture becomes a generic entity.  Returns (relationships, blank fields, coverage)."""
    boxes = _template_boxes(binder) if template_used else []
    rels: list[Relationship] = []
    sections: dict[str, Entity] = {}
    blanks: list[dict] = []
    leftovers = {"fields": 0, "table_rows": 0, "questions": 0}

    # a section continued on the next page is the same section
    canon: dict[str, Region] = {}
    last: dict[str, Region] = {}
    for r in binder.regions:
        if not r.continued:
            last[r.key] = r
        canon[r.region_id] = last.get(r.key, r) if r.continued else r

    def section_of(region: Region) -> Entity:
        region = canon.get(region.region_id, region)
        ent = sections.get(region.region_id)
        if ent is None:
            prefix, group = GENERIC_TYPES["Section"]
            ent = binder.new_entity("Section", prefix, region.name, region, group)
            if region.heading:
                ent.attributes["title"] = Attribute(
                    value=region.name, field_label=region.heading, page=region.hpage, bbox=region.heading_bbox,
                    extraction_method="section_heading", confidence=0.95, section=region.name,
                    region_id=region.region_id, order=(region.hpage, region.heading_bbox[1], 0))
            sections[region.region_id] = ent
        return ent

    def contains(region: Region, ent: Entity, ev_attr: Attribute | None, what: str):
        sec = section_of(region)
        ev = []
        if ev_attr and ev_attr.page and ev_attr.bbox:
            ev.append(Evidence(ev_attr.page, ev_attr.bbox, str(ev_attr.value), "object"))
        if region.heading:
            ev.append(Evidence(region.hpage, region.heading_bbox, region.heading, "heading"))
        conf = ev_attr.confidence if ev_attr else 0.9
        warnings = []
        rel = Relationship(f"REL_{start_rel + len(rels):03d}", sec.id, "CONTAINS", ent.id,
                           "explicit", conf,
                           f"{what} printed inside section '{region.name}'" + (f" (heading '{region.heading}', page {region.page})" if region.heading else f" (page {region.page})"),
                           section=region.name, heading=region.heading or None, page=region.page, evidence=ev,
                           warnings=warnings)
        if ev_attr and ev_attr.status != "valid":
            rel.warnings.append("the value it holds needs review")
            rel.support = "uncertain"
        rels.append(rel)

    # labelled fields
    for f in st.fields:
        if not f.value_tokens and not f.signature_mark:
            if not template_used and f.label_tokens:
                blanks.append({"kind": "blank_field", "path": f"{f.region.name}.{f.label}", "label": f.label,
                               "reason": "label printed with no value next to it", "entity": None,
                               "section": f.region.name, "page": f.region.page, "bbox": bbox_of(f.label_tokens)})
            continue
        if f.value_tokens and _covered(f.value_tokens, boxes):
            continue
        if f.signature_mark and not f.value_tokens and any(
                p == f.signature_mark.page and b == f.signature_mark.bbox for p, b in boxes):
            continue
        if f.is_signature:
            prefix, group = GENERIC_TYPES["Signature"]
            ent = binder.new_entity("Signature", prefix, f.label, f.region, group)
            if f.signature_mark is not None:
                mk = f.signature_mark
                attr = Attribute(value="ink signature", field_label=f.label, page=mk.page, bbox=mk.bbox,
                                 label_bbox=bbox_of(f.label_tokens), extraction_method="layout_signature",
                                 confidence=0.9, section=f.region.name, region_id=f.region.region_id,
                                 order=(mk.page, mk.top, mk.x0))
            else:
                attr = binder.make_attr(f.raw, f.label_tokens, f.value_tokens, "key_value", f.region, raw=f.raw,
                                        label=f.label)
            ent.attributes["signature"] = attr
            contains(f.region, ent, attr, f"signature '{f.label}'")
        else:
            prefix, group = GENERIC_TYPES["Field"]
            value, vtype = detect_value(f.raw, binder.parse_order, f.label)
            ent = binder.new_entity("Field", prefix, f.label, f.region, group)
            attr = binder.make_attr(value, f.label_tokens, f.value_tokens, "key_value", f.region, raw=f.raw,
                                    label=f.label)
            _generic_flags(binder, attr, f.raw, vtype, f.continued)
            if f.named_by_field:
                attr.notes.append("no printed label: named after the form field's own description")
                attr.field_label = f.label
            ent.attributes["value"] = attr
            ent.extra["value_type"] = vtype
            contains(f.region, ent, attr, f"'{f.label}' field")
        leftovers["fields"] += 1

    # tables
    for gt in st.tables:
        headers = [(f"c{i}", tx, seg) for i, (tx, seg) in enumerate(gt.header)]
        for row in gt.rows:
            cells = [(key, tx, seg, row.cells.get(key)) for key, tx, seg in headers]
            filled = [(k, tx, seg, c) for k, tx, seg, c in cells if c and c.text]
            # a printed row label with nothing filled in is an empty row, not data
            if not filled or (len(filled) == 1 and filled[0][0] == "c0"):
                continue
            if all(_covered(c.all_tokens, boxes) for _, _, _, c in filled):
                continue
            prefix, group = GENERIC_TYPES["TableRow"]
            first = filled[0][3].text
            ent = binder.new_entity("TableRow", prefix, first, gt.region, group, row=row.index)
            ent.extra["table_header"] = [tx for _, tx, _ in headers]
            for k, tx, seg, c in filled:
                value, vtype = detect_value(c.text, binder.parse_order, tx)
                attr = binder.make_attr(value, seg, c.all_tokens, "table", gt.region, raw=c.text, row=row.index,
                                        label=tx)
                if k in row.wrapped_columns:
                    attr.status = "needs_review"
                    attr.confidence = min(attr.confidence, 0.55)
                    attr.notes.append("value continues on a following line with no row key; merged into the row above")
                _generic_flags(binder, attr, c.text, vtype, False)
                ent.attributes[slug(tx) or k] = attr
            contains(gt.region, ent, ent.attributes[next(iter(ent.attributes))], f"row {row.index} of the table")
            leftovers["table_rows"] += 1

    # check-box questions
    for q in st.questions:
        checked = [(b, lab) for b, lab in q.options if b.checked]
        if template_used:
            if not checked or all(_covered([b] + lab, boxes) for b, lab in checked):
                continue
        prefix, group = GENERIC_TYPES["Question"]
        label = q.text or q.region.name
        ent = binder.new_entity("Question", prefix, label, q.region, group)
        chosen = [label_text(join_tokens(lab)) or "(unlabelled box)" for _, lab in checked]
        opts = [label_text(join_tokens(lab)).lower() for _, lab in q.options]
        yes_no = set(opts) <= {"yes", "no", "y", "n"} and len(opts) >= 2
        value = (chosen[0].lower() if len(chosen) == 1 else None) if yes_no else chosen
        vtoks = [x for b, lab in (checked or q.options) for x in [b, *lab]]
        attr = binder.make_attr(value, q.question_tokens, vtoks, "checkbox", q.region, label=label,
                                raw=" ".join(f"{b.text} {join_tokens(lab)}" for b, lab in q.options))
        if yes_no and len(chosen) != 1:
            attr.status = "needs_review"
            attr.notes.append("could not resolve a single yes/no answer" if chosen else "no answer was marked")
        if any(not lab for _, lab in q.options) or (yes_no and any(
                norm(t.text) in ("yes", "no") for t in q.question_tokens)):
            attr.status = "needs_review"
            attr.notes.append("part of this line could not be read (a box or its label is missing)")
        ent.attributes["answer"] = attr
        ent.extra["options"] = [label_text(join_tokens(lab)) for _, lab in q.options]
        contains(q.region, ent, attr, "check-box question")
        leftovers["questions"] += 1

    # a date printed on the same line as a signature dates that signature
    sigs = [e for e in binder.entities.values() if e.type == "Signature"]
    dates = [e for e in binder.entities.values() if e.type == "Field" and e.extra.get("value_type") == "date"]
    for sig in sigs:
        sa = sig.attributes.get("signature")
        if not sa or not sa.bbox:
            continue
        scy = (sa.bbox[1] + sa.bbox[3]) / 2
        same_line = [d for d in dates if d.region_id == sig.region_id and d.attributes["value"].page == sa.page
                     and abs((d.attributes["value"].bbox[1] + d.attributes["value"].bbox[3]) / 2 - scy) < 9]
        if same_line:
            d = min(same_line, key=lambda d: abs(d.attributes["value"].bbox[0] - sa.bbox[2]))
            da = d.attributes["value"]
            rels.append(Relationship(
                f"REL_{start_rel + len(rels):03d}", sig.id, "DATED", d.id, "explicit",
                min(sa.confidence, da.confidence),
                f"'{da.field_label}' printed on the same line as the signature '{sig.label}'",
                section=sig.section, page=sa.page,
                evidence=[Evidence(sa.page, sa.bbox, str(sa.value), "subject"),
                          Evidence(da.page, da.bbox, str(da.value), "object")]))

    explained = sum(1 for p in binder.pages for t in p.tokens if t.is_content and t.kind != "placeholder"
                    and id(t) in st.roles)
    coverage = {
        "tokens_total": st.tokens_total,
        "tokens_explained": explained,
        "roles": {r: sum(1 for v in st.roles.values() if v == r) for r in sorted(set(st.roles.values()))},
        "generic_fields": leftovers["fields"],
        "generic_table_rows": leftovers["table_rows"],
        "generic_questions": leftovers["questions"],
        "tables": len(st.tables),
        "fields": len(st.fields),
        "questions": len(st.questions),
    }
    return rels, blanks, coverage


def unexplained_tokens(binder, st: Structure) -> list[Token]:
    return [t for p in binder.pages for t in p.tokens
            if t.is_content and t.kind != "placeholder" and id(t) not in st.roles]


# --------------------------------------------------------------------------- reading order
def build_blocks(binder, st: Structure) -> list[dict]:
    """The whole document in reading order: headings, fields, tables, questions,
    signatures, paragraphs and page furniture - every piece of text, with its page and box."""
    blocks: list[dict] = []
    order = {r.region_id: i for i, r in enumerate(sorted(binder.regions + st.pseudo_regions,
                                                           key=lambda r: (r.page, r.top, r.x0)))}

    def add(kind, region, toks, **kw):
        toks = [t for t in toks if t is not None]
        if not toks:
            return
        b = {"type": kind, "page": toks[0].page, "bbox": bbox_of(toks),
             "section": region.name if region else None, "section_id": region.region_id if region else None}
        b.update(kw)
        b["_key"] = (toks[0].page, order.get(region.region_id, -1) if region else -1,
                     min(t.top for t in toks), min(t.x0 for t in toks))
        blocks.append(b)

    for r in binder.regions:
        if not r.continued and r.heading:
            hb = r.heading_bbox
            blocks.append({"type": "heading", "text": r.heading, "name": r.name, "page": r.hpage, "bbox": hb,
                           "section": r.name, "section_id": r.region_id,
                           "_key": (r.hpage, order[r.region_id], hb[1] - 0.01, hb[0])})
    for f in st.fields:
        sig = f.signature_mark
        if f.is_signature or sig is not None:
            toks = f.label_tokens + f.value_tokens
            b_extra = {"label": f.label, "value": f.raw or ("ink signature" if sig is not None else None),
                       "signed": bool(f.raw or sig is not None)}
            add("signature", f.region, toks, **b_extra)
            if sig is not None:
                blocks[-1]["bbox"] = [min(blocks[-1]["bbox"][0], sig.x0), min(blocks[-1]["bbox"][1], sig.top),
                                      max(blocks[-1]["bbox"][2], sig.x1), max(blocks[-1]["bbox"][3], sig.bottom)]
        else:
            value, vtype = detect_value(f.raw, binder.parse_order, f.label) if f.raw else (None, "empty")
            add("field", f.region, f.label_tokens + f.value_tokens, label=f.label, value=f.raw or None,
                normalized=value if value != f.raw else None, value_type=vtype)
    for gt in st.tables:
        header = [tx for tx, _ in gt.header]
        rows = [[(row.cells.get(f"c{i}").text if row.cells.get(f"c{i}") else "") for i in range(len(header))]
                for row in gt.rows]
        toks = ([t for _, seg in gt.header for t in seg] if gt.header and gt.header[0][1][0].page == gt.region.page else []) + \
            [t for row in gt.rows for c in row.cells.values() for t in c.all_tokens]
        add("table", gt.region, toks, header=header, rows=rows, continued=gt.region.continued)
    for q in st.questions:
        toks = q.question_tokens + [x for b, lab in q.options for x in [b, *lab]]
        add("question", q.region, toks, question=q.text or None,
            options=[{"label": label_text(join_tokens(lab)), "checked": bool(b.checked)} for b, lab in q.options])
    # paragraphs: consecutive text lines of one section
    paras: list[tuple[Region, list[list[Token]]]] = []
    for region, words in sorted(st.text, key=lambda rw: (rw[1][0].page, order.get(rw[0].region_id, -1),
                                                          min(t.top for t in rw[1]))):
        if paras and paras[-1][0] is region:
            prev = paras[-1][1][-1]
            gap = min(t.top for t in words) - max(t.bottom for t in prev)
            h = max(t.height for t in words)
            if 0 <= gap < 0.9 * h and abs(min(t.x0 for t in words) - min(t.x0 for t in prev)) < 25:
                paras[-1][1].append(words)
                continue
        paras.append((region, [words]))
    for region, lines in paras:
        add("text", region, [t for ln in lines for t in ln], text="\n".join(join_tokens(ln) for ln in lines))
    from .layout import build_lines

    furniture_lines = [ln for p in binder.pages
                       for ln in build_lines([_as_word(t) for t in p.tokens if t.kind == "furniture"])]
    for ln in furniture_lines:
        blocks.append({"type": "page_furniture", "text": ln.text, "page": ln.page, "bbox": bbox_of(ln.tokens),
                       "section": None, "section_id": None,
                       "_key": (ln.page, -1 if ln.top < 400 else 10 ** 6, ln.top, ln.x0)})
    blocks.sort(key=lambda b: b["_key"])
    for i, b in enumerate(blocks, start=1):
        b.pop("_key")
        b["block_id"] = f"BLK_{i:03d}"
    return blocks


def _as_word(t: Token) -> Token:
    import copy

    c = copy.copy(t)
    c.kind = "word"
    return c


def blocks_to_markdown(doc: dict) -> str:
    """A readable Markdown rendering of the reading-order blocks."""
    d = doc["document"]
    out = [f"<!-- {d['filename']} - {d.get('document_type') or 'document'} - read by docintel -->", ""]
    page = None
    for b in doc.get("blocks", []):
        if b["page"] != page:
            page = b["page"]
            out += ["", f"<!-- page {page} -->", ""]
        t = b["type"]
        if t == "heading":
            first = not any(l.startswith("# ") for l in out)
            out += [("# " if first else "## ") + b["name"], ""]
        elif t == "field":
            out.append(f"**{b['label']}:** {b['value'] if b['value'] is not None else '_(blank)_'}  ")
        elif t == "signature":
            out.append(f"**{b['label']}:** {('✍ ' + b['value']) if b.get('signed') else '_(not signed)_'}  ")
        elif t == "question":
            opts = "  ".join(f"[{'x' if o['checked'] else ' '}] {o['label']}" for o in b["options"])
            out.append(f"{b['question'] + ' ' if b.get('question') else ''}{opts}  ")
        elif t == "table":
            cols = b["header"]
            out += ["", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
            for row in b["rows"]:
                out.append("| " + " | ".join(c.replace("|", "\\|") for c in row) + " |")
            out.append("")
        elif t == "text":
            out += ["", b["text"].replace("\n", " "), ""]
        elif t == "page_furniture":
            out.append(f"<!-- {b['text']} -->")
    text = "\n".join(out)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip() + "\n"


# --------------------------------------------------------------------------- document type
# Words that name a kind of document.  Titles and headings count three times as much as
# body text; the guess is only a label - nothing is extracted differently because of it.
DOC_KEYWORDS = {
    "invoice": ["invoice", "bill to", "amount due", "total due", "invoice no", "invoice number", "remit to"],
    "receipt": ["receipt", "amount paid", "payment received"],
    "lab report": ["lab report", "laboratory", "test results", "reference range", "specimen", "collected"],
    "referral": ["referral", "referring physician", "referred to", "reason for referral"],
    "prescription": ["prescription", "dispense", "refills", "rx number"],
    "discharge summary": ["discharge summary", "discharge diagnosis", "admission date", "discharge date"],
    "purchase order": ["purchase order", "po number", "ship to"],
    "insurance claim": ["claim form", "claim number", "explanation of benefits", "cms 1500"],
    "screening questionnaire": ["screening", "questionnaire", "over the last 2 weeks", "phq", "gad"],
    "consent form": ["consent form", "informed consent", "i consent"],
    "order form": ["order form", "requisition", "order number", "order no"],
    "letter": ["dear", "sincerely", "yours faithfully", "kind regards"],
}


def guess_document_type(binder) -> tuple[str, str] | None:
    """(type, basis) from the words on the first page, or None when nothing names it."""
    from .template import norm

    first = [p for p in binder.pages if p.number == 1]
    body = " " + norm(" ".join(t.text for p in first for t in p.tokens if t.kind == "word")) + " "
    heads = " " + norm(" ".join(r.heading for r in binder.regions if r.page == 1 and r.heading)) + " "
    best, basis = None, []
    best_score = 0
    for dtype, words in DOC_KEYWORDS.items():
        score, found = 0, []
        for w in words:
            k = " " + norm(w) + " "
            if k in heads:
                score += 3
                found.append(w)
            elif k in body:
                score += 1
                found.append(w)
        if score > best_score:
            best, best_score, basis = dtype, score, found
    if best is None or best_score < 2:
        return None
    return best, "words on page 1: " + ", ".join(f"'{w}'" for w in basis[:4])
