"""Stage 3 - Bind.

A value may only join an entity if it was found inside that entity's section
region, and - for tables - on the same table row.  Nothing is bound because it
happens to be *near* something else on the page.
"""
from __future__ import annotations

import re
from collections import defaultdict

from .layout import (Cell, Table, bbox_of, build_lines, build_regions, checkbox_options, continuation_tokens,
                     labels_below,
                     continue_table, find_table, join_tokens, match_aliases, region_lines)
from .models import Attribute, Entity, Line, PageData, Region, Token
from .normalize import (clean, none_answer, split_dose_frequency, infer_date_order, is_ambiguous_date, label_text, name_key, normalise, split_list,
                        middle_initial, split_person_name)
from .template import Template, norm, norm_tokens

TYPE_NAMES = {
    "Patient": "Patient", "Spouse": "Spouse", "EmergencyContact": "Emergency contact",
    "InsurancePolicy": "Insurance policy", "InsuranceCompany": "Insurance company", "Medication": "Medication",
    "Doctor": "Doctor", "Allergy": "Allergy", "Condition": "Condition", "Surgery": "Surgery", "Hospital": "Hospital",
    "FamilyMember": "Family member", "Consent": "Consent", "AuthorizedPerson": "Authorized person",
    "Agreement": "Agreement", "Pharmacy": "Pharmacy",
}

BASE_CONF = {"key_value": 0.92, "table": 0.90, "checkbox": 0.90, "family": 0.85, "signature": 0.90}
WRAPPED_CONF = 0.55
OCR_REVIEW_CONF = 0.6  # an OCR word read with less confidence than this is never accepted silently
WRAP_NOTE = "value continues on a following line with no row key; merged into the row above"


def _method(tokens: list[Token], kind: str) -> tuple[str, float]:
    srcs = {t.source for t in tokens}
    if srcs and srcs <= {"form_field"}:
        return ("form_field" if kind != "checkbox" else "form_field_checkbox"), 0.98
    base = BASE_CONF.get(kind, 0.9)
    tag = {"family": "key_value"}.get(kind, kind)
    if "ocr" in srcs:
        oc = min(t.conf for t in tokens if t.source == "ocr")
        return f"ocr_{tag}", round(min(base, 0.8) * (0.6 + 0.4 * oc), 2)
    return f"layout_{tag}", base


# Words that turn a known label into a different field: "Work Phone" is not the
# patient's phone, "Spouse Name" is not the patient's name.
QUALIFIERS = {
    "work", "home", "cell", "office", "business", "fax", "alternate", "alt", "other", "secondary", "previous",
    "former", "maiden", "spouse", "partner", "mother", "father", "parent", "guardian", "employer", "pharmacy",
    "physician", "doctor", "referring", "insured", "subscriber", "holder", "billing", "mailing", "emergency",
    "school", "child", "sibling", "nearest", "witness", "interpreter", "agent", "representative", "provider",
    "facility", "clinic", "hospital", "company", "contact",
}


def _qualified(tokens: list[Token], i: int, labels) -> bool:
    """Is the label starting at tokens[i] really the tail of a longer, different label?"""
    if i == 0:
        return False
    prev = tokens[i - 1]
    if prev.kind != "word" or prev.text.endswith(":") or tokens[i].x0 - prev.x1 >= 5:
        return False
    if labels and labels[-1][1] == i - 1:  # the word is the only value of the label before it
        return False
    return norm(prev.text) in QUALIFIERS


def _parse_kv_line(tokens: list[Token], table) -> list[tuple[dict | None, list[Token], list[Token]]]:
    """Split one line into (field spec | None, label tokens, value tokens) triples."""
    labels: list[tuple[int, int, dict | None]] = []
    n = len(tokens)

    def after_box(k: int) -> bool:
        # words printed right after a check box are that box's option ("[X] Other: ___"), not a label
        return k > 0 and tokens[k - 1].kind == "checkbox" and tokens[k].x0 - tokens[k - 1].x1 < 20

    i = 0
    while i < n:
        t = tokens[i]
        if t.kind == "word" and after_box(i):
            i += 1
            continue
        if t.kind == "word":
            m = match_aliases(tokens, i, table)
            if m and _qualified(tokens, i, labels):
                m = None  # handled below as a label of its own ("Work Phone:")
            if m:
                consumed, spec = m
                j = i + consumed
                # a format hint printed in brackets after the label: "Date of Birth (MM/DD/YYYY):"
                if j < n and tokens[j].kind == "word" and tokens[j].text.startswith("(") and tokens[j].x0 - tokens[j - 1].x1 < 8:
                    k = j
                    while k < n - 1 and k < j + 6 and ")" not in tokens[k].text and tokens[k + 1].kind == "word":
                        k += 1
                    if ")" in tokens[k].text and (tokens[k].text.endswith(":") or (k + 1 < n and tokens[k + 1].text == ":")):
                        consumed = k + 1 - i
                last = tokens[i + consumed - 1]
                nxt = tokens[i + consumed] if i + consumed < n else None
                colon_tok = nxt is not None and nxt.text == ":"
                # OCR often loses a label's colon: accept a label that stands apart on its line
                ocr_label = (all(x.source == "ocr" for x in tokens[i:i + consumed])
                             and (i == 0 or tokens[i].x0 - tokens[i - 1].x1 > 12)
                             and (nxt is None or nxt.x0 - last.x1 > 15))
                if (last.text.endswith(":") or colon_tok or ocr_label
                        or (nxt is not None and nxt.source == "form_field" and nxt.kind != "checkbox")):
                    end = i + consumed + (1 if colon_tok else 0)
                    labels.append((i, end, spec))
                    i = end
                    continue
            if (t.text.endswith(":") and t.source == "ocr" and t.text[:1].islower() and labels and i > 0
                    and tokens[i - 1].kind == "word" and t.x0 - tokens[i - 1].x1 < 0.6 * t.height):
                i += 1  # OCR reads ';' as ':' - "10 mg daily: Metformin" continues the value
                continue
            if t.text.endswith(":") and len(t.text) > 1 and not re.search(r"\d:\d", t.text):
                start = i
                floor = labels[-1][1] if labels else 0
                while (start - 1 >= floor and i - start < 4 and tokens[start - 1].kind == "word"
                       and not tokens[start - 1].text.endswith(":") and tokens[start].x0 - tokens[start - 1].x1 < 5):
                    start -= 1
                if after_box(start):
                    i += 1
                    continue
                # words reaching back to the previous label are the value of that label,
                # unless a wide empty gap separates them from it (an empty field)
                if labels and start == floor:
                    prev_end = tokens[floor - 1].x1 if floor > 0 else None
                    if prev_end is None or tokens[floor].x0 - prev_end < 12:
                        start = i
                labels.append((start, i + 1, None))
        i += 1
    out = []
    for k, (s, e, spec) in enumerate(labels):
        nxt_start = labels[k + 1][0] if k + 1 < len(labels) else n
        out.append((spec, tokens[s:e], list(tokens[e:nxt_start])))  # check boxes stay: they may be the answer
    return out


_DATE_HINT = re.compile(r"\b(mm|dd|yyyy|yy)\s*[/.\-]\s*(mm|dd)\s*[/.\-]\s*(yyyy|yy|dd)\b", re.I)


def date_hint(label: str) -> str | None:
    """The date order a label prints for its value: 'Date of Birth (DD/MM/YYYY)' -> 'dmy'."""
    m = _DATE_HINT.search(label or "")
    if not m:
        return None
    first = m.group(1).lower()
    return "ymd" if first.startswith("y") else "dmy" if first == "dd" else "mdy"


