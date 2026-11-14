"""Stage 3 - Bind.

A value may only join an entity if it was found inside that entity's section
region, and - for tables - on the same table row.  Nothing is bound because it
happens to be *near* something else on the page.
"""
from __future__ import annotations

import re
from collections import defaultdict

from .layout import (Cell, Table, bbox_of, build_lines, build_regions, find_table, join_tokens, match_aliases,
                     region_lines)
from .models import Attribute, Entity, Line, PageData, Region, Token
from .normalize import clean, label_text, name_key, normalise, split_list, split_person_name
from .template import Template, norm, norm_tokens

TYPE_NAMES = {
    "Patient": "Patient", "Spouse": "Spouse", "EmergencyContact": "Emergency contact",
    "InsurancePolicy": "Insurance policy", "InsuranceCompany": "Insurance company", "Medication": "Medication",
    "Doctor": "Doctor", "Allergy": "Allergy", "Condition": "Condition", "Surgery": "Surgery", "Hospital": "Hospital",
    "FamilyMember": "Family member", "Consent": "Consent", "AuthorizedPerson": "Authorized person",
    "Agreement": "Agreement",
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


def _parse_kv_line(tokens: list[Token], table) -> list[tuple[dict | None, list[Token], list[Token]]]:
    """Split one line into (field spec | None, label tokens, value tokens) triples."""
    labels: list[tuple[int, int, dict | None]] = []
    n = len(tokens)
    i = 0
    while i < n:
        t = tokens[i]
        if t.kind == "word":
            m = match_aliases(tokens, i, table)
            if m:
                consumed, spec = m
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
            if t.text.endswith(":") and len(t.text) > 1 and not re.search(r"\d:\d", t.text):
                start = i
                floor = labels[-1][1] if labels else 0
                while (start - 1 >= floor and i - start < 4 and tokens[start - 1].kind == "word"
                       and not tokens[start - 1].text.endswith(":") and tokens[start].x0 - tokens[start - 1].x1 < 5):
                    start -= 1
                # never steal the last word of a value that is directly attached
                if labels and start == floor:
                    start = i
                labels.append((start, i + 1, None))
        i += 1
    out = []
    for k, (s, e, spec) in enumerate(labels):
        nxt_start = labels[k + 1][0] if k + 1 < len(labels) else n
        value = [t for t in tokens[e:nxt_start] if t.kind != "checkbox"]
        out.append((spec, tokens[s:e], value))
    return out


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

    def add_missing(self, kind: str, path: str, label: str, reason: str, entity: str | None = None,
                    region: Region | None = None):
        self.missing.append({
            "kind": kind, "path": path, "label": label, "reason": reason, "entity": entity,
            "section": region.name if region else None, "page": region.page if region else None,
            "bbox": region.heading_bbox if region else None,
        })

    def slot(self, path: str, tokens: list[Token], region: Region, label: str):
        for t in tokens:
            if t.field_name:
                self.slots.append({"field": t.field_name, "path": path, "label": label, "section": region.key,
                                   "page": t.page, "rect": t.bbox, "kind": "checkbox" if t.kind == "checkbox" else "text"})

    # ------------------------------------------------------------------ run
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
        table = Template.alias_table(fields or spec["fields"])
        for region in regions:
            for ln in self.lines(region):
                for fspec, ltoks, vtoks in _parse_kv_line(ln.tokens, table):
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
            raw = clean(join_tokens(vtoks))
            if not raw:
                continue
            value, ok = normalise(raw, fspec.get("type", "text"))
            attr = self.make_attr(value, ltoks, vtoks, "key_value", region, raw=raw)
            _type_notes(attr, raw, value, ok, fspec.get("type", "text"))
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
                page=region0.page, bbox=region0.heading_bbox, extraction_method="section_heading", confidence=0.95,
                section=region0.name, region_id=region0.region_id,
                order=(region0.page, region0.heading_bbox[1] - 0.1, region0.heading_bbox[0]))
            company = found.get("insurance_company")
            ent.label = company.value if company else spec.get("policy_type", "")
            ent.extra["policy_type"] = spec.get("policy_type")
            if company:
                self._derive_company(ent, company, region0)
        else:
            nm = found.get("full_name")
            ent.label = nm.value if nm else TYPE_NAMES.get(espec["type"], espec["type"])
        # required fields
        for f in spec["fields"]:
            if f.get("required") and f["key"] not in ent.attributes:
                self.add_missing("not_provided", f"{spec['key']}.{f['key']}", f.get("label", f["key"]),
                                 "no value found in the source document", ent.id, region0)
        return ent

    def _derive_names(self, ent: Entity, region: Region | None):
        full = ent.attributes.get("full_name")
        if full and ("first_name" not in ent.attributes or "last_name" not in ent.attributes):
            first, last = split_person_name(full.raw or str(full.value))
            line_tokens = self._tokens_in_bbox(full.page, full.bbox)
            for key, part in (("first_name", first), ("last_name", last)):
                if part and key not in ent.attributes:
                    toks = [t for t in line_tokens if t.text.strip(",.") == part] or line_tokens
                    ent.attributes[key] = Attribute(
                        value=part, field_label=full.field_label, page=full.page, bbox=bbox_of(toks) if toks else full.bbox,
                        label_bbox=full.label_bbox, extraction_method="derived_split",
                        confidence=round(min(0.85, full.confidence - 0.07), 2),
                        section=full.section, region_id=full.region_id, raw=full.raw,
                        notes=[f"derived by splitting the printed name '{full.raw}'"],
                        order=(99, 0, 1 if key == "first_name" else 2))
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
        out = []
        for region in regions:
            t = find_table(self.lines(region), spec["columns"], region)
            if t:
                out.append((region, t))
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
        ent = self.new_entity(espec["type"], espec["prefix"], key_cell.text, region, espec["group"], row=rowno)
        ent.extra["row_bbox"] = bbox_of([t for ln in row.lines for t in ln.tokens])
        for ckey, (cspec, htoks) in cols.items():
            cell: Cell = row.cells[ckey]
            raw = cell.text
            if not raw:
                continue
            value, ok = normalise(raw, cspec.get("type", "text"))
            wrapped = ckey in row.wrapped_columns
            attr = self.make_attr(value, htoks, cell.all_tokens, "table", region, raw=raw, row=rowno)
            _type_notes(attr, raw, value, ok, cspec.get("type", "text"))
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
                i = 0
                while i < len(toks):
                    t = toks[i]
                    if t.kind == "checkbox":
                        j = i + 1
                        lab = []
                        while j < len(toks) and toks[j].kind == "word" and (not lab or toks[j].x0 - lab[-1].x1 < 20):
                            lab.append(toks[j])
                            j += 1
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
                        i = j
                        continue
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
                        value, _ = normalise(cell.text, cspec.get("type", "text"))
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
        boxes = []
        for i, t in enumerate(toks):
            if t.kind == "checkbox":
                lab = toks[i + 1] if i + 1 < len(toks) and toks[i + 1].kind == "word" else None
                boxes.append((t, lab))
        if not boxes:
            return None
        first_box = toks.index(boxes[0][0])
        question = [t for t in toks[:first_box] if t.kind == "word"]
        yes = [(b, l) for b, l in boxes if l is not None and norm(l.text) in ("yes", "y")]
        no = [(b, l) for b, l in boxes if l is not None and norm(l.text) in ("no", "n")]
        if not yes and not no:
            return None
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
            value, _ = normalise(raw, fspec.get("type", "text"))
            found[key] = (self.make_attr(value, ltoks, vtoks, "key_value", region, raw=raw), ltoks)
        if self.scan:
            return None
        ent = self.new_entity(espec["type"], espec["prefix"], spec["name"], region0, espec["group"])
        ent.extra["agreement_key"] = spec["key"]
        ent.attributes["title"] = Attribute(
            value=spec["name"], field_label=region0.heading, page=region0.page, bbox=region0.heading_bbox,
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
            for m in self.marks:
                if m.page == region.page and region.contains(m) and abs(m.cy - ln.cy) < 14 and m.x0 >= label_end - 4 and m.x0 < limit:
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
def _type_notes(attr: Attribute, raw: str, value, ok: bool, vtype: str) -> None:
    """Explain corrections and doubtful formats.  An OCR value that had to be corrected,
    or that does not fit its type, goes to review instead of being trusted."""
    ocr = attr.extraction_method.startswith("ocr")
    if vtype in ("dosage", "year") and isinstance(value, str) and value.replace(" ", "") != raw.replace(" ", ""):
        attr.notes.append(f"read as '{raw}', corrected to '{value}'")
        if ocr and attr.status == "valid":
            attr.status = "needs_review"
    if not ok and vtype not in ("text", "person_name", "lower", "list"):
        attr.notes.append(f"value '{raw}' does not look like a {vtype.replace('_', ' ')}")
        if ocr and attr.status == "valid":
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
