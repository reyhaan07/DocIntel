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

from .layout import Cell, Table, TableRow, bbox_of, find_table, join_tokens, segments, slug
from .models import Attribute, Entity, Line, Region, Relationship, Evidence, Token
from .normalize import clean, format_phone, label_text, parse_date

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
def detect_value(raw: str):
    """-> (normalised value, value type).  Unknown documents still get typed values."""
    v = clean(raw)
    if not v:
        return None, "empty"
    iso = parse_date(v)
    if iso:
        return iso, "date"
    if re.fullmatch(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", v.replace(" ", "")):
        return v.replace(" ", "").lower(), "email"
    digits = re.sub(r"\D", "", v)
    if re.fullmatch(r"[\d\s().+-]{10,18}", v) and len(digits) in (10, 11):
        return format_phone(v), "phone"
    if re.fullmatch(r"[-+]?[$€£]\s?\d[\d,]*(\.\d+)?|[-+]?\d[\d,]*(\.\d{2})\s?(USD|EUR|GBP)?", v):
        return v, "amount"
    if re.fullmatch(r"[-+]?\d+([.,]\d+)?\s?%?", v):
        return v, "number"
    if v.lower() in ("yes", "no", "y", "n", "true", "false"):
        return v.lower()[0] in "yt" and "yes" or "no", "yes_no"
    return v, "text"


# --------------------------------------------------------------------------- structures
@dataclass
class GField:
    region: Region
    label_tokens: list[Token]
    value_tokens: list[Token]
    label: str
    raw: str
    signature_mark: object = None

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


def _generic_table(lines: list[Line], region: Region, start: int):
    """A header row (2+ separated short labels, no colons) with aligned rows below it."""
    ln = lines[start]
    segs = segments(ln, gap=12)
    if len(segs) < 2 or any(t.kind != "word" or t.text.endswith(":") for t in ln.tokens):
        return None
    if any(len(s) > 4 for s in segs):
        return None
    texts = [join_tokens(s) for s in segs]
    if any(not re.search(r"[A-Za-z]{2,}", tx) for tx in texts):
        return None
    if start + 1 >= len(lines):
        return None
    nxt = lines[start + 1]
    starts = [s[0].x0 for s in segs]
    hit_cols = {i for t in nxt.tokens for i, x in enumerate(starts) if x - 8 <= t.x0 < (starts[i + 1] - 6 if i + 1 < len(starts) else 1e9)}
    if len(hit_cols) < 2 or any(t.text.endswith(":") for t in nxt.tokens[:1]):
        return None
    specs = [{"key": f"c{i}", "label": tx, "aliases": [tx], "row_key": i == 0} for i, tx in enumerate(texts)]
    table = find_table(lines[start:], specs, region)
    if not table or not table.rows:
        return None
    # rows end at the first large vertical gap (the table is over)
    rows, prev_bottom = [], table.header.bottom
    gaps = []
    for row in table.rows:
        top = min(l.top for l in row.lines)
        gap = top - prev_bottom
        typical = sorted(gaps)[len(gaps) // 2] if gaps else 8.0
        if gap > max(14.0, 2.2 * typical):
            break
        gaps.append(gap)
        rows.append(row)
        prev_bottom = max(l.bottom for l in row.lines)
    if not rows:
        return None
    table.rows = rows
    return GTable(region, list(zip(texts, segs)), rows, table)


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

    for region in regions + st.pseudo_regions:
        lines = binder.lines(region)
        used: set[int] = set()
        # tables
        i = 0
        while i < len(lines):
            gt = _generic_table(lines, region, i)
            if gt:
                st.tables.append(gt)
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
            i += 1
        for k, ln in enumerate(lines):
            if k in used:
                continue
            toks = [t for t in ln.tokens if id(t) not in st.roles]
            if not toks:
                continue
            # questions answered with check boxes
            if any(t.kind == "checkbox" for t in toks):
                first = next(n for n, t in enumerate(toks) if t.kind == "checkbox")
                question = [t for t in toks[:first] if t.kind == "word"]
                opts, n = [], first
                while n < len(toks):
                    if toks[n].kind == "checkbox":
                        lab = []
                        m = n + 1
                        while m < len(toks) and toks[m].kind == "word" and (not lab or toks[m].x0 - lab[-1].x1 < 20):
                            lab.append(toks[m])
                            m += 1
                        opts.append((toks[n], lab))
                        n = m
                    else:
                        n += 1
                # "Other: ___" after the boxes is a field of its own
                st.questions.append(GQuestion(region, question, opts))
                _assign(st, question, "question")
                for b, lab in opts:
                    _assign(st, [b], "checkbox")
                    _assign(st, lab, "option")
                continue
            # labelled fields
            pairs = _parse_kv_line(toks, [])
            if pairs:
                first_label = pairs[0][1][0]
                lead = [t for t in toks[:toks.index(first_label)] if t.kind == "word"]
                if lead:
                    st.text.append((region, lead))
                    _assign(st, lead, "text")
                for _, ltoks, vtoks in pairs:
                    f = GField(region, ltoks, [t for t in vtoks if t.kind != "checkbox"],
                               label_text(join_tokens(ltoks)), clean(join_tokens([t for t in vtoks if t.kind == "word"])))
                    st.fields.append(f)
                    _assign(st, ltoks, "label")
                    _assign(st, f.value_tokens, "value")
                continue
            words = [t for t in toks if t.kind == "word"]
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

    def section_of(region: Region) -> Entity:
        ent = sections.get(region.region_id)
        if ent is None:
            prefix, group = GENERIC_TYPES["Section"]
            ent = binder.new_entity("Section", prefix, region.name, region, group)
            if region.heading:
                ent.attributes["title"] = Attribute(
                    value=region.name, field_label=region.heading, page=region.page, bbox=region.heading_bbox,
                    extraction_method="section_heading", confidence=0.95, section=region.name,
                    region_id=region.region_id, order=(region.page, region.heading_bbox[1], 0))
            sections[region.region_id] = ent
        return ent

    def contains(region: Region, ent: Entity, ev_attr: Attribute | None, what: str):
        sec = section_of(region)
        ev = []
        if ev_attr and ev_attr.page and ev_attr.bbox:
            ev.append(Evidence(ev_attr.page, ev_attr.bbox, str(ev_attr.value), "object"))
        if region.heading:
            ev.append(Evidence(region.page, region.heading_bbox, region.heading, "heading"))
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
            if not template_used:
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
            value, vtype = detect_value(f.raw)
            ent = binder.new_entity("Field", prefix, f.label, f.region, group)
            attr = binder.make_attr(value, f.label_tokens, f.value_tokens, "key_value", f.region, raw=f.raw,
                                    label=f.label)
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
                value, vtype = detect_value(c.text)
                attr = binder.make_attr(value, seg, c.all_tokens, "table", gt.region, raw=c.text, row=row.index,
                                        label=tx)
                if k in row.wrapped_columns:
                    attr.status = "needs_review"
                    attr.confidence = min(attr.confidence, 0.55)
                    attr.notes.append("value continues on a following line with no row key; merged into the row above")
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