def name_hint(label: str) -> str | None:
    """'Name (Last, First, MI)' -> 'last_first'; 'Name (First Last)' -> 'first_last'."""
    m = re.search(r"\(([^)]*)\)", label or "")
    if not m:
        return None
    inner = m.group(1).lower()
    if re.search(r"\b(last|surname|family)\b.*\b(first|given)\b", inner):
        return "last_first"
    if re.search(r"\b(first|given)\b.*\b(last|surname|family)\b", inner):
        return "first_last"
    return None


def _hint_conflict(raw: str, order: str) -> bool:
    """A numeric date that cannot be in the order its label prints ('13/05/1975' under MM/DD)."""
    m = re.fullmatch(r"\s*(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\s*", raw or "")
    if not m or order not in ("mdy", "dmy"):
        return False
    a, b = int(m.group(1)), int(m.group(2))
    month = a if order == "mdy" else b
    return month > 12


_LIST_PROMPT = re.compile(r"\b(list|please list|if yes|specify|describe|name them)\b", re.I)
_INSTRUCTION = re.compile(r"\b(please|list|include|including|if|you|your|below|above|attach|check|circle|"
                          r"complete|provide|describe|indicate|write)\b", re.I)
_DOSE_START = re.compile(r"\s(?=\d[\d.,/]*\s*(?:mg|mcg|g|ml|iu|units?|puffs?|tabs?|tablets?|caps?|capsules?|drops?|%|meq|mmol)\b)",
                         re.I)


def _list_items(words: list[Token]) -> list[list[Token]]:
    """Split a written list into items at commas, semicolons and bullets."""
    items: list[list[Token]] = []
    cur: list[Token] = []
    for t in words:
        txt = t.text
        if txt in ("•", "·", "-", "–", ";", ",") or re.fullmatch(r"\d{1,2}[.)]", txt):
            if cur:
                items.append(cur)
            cur = []
            continue
        cur.append(t)
        if txt.endswith((",", ";")) or (t.source == "ocr" and txt.endswith(":")):  # OCR: ';' read as ':'
            items.append(cur)
            cur = []
    if cur:
        items.append(cur)
    return items


def _parse_list_item(etype: str, text: str) -> tuple[dict, bool]:
    """One written item -> (column values, parsed with confidence)."""
    text = re.sub(r"^[•·\-–\d.)\s]+(?=[A-Za-z])", "", text).strip()
    if not text:
        return {}, False
    if etype == "Medication":
        m = _DOSE_START.search(" " + text)
        if not m:
            ok = not re.search(r"\d", text)  # a name without a dose; digits elsewhere are unexplained
            return {"name": text}, ok
        name, rest = text[:m.start()].strip(), text[m.start():].strip()
        dose, freq, ok = split_dose_frequency(rest)
        return {"name": name, "dosage": dose, "frequency": freq}, ok and bool(re.search(r"[A-Za-z]", name))
    if etype == "Allergy":
        m = re.fullmatch(r"(?P<a>[^()\-–:]+?)\s*(?:\((?P<r>[^)]*)\)|[-–:]\s*(?P<r2>.+))?", text)
        if not m:
            return {"allergen": text}, False
        return {"allergen": m.group("a").strip(), "reaction": (m.group("r") or m.group("r2") or "").strip() or None}, True
    if etype == "Surgery":
        m = re.fullmatch(r"(?P<p>.+?)[\s,(-]*(?:in\s+)?(?P<y>(?:19|20)\d{2})?\)?", text)
        if not m:
            return {"procedure": text}, False
        return {"procedure": m.group("p").strip(" ,(-"), "year": m.group("y")}, True
    return {}, False


def _tokens_for(tokens: list[Token], value: str) -> list[Token]:
    """The tokens of an item that print a given part of it."""
    words = set(re.sub(r"[^\w%./-]+", " ", value.lower()).split())
    return [t for t in tokens if re.sub(r"[^\w%./-]+", " ", t.text.lower()).strip() in words]


def choice_value(vtoks: list[Token]):
    """A field answered by ticking one of its printed options ("Sex: [ ] F [X] M").

    Returns (text, evidence tokens, problems).  ``text`` is None when nothing is ticked.
    Every doubt is a problem for review: several ticks, a tick without a readable option,
    or words that belong to no option."""
    lead, opts, trailing = checkbox_options(vtoks)
    # a fillable radio option with no printed label is named by its export value ("Male")
    opts = [(b, lab or ([Token(b.hint, b.x1 + 1, b.top, b.x1 + 1 + 5 * len(b.hint), b.bottom, b.page, "form_field",
                                hint="export value")] if b.hint and b.source == "form_field" else []))
            for b, lab in opts]
    ticked = [(b, lab) for b, lab in opts if b.checked]
    problems: list[str] = []
    names = ", ".join(clean(join_tokens(lab)) or "?" for _, lab in opts)
    if not ticked:
        return None, [b for b, _ in opts], [f"none of the options ({names}) is ticked"]
    if len(ticked) > 1:
        problems.append(f"{len(ticked)} options are ticked ({', '.join(clean(join_tokens(l)) or '?' for _, l in ticked)})")
    if any(not lab for _, lab in ticked):
        problems.append("a ticked box has no readable option next to it")
    words_after = [t for t in trailing if t.kind == "word"]
    toks = [x for b, lab in ticked for x in (b, *lab)]
    text = ", ".join(clean(join_tokens(lab)) for _, lab in ticked if lab)
    if words_after:
        if ticked[-1][0] is opts[-1][0]:  # "[X] Other: Buddhist" - the text is the option's answer
            text = clean(f"{text} {join_tokens(words_after)}")
            toks += words_after
        else:
            problems.append(f"text '{clean(join_tokens(words_after))}' after the options belongs to none of them")
    stray = [t for t in lead if t.kind == "word"]
    if stray:
        problems.append(f"text '{clean(join_tokens(stray))}' before the options belongs to none of them")
    return text or None, toks, problems


class Binder:
    def __init__(self, pages: list[PageData], template: Template, scan: bool = False):
        self.pages = pages
        self.template = template
        self.scan = scan
        self.lines_by_page = {p.number: build_lines(p.tokens) for p in pages}
        self.regions: list[Region] = build_regions(pages, self.lines_by_page, template)
        self.heading_ids: set[int] = set()
        for p in pages:
            for t in p.tokens:
                for r in self.regions:
                    hb = r.heading_bbox
                    if r.page == t.page and not r.continued and hb[0] - 1 <= t.cx <= hb[2] + 1 and hb[1] - 1 <= t.cy <= hb[3] + 1:
                        self.heading_ids.add(id(t))
        self.entities: dict[str, Entity] = {}
        self.counters: dict[str, int] = defaultdict(int)
        self.missing: list[dict] = []
        self.slots: list[dict] = []  # scan-template mode
        self.unbound: list[dict] = []
        self.sections_seen: list[str] = []
        self.marks = [m for p in pages for m in p.marks]
        self.continued: set[int] = set()  # tokens joined to a value from the following line
        self._unclear_lines: set[int] = set()  # yes/no lines where a box or an answer was not readable
        self.none_answers: dict[str, Attribute] = {}  # section key -> "NKDA"/"None" written in its table
        self.bound_ids: set[int] = set()  # tokens already read into an inline list
        self.below_labels: set[int] = set()  # labels printed under their value (signature blocks)
        # day/month order of numeric dates, decided once for the whole document
        self.date_order = infer_date_order([t.text for p in pages for t in p.tokens if t.kind == "word"])
        self.parse_order = "dmy" if self.date_order == "dmy" else "mdy"

    # ------------------------------------------------------------------ helpers
    def lines(self, region: Region) -> list[Line]:
        return region_lines(region, self.lines_by_page.get(region.page, []), self.heading_ids)

    def new_entity(self, etype: str, prefix: str, label: str, region: Region | None, group: str,
                   row: int | None = None, derived: bool = False) -> Entity:
        self.counters[prefix] += 1
        eid = f"{prefix}_{self.counters[prefix]:03d}"
        ent = Entity(eid, etype, label, region.name if region else None, region.key if region else None,
                     region.page if region else None, group, row=row, derived=derived,
                     region_id=region.region_id if region else None)
        self.entities[eid] = ent
        return ent

    def make_attr(self, value, label_tokens, value_tokens, kind, region: Region | None, *, raw=None, row=None,
                  label=None, conf=None, method=None, status="valid", notes=None, bbox=None) -> Attribute:
        vt = [t for t in value_tokens if t.kind != "placeholder"]
        src = [t for t in vt if t.kind == "checkbox"] if kind == "checkbox" else []
        m, c = _method(src or vt or label_tokens, kind)
        page = (vt or label_tokens)[0].page if (vt or label_tokens) else (region.page if region else None)
        vb = bbox or (bbox_of(vt) if vt else None)
        lb = bbox_of(label_tokens) if label_tokens else None
        anchor = vb or lb or [0, 0, 0, 0]
        notes = list(notes or [])
        ocr_words = [t for t in vt if t.source == "ocr" and t.kind == "word"]
        if ocr_words and status == "valid":
            low = min(ocr_words, key=lambda t: t.conf)
            if low.conf < OCR_REVIEW_CONF:
                status = "needs_review"
                notes.append(f"OCR read '{low.text}' with low confidence ({low.conf:.2f}); confirm it against the page")
        return Attribute(
            value=value, field_label=label if label is not None else label_text(" ".join(t.text for t in label_tokens)),
            page=page, bbox=vb, extraction_method=method or m, confidence=conf if conf is not None else c,
            raw=raw, label_bbox=lb, status=status, notes=notes,
            section=region.name if region else None, region_id=region.region_id if region else None,
            row=row, order=(page or 0, anchor[1], anchor[0]),
        )

    def _flag_continued(self, attr: Attribute, vtoks: list[Token]) -> None:
        if any(id(t) in self.continued for t in vtoks):
            attr.notes.append("value continues on the next line; the two lines were joined - confirm")
            if attr.status == "valid":
                attr.status = "needs_review"

    def add_missing(self, kind: str, path: str, label: str, reason: str, entity: str | None = None,
                    region: Region | None = None):
        self.missing.append({
            "kind": kind, "path": path, "label": label, "reason": reason, "entity": entity,
            "section": region.name if region else None, "page": region.hpage if region else None,
            "bbox": region.heading_bbox if region else None,
        })

    def slot(self, path: str, tokens: list[Token], region: Region, label: str):
        for t in tokens:
            if t.field_name:
                self.slots.append({"field": t.field_name, "path": path, "label": label, "section": region.key,
                                   "page": t.page, "rect": t.bbox, "kind": "checkbox" if t.kind == "checkbox" else "text"})

    # ------------------------------------------------------------------ run
    def matched_sections(self) -> set[str]:
        return {r.key for r in self.regions if not r.key.startswith("other:")}

    def run(self) -> "Binder":
        handlers = {"record": self.bind_record, "table": self.bind_table, "checklist": self.bind_checklist,
                    "family": self.bind_family, "yes_no": self.bind_yes_no, "release": self.bind_release,
                    "agreement": self.bind_agreement}
        if not self.scan:
            pat = self.template.by_key["patient_information"]["entity"]
            self.patient = self.new_entity(pat["type"], pat["prefix"], "Patient", None, pat["group"])
        for spec in self.template.sections:
            regions = [r for r in self.regions if r.key == spec["key"]]
            if regions:
                self.sections_seen.append(spec["key"])
            handlers[spec["kind"]](spec, regions)
        return self

    # ------------------------------------------------------------------ record sections
    def _kv_pairs(self, spec, regions, fields=None):
        """(region, line, field spec, label tokens, value tokens) for every label on the
        section's lines.  A value that continues on the next line is extended with it
        (and marked by ``self.continued``) so it is never split or dropped."""
        table = Template.alias_table(fields or spec["fields"])
        for region in regions:
            lines = self.lines(region)
            for k, ln in enumerate(lines):
                below = labels_below(lines, k, table) if not any(t.text.endswith(":") for t in ln.tokens) else []
                for fspec, ltoks, vtoks in below:
                    self.below_labels.add(id(ltoks[0]))
                    yield region, ln, fspec, ltoks, vtoks
                if below:
                    continue
                pairs = _parse_kv_line(ln.tokens, table)
                for n, (fspec, ltoks, vtoks) in enumerate(pairs):
                    if vtoks and not self.scan:
                        right = pairs[n + 1][1][0].x0 - 4 if n + 1 < len(pairs) else region.x1
                        extra = continuation_tokens(lines, k, vtoks, right)
                        if extra:
                            vtoks = vtoks + extra
                            self.continued.update(id(t) for t in extra)
                    yield region, ln, fspec, ltoks, vtoks

    def bind_record(self, spec, regions):
        espec = spec["entity"]
        found: dict[str, Attribute] = {}
        for region, ln, fspec, ltoks, vtoks in self._kv_pairs(spec, regions):
            if fspec is None:
                if vtoks and not self.scan:
                    self.unbound.append({"section": region.name, "label": label_text(" ".join(t.text for t in ltoks)),
                                         "value": clean(" ".join(t.text for t in vtoks)), "page": region.page})
                continue
            key = fspec["key"]
            if key in found:
                continue
            if self.scan:
                self.slot(f"{spec['key']}.{key}", vtoks, region, label_text(" ".join(t.text for t in ltoks)))
                found[key] = None  # type: ignore
                continue
            if any(t.kind == "checkbox" for t in vtoks):
                attr = self._choice_attr(fspec, ltoks, vtoks, region, f"{spec['key']}.{key}")
                if attr:
                    found[key] = attr
                continue
            raw = clean(join_tokens(vtoks))
            if not raw:
                continue
            attr = self._value_attr(fspec, ltoks, vtoks, region, raw)
            found[key] = attr
        if self.scan:
            return None
        if not found and espec["type"] != "Patient":
            return None
        region0 = regions[0] if regions else None
        if espec["type"] == "Patient":
            ent = self.patient
            ent.section, ent.section_key = region0.name if region0 else None, spec["key"]
            ent.page, ent.region_id = (region0.page, region0.region_id) if region0 else (None, None)
        else:
            ent = self.new_entity(espec["type"], espec["prefix"], "", region0, espec["group"])
        ent.attributes.update(found)
        if espec["type"] == "Patient":
            self._derive_names(ent, region0)
            first = ent.attributes.get("first_name")
            last = ent.attributes.get("last_name")
            ent.label = clean(f"{first.value if first else ''} {last.value if last else ''}") or "Patient"
        elif espec["type"] == "InsurancePolicy":
            ent.attributes["policy_type"] = Attribute(
                value=spec.get("policy_type"), field_label=f"section heading '{region0.heading}'",
                page=region0.hpage, bbox=region0.heading_bbox, extraction_method="section_heading", confidence=0.95,
                section=region0.name, region_id=region0.region_id,
                order=(region0.page, region0.heading_bbox[1] - 0.1, region0.heading_bbox[0]))
            company = found.get("insurance_company")
            ent.label = company.value if company else spec.get("policy_type", "")
            ent.extra["policy_type"] = spec.get("policy_type")
            if company:
                self._derive_company(ent, company, region0)
        else:
            nm = found.get("full_name") or found.get("name")
            ent.label = nm.value if nm else TYPE_NAMES.get(espec["type"], espec["type"])
        # required fields
        for f in spec["fields"]:
            if f.get("required") and f["key"] not in ent.attributes:
                self.add_missing("not_provided", f"{spec['key']}.{f['key']}", f.get("label", f["key"]),
                                 "no value found in the source document", ent.id, region0)
        return ent

    def _value_attr(self, fspec, ltoks, vtoks, region, raw) -> Attribute:
        """A typed value; a format printed in the label ('(MM/DD/YYYY)') decides its reading."""
        vtype = fspec.get("type", "text")
        label = " ".join(t.text for t in ltoks)
        hint = date_hint(label) if vtype == "date" else None
        order = hint if hint in ("mdy", "dmy") else self.parse_order
        value, ok = normalise(raw, vtype, order)
        attr = self.make_attr(value, ltoks, vtoks, "key_value", region, raw=raw)
        _type_notes(attr, raw, value, ok, vtype, hint or self.date_order)
        if hint and _hint_conflict(raw, hint):
            attr.notes.append(f"'{raw}' does not follow the format printed in the label ({label_text(label)})")
            if attr.status == "valid":
                attr.status = "needs_review"
        self._flag_continued(attr, vtoks)
        return attr

    def _choice_attr(self, fspec, ltoks, vtoks, region, path) -> Attribute | None:
        label = label_text(" ".join(t.text for t in ltoks))
        text, toks, problems = choice_value(vtoks)
        if text is None:
            if not problems or problems[0].startswith("none of"):
                self.add_missing("not_answered", path, label, problems[0] if problems else "no option ticked",
                                 None, region)
            return None
        vtype = fspec.get("type", "text")
        value, ok = normalise(text, vtype, self.parse_order)
        attr = self.make_attr(value, ltoks, toks, "checkbox", region, raw=text, label=label)
        _type_notes(attr, text, value, ok, vtype, self.date_order)
        if problems:
            attr.status = "needs_review"
            attr.notes.extend(problems)
        return attr

    def _derive_names(self, ent: Entity, region: Region | None):
        full = ent.attributes.get("full_name")
        if full and ("first_name" not in ent.attributes or "last_name" not in ent.attributes):
            first, last = split_person_name(full.raw or str(full.value), name_hint(full.field_label or ""))
            line_tokens = self._tokens_in_bbox(full.page, full.bbox)
            middle = middle_initial(full.raw or str(full.value), name_hint(full.field_label or ""))
            for key, part in (("first_name", first), ("last_name", last), ("middle_name", middle)):
                if part and key not in ent.attributes:
                    toks = [t for t in line_tokens if t.text.strip(",.") == part] or line_tokens
                    ent.attributes[key] = Attribute(
                        value=part, field_label=full.field_label, page=full.page, bbox=bbox_of(toks) if toks else full.bbox,
                        label_bbox=full.label_bbox, extraction_method="derived_split",
                        confidence=round(min(0.85, full.confidence - 0.07), 2),
                        section=full.section, region_id=full.region_id, raw=full.raw,
                        notes=[f"derived by splitting the printed name '{full.raw}'"],
                        order=(99, 0, {"first_name": 1, "last_name": 2}.get(key, 3)))
        if not full and "first_name" in ent.attributes and "last_name" in ent.attributes:
            f, l = ent.attributes["first_name"], ent.attributes["last_name"]
            if f.page == l.page:
                bb = [min(f.bbox[0], l.bbox[0]), min(f.bbox[1], l.bbox[1]), max(f.bbox[2], l.bbox[2]), max(f.bbox[3], l.bbox[3])]
            else:
                bb = f.bbox
            ent.attributes["full_name"] = Attribute(
                value=f"{f.value} {l.value}", field_label=f"{f.field_label} + {l.field_label}", page=f.page, bbox=bb,
                extraction_method="derived_join", confidence=round(min(f.confidence, l.confidence) - 0.05, 2),
                section=f.section, region_id=f.region_id, notes=["joined from first and last name"],
                order=(99, 0, 0))

    def _tokens_in_bbox(self, page: int | None, bbox) -> list[Token]:
        if not page or not bbox:
            return []
        pd = self.pages[page - 1]
        return [t for t in pd.tokens if t.kind == "word" and bbox[0] - 0.5 <= t.cx <= bbox[2] + 0.5
                and bbox[1] - 0.5 <= t.cy <= bbox[3] + 0.5]

    def _derive_company(self, policy: Entity, company: Attribute, region: Region):
        key = name_key(company.value) or str(company.value).lower()
        for e in self.entities.values():
            if e.type == "InsuranceCompany" and e.extra.get("_key") == key:
                policy.links["insurance_company_id"] = e.id
                return
        ent = self.new_entity("InsuranceCompany", "INSCO", company.value, region, "Insurance companies", derived=True)
        ent.extra["_key"] = key
        ent.attributes["name"] = Attribute(**{**company.__dict__, "notes": ["derived from the policy's carrier field"]})
        policy.links["insurance_company_id"] = ent.id

    # ------------------------------------------------------------------ tables
    def _tables(self, spec, regions) -> list[tuple[Region, Table]]:
        """The section's table in every region, including its continuation on the next
        page when the header is not repeated there."""
        out = []
        prev = None
        for region in regions:
            lines = self.lines(region)
            t = find_table(lines, spec["columns"], region)
            if t is None and prev is not None and region.continued:
                t = continue_table(lines, prev)
            if t:
                out.append((region, t))
                prev = t
        return out

    def bind_table(self, spec, regions):
        espec = spec["entity"]
        rowno = 0
        made = []
        for region, table in self._tables(spec, regions):
            for row in table.rows:
                rowno += 1
                if self.scan:
                    for cspec, _, _, htoks in table.columns:
                        cell = row.cells[cspec["key"]]
                        self.slot(f"{spec['key']}[{rowno}].{cspec['key']}", cell.all_tokens, region,
                                  label_text(" ".join(t.text for t in htoks)))
                    continue
                ent = self._row_entity(spec, espec, region, table, row, rowno)
                if ent:
                    made.append(ent)
        if not made and not self.scan and spec["key"] not in self.none_answers and spec.get("inline_list", True):
            made = self._inline_list(spec, regions)
        none = self.none_answers.get(spec["key"])
        if none is not None and made:
            none.status = "needs_review"
            none.notes.append(f"the table also lists {len(made)} entr{'y' if len(made) == 1 else 'ies'} "
                              f"({', '.join(e.label for e in made[:3])}); the two contradict each other")
        if not self.scan:
            if espec["type"] == "Medication":
                self._derive_doctors(made)
            elif espec["type"] == "Surgery":
                self._derive_hospitals(made)
        return made

    def _row_entity(self, spec, espec, region, table, row, rowno) -> Entity | None:
        cols = {cspec["key"]: (cspec, htoks) for cspec, _, _, htoks in table.columns}
        key_col = next(c for c in spec["columns"] if c.get("row_key"))
        key_cell = row.cells.get(key_col["key"])
        if not key_cell or not key_cell.text:
            return None
        others = [c for k, c in row.cells.items() if k != key_col["key"] and c.text]
        nothing = none_answer(key_cell.text)
        if nothing and not others and not self.scan:
            # "NKDA" / "None" written in the table: the list is empty, which is itself an answer
            akey = f"{spec['key']}_status"
            if akey not in self.patient.attributes:
                attr = self.make_attr(nothing, cols[key_col["key"]][1], key_cell.all_tokens, "table", region,
                                      raw=key_cell.text, label=f"{spec['name']}")
                attr.notes.append(f"'{key_cell.text}' written in the {spec['name']} table: none reported")
                self.patient.attributes[akey] = attr
                self.none_answers[spec["key"]] = attr
            return None
        ent = self.new_entity(espec["type"], espec["prefix"], key_cell.text, region, espec["group"], row=rowno)
        ent.extra["row_bbox"] = bbox_of([t for ln in row.lines for t in ln.tokens])
        for ckey, (cspec, htoks) in cols.items():
            cell: Cell = row.cells[ckey]
            raw = cell.text
            if not raw:
                continue
            if cspec.get("combined"):
                self._combined_cell(ent, cspec, htoks, cell, region, rowno, raw)
                continue
            if cspec.get("unknown"):
                attr = self.make_attr(raw, htoks, cell.all_tokens, "table", region, raw=raw, row=rowno)
                attr.notes.append(f"column '{cspec['label']}' is not part of the template; kept as printed")
                ent.attributes[ckey] = attr
                continue
            value, ok = normalise(raw, cspec.get("type", "text"), self.parse_order)
            wrapped = ckey in row.wrapped_columns
            attr = self.make_attr(value, htoks, cell.all_tokens, "table", region, raw=raw, row=rowno)
            _type_notes(attr, raw, value, ok, cspec.get("type", "text"), self.date_order)
            if wrapped:
                attr.confidence = WRAPPED_CONF
                attr.status = "needs_review"
                attr.notes.append(WRAP_NOTE)
            ent.attributes[ckey] = attr
        if row.wrapped:
            ent.extra["row_wrapped"] = True
            ent.extra["wrapped_columns"] = list(row.wrapped_columns)
        missing_cols = [c for c in spec["columns"] if c.get("required") and c["key"] not in ent.attributes]
        if missing_cols:
            labels = ", ".join(c.get("label", c["key"]) for c in missing_cols)
            self.add_missing("incomplete_record", ent.id, labels, f"record {rowno} has no value for: {labels}", ent.id, region)
        return ent

    # ------------------------------------------------------------------ lists written as text
    def _inline_list(self, spec, regions) -> list[Entity]:
        """A table section answered as text: "Allergies: Penicillin (hives), Sulfa (rash)",
        "Medications: Lisinopril 10 mg daily; Metformin 500 mg twice daily".  Read from a
        label that names the section (anywhere on the form) or from a list prompt inside
        the section.  Lines without a label under the heading are read too, but only for
        review: free text may be instructions rather than an answer."""
        aliases = [norm_tokens(a) for a in [spec["name"], *spec.get("aliases", [])]]
        found: list[tuple[Region, list[Token], list[Token], bool]] = []
        seen: set[int] = set()
        own_regions = {r.region_id for r in regions}

        def names_section(label_toks) -> bool:
            words = norm_tokens(" ".join(t.text for t in label_toks))
            return any(words[i:i + len(a)] == a for a in aliases for i in range(len(words) - len(a) + 1))

        for region in self.regions:
            own = region.region_id in own_regions
            if not own and region.key.startswith("other:"):
                continue
            lines = self.lines(region)
            for k, ln in enumerate(lines):
                if id(ln) in seen:
                    continue
                pairs = _parse_kv_line(ln.tokens, [])
                for n, (_, ltoks, vtoks) in enumerate(pairs):
                    words = [t for t in vtoks if t.kind == "word"]
                    if not words or any(t.kind == "checkbox" for t in vtoks) or any(id(t) in self.bound_ids for t in words):
                        continue
                    if names_section(ltoks) or (own and _LIST_PROMPT.search(" ".join(t.text for t in ltoks))):
                        right = pairs[n + 1][1][0].x0 - 4 if n + 1 < len(pairs) else region.x1
                        extra = [t for t in continuation_tokens(lines, k, words, right) if t.kind == "word"]
                        found.append((region, ltoks, words + extra, True))
                        seen.add(id(ln))
                if own and not pairs and id(ln) not in seen:
                    words = [t for t in ln.tokens if t.kind == "word"]
                    text = " ".join(t.text for t in words)
                    if words and not _INSTRUCTION.search(text) and not text.rstrip().endswith((".", ":", "?")):
                        found.append((region, [], words, False))
                        seen.add(id(ln))
        made: list[Entity] = []
        espec = spec["entity"]
        key_col = next(c for c in spec["columns"] if c.get("row_key"))
        for region, ltoks, words, labelled in found:
            raw_all = clean(join_tokens(words))
            nothing = none_answer(raw_all)
            if nothing:
                akey = f"{spec['key']}_status"
                if akey not in self.patient.attributes:
                    attr = self.make_attr(nothing, ltoks, words, "key_value", region, raw=raw_all, label=spec["name"])
                    attr.notes.append(f"'{raw_all}' written for {spec['name']}: none reported")
                    self.patient.attributes[akey] = attr
                    self.none_answers[spec["key"]] = attr
                continue
            for item_toks in _list_items(words):
                text = clean(join_tokens(item_toks)).strip(" ,;.")
                parts, ok = _parse_list_item(espec["type"], text)
                if not parts or not parts.get(key_col["key"]):
                    continue
                rowno = len(made) + 1
                ent = self.new_entity(espec["type"], espec["prefix"], parts[key_col["key"]], region, espec["group"],
                                      row=rowno)
                ent.extra["row_bbox"] = bbox_of(item_toks)
                for key, value in parts.items():
                    if not value:
                        continue
                    cspec = next((c for c in spec["columns"] if c["key"] == key), {"type": "text"})
                    ptoks = _tokens_for(item_toks, value) or item_toks
                    norm_value, vok = normalise(value, cspec.get("type", "text"), self.parse_order)
                    attr = self.make_attr(norm_value, ltoks, ptoks, "key_value", region, raw=value, row=rowno,
                                          label=label_text(" ".join(t.text for t in ltoks)) if ltoks else spec["name"])
                    attr.extraction_method = attr.extraction_method.replace("key_value", "list")
                    _type_notes(attr, value, norm_value, vok, cspec.get("type", "text"), self.date_order)
                    attr.notes.append(f"item {rowno} of the list '{text if len(text) < 60 else text[:57] + '...'}'")
                    if not ok:
                        attr.status = "needs_review"
                        attr.notes.append(f"'{text}' could not be split into its parts with confidence")
                    if not labelled:
                        attr.status = "needs_review"
                        attr.notes.append(f"read from text under the '{region.heading}' heading, which has no label; "
                                          "confirm it is an answer and not an instruction")
                    if any(id(t) in self.continued for t in ptoks):
                        attr.status = "needs_review"
                    ent.attributes[key] = attr
                self.bound_ids.update(id(t) for t in item_toks)
                made.append(ent)
                missing_cols = [c for c in spec["columns"] if c.get("required") and c["key"] not in ent.attributes]
                if missing_cols:
                    labels = ", ".join(c.get("label", c["key"]) for c in missing_cols)
                    self.add_missing("incomplete_record", ent.id, labels,
                                     f"list item {rowno} ('{text}') gives no {labels}", ent.id, region)
        return made

    def _combined_cell(self, ent: Entity, cspec, htoks, cell: Cell, region, rowno, raw):
        """One printed column holding two fields ("Dose/Frequency"): split the value."""
        a, b = cspec["combined"]
        toks = cell.all_tokens
        if {a["key"], b["key"]} == {"dosage", "frequency"}:
            dose, freq, ok = split_dose_frequency(raw)
            parts = [("dosage", dose), ("frequency", freq)]
        else:
            pieces = [x.strip() for x in re.split(r"\s*[/,;]\s*", raw, maxsplit=1)]
            ok = len(pieces) == 2 and all(pieces)
            parts = list(zip((a["key"], b["key"]), pieces + [None] * (2 - len(pieces))))
        used = 0
        for key, text in parts:
            if not text:
                continue
            n = len(text.split())
            ptoks = toks[used:used + n] if used + n <= len(toks) else toks
            used += n
            spec = a if key == a["key"] else b
            value, vok = normalise(text, spec.get("type", "text"), self.parse_order)
            attr = self.make_attr(value, htoks, ptoks, "table", region, raw=text, row=rowno)
            _type_notes(attr, text, value, vok, spec.get("type", "text"), self.date_order)
            attr.notes.append(f"split from the combined '{cspec['label']}' column ('{raw}')")
            if not ok:
                attr.status = "needs_review"
                attr.notes.append(f"'{raw}' could not be split into {a.get('label', a['key'])} and "
                                  f"{b.get('label', b['key'])} with confidence")
            if cell.continued:
                attr.status = "needs_review"
                attr.notes.append(WRAP_NOTE)
            ent.attributes[key] = attr

    def _derive_doctors(self, meds: list[Entity]):
        index: dict[str, Entity] = {}
        for med in meds:
            a = med.attributes.get("prescribing_doctor")
            if not a:
                continue
            key = name_key(a.value)
            doc = index.get(key)
            if not doc:
                region = next(r for r in self.regions if r.region_id == a.region_id)
                doc = self.new_entity("Doctor", "DR", a.value, region, "Doctors", derived=True)
                doc.attributes["name"] = Attribute(**{**a.__dict__, "notes": [], "row": None, "status": "valid",
                                                       "confidence": max(a.confidence, BASE_CONF["table"]) if a.status == "valid" else a.confidence})
                index[key] = doc
            med.links["prescribing_doctor_id"] = doc.id

    def _derive_hospitals(self, surgeries: list[Entity]):
        index: dict[str, Entity] = {}
        for s in surgeries:
            a = s.attributes.get("facility")
            if not a:
                continue
            key = name_key(a.value)
            h = index.get(key)
            if not h:
                region = next(r for r in self.regions if r.region_id == a.region_id)
                h = self.new_entity("Hospital", "HOSP", a.value, region, "Hospitals", derived=True)
                h.attributes["name"] = Attribute(**{**a.__dict__, "notes": [], "row": None})
                index[key] = h
            s.links["facility_id"] = h.id

    # ------------------------------------------------------------------ checklists
    def bind_checklist(self, spec, regions):
        espec = spec["entity"]
        opt_table = Template.alias_table(spec["options"])
        other_aliases = [norm_tokens(a) for a in spec.get("other_aliases", ["other"])]
        out = []
        for region in regions:
            for ln in self.lines(region):
                toks = ln.tokens
                if any(t.kind == "checkbox" for t in toks):
                    _, opts, trailing = checkbox_options(toks)
                    for t, lab in opts:
                        text = clean(" ".join(x.text for x in lab))
                        m = match_aliases(lab, 0, opt_table) if lab else None
                        if self.scan:
                            if m:
                                self.slot(f"{spec['key']}.options.{m[1]['key']}", [t], region, text)
                        elif t.checked and text:
                            ent = self.new_entity(espec["type"], espec["prefix"], text, region, espec["group"])
                            ent.attributes["name"] = self.make_attr(text, lab, [t] + lab, "checkbox", region, label=text)
                            ent.extra["owner_hint"] = "patient"
                            ent.extra["option"] = m[1]["key"] if m else None
                            out.append(ent)
                    toks = trailing
                i = 0
                while i < len(toks):
                    t = toks[i]
                    # "Other: ..." free text
                    w = norm_tokens(t.text)
                    hit = None
                    for alias in other_aliases:
                        n = len(alias)
                        cand = [x for tok in toks[i:i + n] for x in norm_tokens(tok.text)]
                        if cand == alias and toks[i + n - 1].text.endswith(":"):
                            hit = n
                            break
                    if hit and w:
                        ltoks = toks[i:i + hit]
                        j = i + hit
                        vals = []
                        while j < len(toks) and toks[j].kind != "checkbox":
                            vals.append(toks[j])
                            j += 1
                        if self.scan:
                            self.slot(f"{spec['key']}.other", vals, region, "Other")
                        else:
                            for piece, ptoks in _split_tokens(vals):
                                ent = self.new_entity(espec["type"], espec["prefix"], piece, region, espec["group"])
                                ent.attributes["name"] = self.make_attr(piece, ltoks, ptoks, "key_value", region)
                                ent.extra["owner_hint"] = "patient"
                                ent.extra["option"] = "other"
                                out.append(ent)
                        i = j
                        continue
                    i += 1
        return out

    # ------------------------------------------------------------------ family history
    def bind_family(self, spec, regions):
        espec = spec["entity"]
        relations = Template.alias_table([{"key": r, "label": r} for r in spec["relations"]])
        members: list[Entity] = []
        tables = self._tables(spec, regions)
        if tables:
            for region, table in tables:
                for row in table.rows:
                    rel_cell = row.cells.get("relation")
                    relation = norm(rel_cell.text) if rel_cell else ""
                    if self.scan:
                        for cspec, _, _, htoks in table.columns:
                            if cspec["key"] == "relation":
                                continue
                            self.slot(f"{spec['key']}[{relation}].{cspec['key']}", row.cells[cspec["key"]].all_tokens,
                                      region, label_text(" ".join(t.text for t in htoks)))
                        continue
                    others = [k for k, c in row.cells.items() if k != "relation" and c.text]
                    if not relation or not others:
                        continue
                    label = rel_cell.text
                    ent = self.new_entity(espec["type"], espec["prefix"], label, region, espec["group"])
                    ent.attributes["relation"] = self.make_attr(relation, [], rel_cell.tokens, "table", region, label=label)
                    ent.attributes["relation"].order = (region.page, min(t.top for t in rel_cell.tokens) - 5, 0)
                    for cspec, _, _, htoks in table.columns:
                        k = cspec["key"]
                        if k == "relation" or not row.cells[k].text:
                            continue
                        cell = row.cells[k]
                        value, _ = normalise(cell.text, cspec.get("type", "text"), self.parse_order)
                        ent.attributes[k] = self.make_attr(value, htoks, cell.all_tokens, "table", region, raw=cell.text)
                    self._family_conditions(ent, ent.attributes.get("conditions"), region,
                                            row.cells["conditions"].all_tokens if "conditions" in row.cells else [])
                    members.append(ent)
            return members
        for region in regions:
            for ln in self.lines(region):
                toks = ln.tokens
                m = match_aliases(toks, 0, relations)
                if not m:
                    continue
                consumed, rspec = m
                if not toks[consumed - 1].text.endswith(":"):
                    continue
                ltoks, vtoks = toks[:consumed], [t for t in toks[consumed:] if t.kind == "word"]
                if self.scan or not vtoks:
                    continue
                label = label_text(" ".join(t.text for t in ltoks))
                ent = self.new_entity(espec["type"], espec["prefix"], label, region, espec["group"])
                parsed = _parse_family_text(vtoks)
                ent.attributes["relation"] = self.make_attr(rspec["key"], ltoks, ltoks, "family", region, label=label)
                for k in ("living_status", "age", "conditions"):
                    if k in parsed:
                        value, ptoks = parsed[k]
                        ent.attributes[k] = self.make_attr(value, ltoks, ptoks, "family", region, label=label,
                                                           raw=clean(" ".join(t.text for t in ptoks)))
                self._family_conditions(ent, ent.attributes.get("conditions"), region,
                                        parsed.get("conditions", (None, []))[1], ltoks)
                members.append(ent)
        return members

    def _family_conditions(self, member: Entity, attr: Attribute | None, region: Region, tokens: list[Token],
                           label_tokens: list[Token] | None = None):
        if not attr or not attr.value:
            return
        names = attr.value if isinstance(attr.value, list) else split_list(str(attr.value))
        pieces = dict((p, pt) for p, pt in _split_tokens(tokens))
        ids = []
        for name in names:
            ptoks = pieces.get(name) or tokens
            ent = self.new_entity("Condition", "COND", name, region, "Conditions")
            ent.attributes["name"] = self.make_attr(name, label_tokens or [], ptoks,
                                                    "family" if label_tokens else "table", region,
                                                    label=member.label if label_tokens else attr.field_label,
                                                    conf=attr.confidence, method=attr.extraction_method)
            ent.extra["owner_hint"] = member.id
            ids.append(ent.id)
        member.links["condition_ids"] = ids  # type: ignore[assignment]

    # ------------------------------------------------------------------ yes / no questions
    def _yes_no_line(self, toks: list[Token]):
        question, opts, trailing = checkbox_options(toks)
        if not opts:
            return None
        boxes = [(b, lab[0] if lab else None) for b, lab in opts]
        yes = [(b, l) for b, l in boxes if l is not None and norm(l.text) in ("yes", "y")]
        no = [(b, l) for b, l in boxes if l is not None and norm(l.text) in ("no", "n")]
        if not yes and not no:
            return None
        # an answer printed without a readable box, or a box without a readable answer,
        # means part of the line was not seen: the decision cannot be trusted
        attached = {id(l) for _, l in boxes if l is not None}
        loose = [t for t in question + trailing if norm(t.text) in ("yes", "no") and id(t) not in attached]
        if loose or any(l is None for _, l in boxes):
            self._unclear_lines.add(id(question[0]) if question else id(boxes[0][0]))
        return question, yes, no, boxes

    @staticmethod
    def _decide(yes, no):
        y = any(b.checked for b, _ in yes)
        n = any(b.checked for b, _ in no)
        marks = "  ".join(f"{b.text} {l.text}" for b, l in yes + no)
        if y and not n:
            return "yes", None
        if n and not y:
            return "no", None
        if y and n:
            return None, f"could not resolve a single yes/no answer from '{marks.replace('  ', ' ')}'"
        return None, "no answer was marked"

    def _consent(self, key, label, question, yes, no, region) -> Entity:
        decision, problem = self._decide(yes, no)
        anchor = id(question[0]) if question else id((yes + no)[0][0]) if (yes + no) else None
        if problem is None and anchor in self._unclear_lines:
            problem = "part of this answer line could not be read (a box or its Yes/No label is missing)"
        chosen = [(b, l) for b, l in yes + no if b.checked] or (yes + no)
        vt = [x for b, l in chosen for x in (b, l)]
        ent = self.new_entity("Consent", "CONS", label, region, "Consents")
        qlabel = label_text(" ".join(t.text for t in question)) or label
        ent.attributes["topic"] = self.make_attr(label, question, question, "key_value", region, label=qlabel)
        attr = self.make_attr(decision, question, vt, "checkbox", region, label=qlabel,
                              raw=" ".join(f"{b.text} {l.text}" for b, l in yes + no))
        if problem:
            attr.status = "needs_review"
            attr.notes.append(problem)
        ent.attributes["decision"] = attr
        ent.extra["consent_key"] = key
        ent.extra["question"] = qlabel
        return ent

    def bind_yes_no(self, spec, regions):
        out = []
        q_table = Template.alias_table(spec["questions"])
        done = set()
        for region in regions:
            for ln in self.lines(region):
                parsed = self._yes_no_line(ln.tokens)
                if not parsed:
                    continue
                question, yes, no, _ = parsed
                qspec = None
                for i in range(len(question)):
                    m = match_aliases(question, i, q_table)
                    if m:
                        qspec = m[1]
                        break
                if not qspec or qspec["key"] in done:
                    continue
                done.add(qspec["key"])
                if self.scan:
                    qtext = label_text(" ".join(t.text for t in question))
                    for b, _ in yes:
                        self.slot(f"{spec['key']}.{qspec['key']}.yes", [b], region, qtext)
                    for b, _ in no:
                        self.slot(f"{spec['key']}.{qspec['key']}.no", [b], region, qtext)
                    continue
                out.append(self._consent(qspec["key"], qspec["label"], question, yes, no, region))
        return out

    # ------------------------------------------------------------------ release of information
    def bind_release(self, spec, regions):
        cspec = spec["consent"]
        aliases = [norm(a) for a in cspec["aliases"]]
        consent = None
        for region in regions:
            for ln in self.lines(region):
                parsed = self._yes_no_line(ln.tokens)
                if not parsed:
                    continue
                question, yes, no, _ = parsed
                qn = norm(" ".join(t.text for t in question))
                if not any(a in qn for a in aliases):
                    continue
                if self.scan:
                    for b, _ in yes:
                        self.slot(f"{spec['key']}.decision.yes", [b], region, "release")
                    for b, _ in no:
                        self.slot(f"{spec['key']}.decision.no", [b], region, "release")
                else:
                    consent = self._consent(cspec["key"], cspec["label"], question, yes, no, region)
                break
            if consent:
                break
        espec = spec["entity"]
        people = []
        rowno = 0
        for region, table in self._tables(spec, regions):
            for row in table.rows:
                rowno += 1
                if self.scan:
                    for c, _, _, htoks in table.columns:
                        self.slot(f"{spec['key']}[{rowno}].{c['key']}", row.cells[c["key"]].all_tokens, region,
                                  label_text(" ".join(t.text for t in htoks)))
                    continue
                ent = self._row_entity(spec, espec, region, table, row, rowno)
                if ent:
                    people.append(ent)
        if consent:
            consent.links["authorized_person_ids"] = [p.id for p in people]  # type: ignore[assignment]
        return people

    # ------------------------------------------------------------------ agreements
    def bind_agreement(self, spec, regions):
        if not regions:
            return None
        espec = spec["entity"]
        region0 = regions[0]
        found: dict[str, tuple[Attribute, list[Token]]] = {}
        sig_labels = None
        for region, ln, fspec, ltoks, vtoks in self._kv_pairs(spec, regions):
            if fspec is None or fspec["key"] in found:
                continue
            key = fspec["key"]
            if not self.scan:
                vtoks = [t for t in vtoks if t.kind != "checkbox"]
            if self.scan:
                self.slot(f"{spec['key']}.{key}", vtoks, region, label_text(" ".join(t.text for t in ltoks)))
                found[key] = (None, ltoks)  # type: ignore
                continue
            raw = clean(join_tokens([t for t in vtoks if t.kind == "word"]))
            if key == "signature":
                sig_labels = (region, ln, ltoks, vtoks)
                if raw:
                    ocr = any(t.source == "ocr" for t in vtoks)
                    words = [t for t in vtoks if t.kind == "word"]
                    mean_conf = sum(t.conf for t in words) / max(1, len(words))
                    # handwriting read by OCR comes out as short, low-confidence fragments
                    if ocr and not raw.lower().startswith("/s/") and (
                            len(re.findall(r"[A-Za-z]{2,}", raw)) < 2 or mean_conf < 0.7):
                        attr = self.make_attr("ink signature", ltoks, vtoks, "key_value", region, raw=raw)
                        attr.extraction_method = "ocr_signature"
                        attr.status = "valid"  # the ink is the evidence; the letters OCR saw in it are not
                        attr.notes = [f"handwriting on the signature line (OCR saw it as '{raw}')"]
                    else:
                        attr = self.make_attr(raw, ltoks, vtoks, "key_value", region, raw=raw)
                    found[key] = (attr, ltoks)
                continue
            if not raw:
                continue
            value, ok = normalise(raw, fspec.get("type", "text"), self.parse_order)
            attr = self.make_attr(value, ltoks, vtoks, "key_value", region, raw=raw)
            _type_notes(attr, raw, value, ok, fspec.get("type", "text"), self.date_order)
            self._flag_continued(attr, vtoks)
            found[key] = (attr, ltoks)
        if self.scan:
            return None
        ent = self.new_entity(espec["type"], espec["prefix"], spec["name"], region0, espec["group"])
        ent.extra["agreement_key"] = spec["key"]
        ent.attributes["title"] = Attribute(
            value=spec["name"], field_label=region0.heading, page=region0.hpage, bbox=region0.heading_bbox,
            extraction_method="section_heading", confidence=0.95, section=region0.name, region_id=region0.region_id,
            order=(region0.page, region0.heading_bbox[1], 0))
        for k, (attr, _) in found.items():
            ent.attributes[k] = attr
        # drawn signature: ink on the signature line, right of its label, inside this section
        if "signature" not in ent.attributes and sig_labels:
            region, ln, ltoks, vtoks = sig_labels
            label_end = max(t.x1 for t in ltoks)
            nxt = [t.x0 for t in ln.tokens if t.x0 > label_end + 4 and t.kind == "word"]
            limit = min(nxt) if nxt else region.x1
            below = id(ltoks[0]) in self.below_labels

            def on_line(m) -> bool:
                if below:  # ink above the label, over its column
                    return (ln.top - 40 <= m.bottom <= ln.top + 3 and m.x1 >= ltoks[0].x0 - 12
                            and m.x0 < (min(nxt) if nxt else region.x1))
                return abs(m.cy - ln.cy) < 14 and m.x0 >= label_end - 4 and m.x0 < limit

            for m in self.marks:
                if m.page == region.page and region.contains(m) and on_line(m):
                    ent.attributes["signature"] = Attribute(
                        value="ink signature", field_label=label_text(" ".join(t.text for t in ltoks)), page=m.page,
                        bbox=m.bbox, label_bbox=bbox_of(ltoks), extraction_method="layout_signature",
                        confidence=BASE_CONF["signature"], section=region.name, region_id=region.region_id,
                        order=(m.page, m.top, m.x0))
                    break
        if "signature" not in ent.attributes:
            self.add_missing("not_signed", f"{spec['key']}.signature", "Signature",
                             "no signature found on the signature line", ent.id, region0)
        for f in spec["fields"]:
            if f.get("required") and f["key"] not in ent.attributes:
                self.add_missing("not_provided", f"{spec['key']}.{f['key']}", f.get("label", f["key"]),
                                 "no value found in the source document", ent.id, region0)
        return ent


# --------------------------------------------------------------------------- free-text helpers
def _type_notes(attr: Attribute, raw: str, value, ok: bool, vtype: str, date_order: str | None = "mdy") -> None:
    """Explain corrections and doubtful formats.  A value that does not fit its field's
    type, a value OCR had to correct, or a date whose day/month order cannot be told
    apart goes to review instead of being trusted."""
    ocr = attr.extraction_method.startswith("ocr")
    if vtype in ("dosage", "year") and isinstance(value, str) and value.replace(" ", "") != raw.replace(" ", ""):
        attr.notes.append(f"read as '{raw}', corrected to '{value}'")
        if ocr and attr.status == "valid":
            attr.status = "needs_review"
    if not ok and vtype not in ("text", "person_name", "lower", "list"):  # marital/sex do say when unknown
        kind = {"marital": "marital status", "sex": "sex or gender"}.get(vtype, vtype.replace("_", " "))
        attr.notes.append(f"value '{raw}' does not look like a {kind}")
        if attr.status == "valid":
            attr.status = "needs_review"
    if vtype == "date" and ok and date_order not in ("mdy", "dmy") and is_ambiguous_date(raw):
        attr.notes.append(f"'{raw}' could be read day-first or month-first and nothing else on the document "
                          f"settles it; read as {value}")
        if attr.status == "valid":
            attr.status = "needs_review"


def _split_tokens(tokens: list[Token]) -> list[tuple[str, list[Token]]]:
    """Split a comma separated run of tokens into (text, tokens) pieces."""
    pieces: list[tuple[str, list[Token]]] = []
    cur: list[Token] = []
    for t in tokens:
        if t.kind != "word":
            continue
        txt = t.text
        if norm(txt) == "and" and cur:
            pieces.append((clean(" ".join(x.text for x in cur)), cur))
            cur = []
            continue
        cur.append(t)
        if txt.endswith((",", ";")):
            pieces.append((clean(" ".join(x.text for x in cur)), cur))
            cur = []
    if cur:
        pieces.append((clean(" ".join(x.text for x in cur)), cur))
    # a single form-field token can hold a whole list
    out = []
    for text, toks in pieces:
        if len(toks) == 1 and ("," in text or ";" in text):
            for p in split_list(text):
                out.append((p, toks))
        elif text:
            out.append((text, toks))
    return out


_STATUS = {"living": "living", "alive": "living", "deceased": "deceased", "died": "deceased", "dead": "deceased",
           "passed": "deceased", "unknown": "unknown"}


def _parse_family_text(tokens: list[Token]) -> dict:
    """'Living, age 66 - Type 2 diabetes, hypertension' -> status, age, conditions (with their tokens)."""
    out: dict = {}
    words = [norm(t.text) for t in tokens]
    used = set()
    for i, w in enumerate(words):
        if w in _STATUS and "living_status" not in out:
            out["living_status"] = (_STATUS[w], [tokens[i]])
            used.add(i)
            if w == "passed" and i + 1 < len(words) and words[i + 1] == "away":
                used.add(i + 1)
    for i, w in enumerate(words):
        if w in ("age", "aged") and i + 1 < len(words) and words[i + 1].isdigit():
            out["age"] = (words[i + 1], tokens[i:i + 2])
            used.update({i, i + 1})
            break
        if w.isdigit() and i + 1 < len(words) and words[i + 1] in ("years", "yrs", "yo", "y o"):
            out["age"] = (w, tokens[i:i + 2])
            used.update({i, i + 1})
            break
    sep = next((i for i, t in enumerate(tokens) if t.text in ("-", "–", "—", ";") or t.text.endswith(";")), None)
    if sep is not None:
        rest = tokens[sep + 1:] if tokens[sep].text in ("-", "–", "—", ";") else tokens[sep + 1:]
    else:
        rest = [t for i, t in enumerate(tokens) if i not in used and norm(t.text)]
        if rest and all(norm(t.text) in ("none", "n a", "na") for t in rest):
            rest = []
    rest = [t for t in rest if norm(t.text)]
    if rest:
        pieces = _split_tokens(rest)
        if pieces:
            out["conditions"] = ([p for p, _ in pieces], rest)
    return out


def bind(pages: list[PageData], template: Template, scan: bool = False) -> Binder:
    return Binder(pages, template, scan=scan).run()
