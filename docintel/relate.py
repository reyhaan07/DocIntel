"""Stage 4 - Relate.

Builds typed relationships between bound entities.  Every relationship says
*why* it exists (``basis``), which page locations support it (``evidence``) and
whether it is ``explicit`` or ``uncertain``.  Doubtful links are kept and marked
uncertain instead of being guessed one way or the other.
"""
from __future__ import annotations

import re

from .bind import Binder
from .models import Attribute, Entity, Evidence, Relationship, Region
from .normalize import same_person

WRAP_WARNING = "row text wraps onto a following line; merged values must be confirmed"


class Relater:
    def __init__(self, binder: Binder, threshold: float):
        self.b = binder
        self.threshold = threshold
        self.rels: list[Relationship] = []
        self.regions = {r.region_id: r for r in binder.regions}
        self.patient: Entity = binder.patient

    # ------------------------------------------------------------------ helpers
    def region(self, ent: Entity) -> Region | None:
        return self.regions.get(ent.region_id) if ent.region_id else None

    def where(self, ent: Entity, prefix: str = "") -> str:
        r = self.region(ent)
        if not r:
            return prefix.strip()
        return f"{prefix}inside section '{r.name}' (heading '{r.heading}', page {r.page})"

    @staticmethod
    def ev(attr: Attribute | None, role: str) -> list[Evidence]:
        if not attr or not attr.page or not attr.bbox:
            return []
        v = attr.value
        text = ", ".join(v) if isinstance(v, list) else ("" if v is None else str(v))
        out = [Evidence(attr.page, attr.bbox, text, role)]
        if attr.label_bbox and role in ("subject", "object", "value"):
            out.append(Evidence(attr.page, attr.label_bbox, attr.field_label or "", "label"))
        return out

    def heading_ev(self, ent: Entity) -> list[Evidence]:
        r = self.region(ent)
        return [Evidence(r.hpage, r.heading_bbox, r.heading, "heading")] if r else []

    def name_attr(self, ent: Entity) -> Attribute | None:
        for k in ("full_name", "name", "allergen", "procedure", "insurance_company", "relation", "topic", "title"):
            if k in ent.attributes:
                return ent.attributes[k]
        return next(iter(ent.attributes.values()), None)

    def add(self, subj: Entity, predicate: str, obj: Entity, conf: float, basis: str, evidence: list[Evidence],
            warnings: list[str] | None = None, page: int | None = None, row: int | None = None,
            region: Region | None = None) -> Relationship:
        warnings = list(warnings or [])
        if conf < self.threshold:
            warnings.append(f"relationship confidence {conf:.2f} is below the review threshold")
        support = "uncertain" if warnings else "explicit"
        region = region or self.region(obj) or self.region(subj)
        rel = Relationship(
            id=f"REL_{len(self.rels) + 1:03d}", subject=subj.id, predicate=predicate, object=obj.id, support=support,
            confidence=conf, basis=basis, section=region.name if region else None,
            heading=region.heading if region else None, page=page or (region.page if region else None), row=row,
            evidence=evidence, warnings=warnings,
        )
        self.rels.append(rel)
        return rel

    def of_type(self, etype: str) -> list[Entity]:
        return [e for e in self.b.entities.values() if e.type == etype]

    # ------------------------------------------------------------------ rules
    def run(self) -> list[Relationship]:
        P = self.patient
        pname = P.label
        for s in self.of_type("Spouse"):
            a = self.name_attr(s)
            self.add(P, "HAS_SPOUSE", s, a.confidence if a else 0.9, self.where(s, "listed "),
                     self.ev(a, "object") + self.heading_ev(s))
        for e in self.of_type("EmergencyContact"):
            a = self.name_attr(e)
            self.add(P, "HAS_EMERGENCY_CONTACT", e, a.confidence if a else 0.9, self.where(e, "listed "),
                     self.ev(a, "object") + self.heading_ev(e))
        for ph in self.of_type("Pharmacy"):
            a = self.name_attr(ph)
            self.add(P, "USES_PHARMACY", ph, a.confidence if a else 0.9, self.where(ph, "listed "),
                     self.ev(a, "object") + self.heading_ev(ph))
        for pol in self.of_type("InsurancePolicy"):
            self._insurance(pol)
        for med in self.of_type("Medication"):
            self._medication(med)
        for alg in self.of_type("Allergy"):
            a = alg.attributes.get("allergen")
            self.add(P, "HAS_ALLERGY", alg, a.confidence if a else 0.9, self.where(alg, f"row {alg.row} "),
                     self.ev(a, "object") + self.heading_ev(alg), row=alg.row)
        for cond in self.of_type("Condition"):
            if cond.extra.get("owner_hint") == "patient":
                a = cond.attributes.get("name")
                how = "'Other' entry " if cond.extra.get("option") == "other" else f"box ticked for '{cond.label}' "
                self.add(P, "HAS_CONDITION", cond, a.confidence if a else 0.9, self.where(cond, how),
                         self.ev(a, "object") + self.heading_ev(cond))
        for s in self.of_type("Surgery"):
            a = s.attributes.get("procedure")
            self.add(P, "HAD_SURGERY", s, a.confidence if a else 0.9, self.where(s, f"row {s.row} "),
                     self.ev(a, "object") + self.heading_ev(s), row=s.row)
            hid = s.links.get("facility_id")
            if hid:
                h = self.b.entities[hid]
                fac = s.attributes.get("facility")
                self.add(s, "PERFORMED_AT", h, min(a.confidence if a else 0.9, fac.confidence),
                         f"'{fac.field_label}' recorded on the same table row as the surgery (row {s.row} of '{s.section}')",
                         self.ev(a, "subject") + self.ev(fac, "object") + self.heading_ev(s), row=s.row)
        for fam in self.of_type("FamilyMember"):
            rel_attr = fam.attributes.get("relation")
            self.add(P, "HAS_FAMILY_HISTORY", fam, rel_attr.confidence if rel_attr else 0.85,
                     self.where(fam, f"'{fam.label}' line "), self.ev(rel_attr, "object") + self.heading_ev(fam))
            for cid in fam.links.get("condition_ids", []):
                cond = self.b.entities[cid]
                a = cond.attributes.get("name")
                self.add(fam, "HAS_CONDITION", cond, a.confidence if a else 0.85,
                         self.where(cond, f"condition printed on the '{fam.label}' line "),
                         self.ev(rel_attr, "subject") + self.ev(a, "object") + self.heading_ev(cond))
        for c in self.of_type("Consent"):
            self._consent(c)
        for agr in self.of_type("Agreement"):
            self._agreement(agr)
        return self.rels

    def _insurance(self, pol: Entity):
        P = self.patient
        r = self.region(pol)
        pt = pol.attributes.get("policy_type")
        self.add(P, "HAS_INSURANCE", pol, pt.confidence if pt else 0.9,
                 f"policy printed under its own heading '{r.heading}' (page {r.page})" if r else "policy section",
                 self.ev(pt, "object"))
        cid = pol.links.get("insurance_company_id")
        carrier = pol.attributes.get("insurance_company")
        if cid and carrier:
            self.add(pol, "ISSUED_BY", self.b.entities[cid], carrier.confidence,
                     f"'{carrier.field_label}' printed inside the same policy region '{r.heading}'",
                     self.ev(carrier, "object") + self.heading_ev(pol))
        holder = pol.attributes.get("policy_holder_name")
        relation = pol.attributes.get("policy_holder_relationship")
        if not holder and not relation:
            return
        hname = holder.value if holder else None
        rtext = (relation.value if relation else "") or ""
        spouse = next(iter(self.of_type("Spouse")), None)
        emc = next(iter(self.of_type("EmergencyContact")), None)
        conf = min(a.confidence for a in (holder, relation) if a)
        ev = self.ev(holder, "object") + self.ev(relation, "value") + self.heading_ev(pol)
        target, basis, warnings = None, "", []
        if rtext == "self" or (hname and same_person(hname, P.attributes.get("full_name").value if "full_name" in P.attributes else P.label)):
            target = P
            if hname and not same_person(hname, P.label) and "full_name" in P.attributes and not same_person(hname, P.attributes["full_name"].value):
                warnings.append(f"policy holder '{hname}' is marked 'Self' but does not match patient '{P.label}'")
            basis = f"policy holder listed as '{relation.raw if relation else 'Self'}'" + (f" and the name '{hname}' matches the patient" if hname and not warnings else "")
        elif spouse and hname and same_person(hname, spouse.label):
            target = spouse
            basis = (f"policy holder listed as '{relation.raw if relation else 'spouse'}' and the name '{hname}' matches "
                     f"the {spouse.section} section ({spouse.id})")
            ev += self.ev(spouse.attributes.get("full_name"), "value")
        elif emc and hname and same_person(hname, emc.label):
            target = emc
            basis = f"policy holder name '{hname}' matches the emergency contact ({emc.id})"
        elif spouse and rtext in ("spouse", "husband", "wife", "partner"):
            target = spouse
            basis = f"policy holder listed as '{relation.raw}'"
            warnings.append(f"policy holder name '{hname}' does not match spouse '{spouse.label}'")
        if target is not None:
            self.add(pol, "HELD_BY", target, conf, basis, ev, warnings)
        else:
            pol.extra["holder_unresolved"] = f"policy holder '{hname}' ({rtext or 'relationship not given'}) matches no person on the form"

    def _medication(self, med: Entity):
        P = self.patient
        name = med.attributes.get("name")
        warnings = []
        conf = name.confidence if name else 0.9
        ev = self.ev(name, "object") + self.heading_ev(med)
        if med.extra.get("row_wrapped"):
            warnings.append(WRAP_WARNING)
            conf = min(conf, min(a.confidence for a in med.attributes.values()))
            for col in med.extra.get("wrapped_columns", []):
                ev += self.ev(med.attributes.get(col), "value")
        self.add(P, "TAKES_MEDICATION", med, conf, self.where(med, f"row {med.row} "), ev, warnings, row=med.row)
        did = med.links.get("prescribing_doctor_id")
        if did:
            doc_attr = med.attributes.get("prescribing_doctor")
            self.add(med, "PRESCRIBED_BY", self.b.entities[did], min(conf if not warnings else 0.9, doc_attr.confidence),
                     f"'{doc_attr.field_label}' recorded on the same table row as the medication (row {med.row} of '{med.section}')",
                     self.ev(name, "subject") + self.ev(doc_attr, "object") + self.heading_ev(med), row=med.row)

    def _consent(self, c: Entity):
        P = self.patient
        d = c.attributes.get("decision")
        q = c.extra.get("question") or c.label
        warnings = []
        if d is not None and d.value is None:
            reason = "yes/no answer could not be resolved" if d.notes and "could not resolve" in d.notes[0] else "no answer was marked"
            warnings.append(f"answer to '{q}?' needs review ({reason})")
        self.add(P, "PROVIDES_CONSENT", c, d.confidence if d else 0.9, self.where(c, f"answer to '{q}' "),
                 self.ev(d, "object") + self.heading_ev(c), warnings)
        for pid in c.links.get("authorized_person_ids", []):
            person = self.b.entities[pid]
            na = person.attributes.get("full_name")
            w = []
            if d is None or d.value is None:
                w.append("the release authorization answer could not be resolved")
            elif d.value == "no":
                w.append("release was answered 'No' but a person is listed to receive information")
            self.add(P, "AUTHORIZES_RELEASE_TO", person, na.confidence if na else 0.9,
                     f"row {person.row} of the release list; release answered '{d.value if d and d.value else 'unresolved'}'",
                     self.ev(na, "object") + self.ev(d, "value") + self.heading_ev(person), w, row=person.row)

    def _agreement(self, agr: Entity):
        """Who signed: the person whose name is printed under (or typed as) the signature.
        The patient by default; a spouse, emergency contact or authorized person named on
        the form when the printed name is theirs; doubtful when it is nobody's."""
        P = self.patient
        sig = agr.attributes.get("signature")
        if not sig:
            return
        printed = agr.attributes.get("printed_name")
        signer = printed.value if printed else None
        if not signer and isinstance(sig.value, str) and re.match(r"^(/s/|digitally signed by\b)", sig.value.strip(), re.I):
            signer = re.sub(r"^(/s/|digitally signed by)\s*", "", sig.value.strip(), flags=re.I)
        warnings = []
        conf = 0.9
        subject = P
        how = ""
        pnames = [P.label] + ([P.attributes["full_name"].value] if "full_name" in P.attributes else [])
        known_patient = any(n and n != "Patient" for n in pnames)
        if signer and any(same_person(signer, n) for n in pnames if n and n != "Patient"):
            how = f"; printed name '{signer}' is the patient's"
        elif signer:
            others = [e for t in ("Spouse", "EmergencyContact", "AuthorizedPerson") for e in self.of_type(t)
                      if same_person(signer, (e.attributes.get("full_name").value if "full_name" in e.attributes else e.label))]
            ids = {name_key_of(e) for e in others}
            if others and len(ids) == 1:
                subject = others[0]
                rel = others[0].attributes.get("relationship")
                role = {"Spouse": "spouse", "EmergencyContact": "emergency contact",
                        "AuthorizedPerson": "authorized person"}[subject.type]
                how = (f"; printed name '{signer}' is the {role}" + (f" ({rel.value})" if rel and rel.value else "")
                       + ", not the patient")
                conf = 0.85
            else:
                conf = 0.75
                if not known_patient:
                    warnings.append(f"the patient's name was not found, so the printed name '{signer}' cannot be "
                                    "confirmed as the patient's")
                else:
                    warnings.append(f"printed name '{signer}' differs from patient '{P.label}' and matches nobody "
                                    "else on the form; the signer may be a guardian or representative")
        else:
            conf = 0.8
        title = agr.attributes.get("title")
        ev = self.ev(sig, "signature") + self.ev(printed, "value") + (
            [Evidence(title.page, title.bbox, title.field_label, "heading")] if title else [])
        self.add(subject, "SIGNS", agr, conf,
                 f"signature found on the '{sig.field_label}' line of '{agr.label}' (page {sig.page}){how}",
                 ev, warnings, page=sig.page)


def name_key_of(e: Entity) -> str:
    from .normalize import name_key
    a = e.attributes.get("full_name")
    return name_key(a.value if a else e.label)


def relate(binder: Binder, threshold: float) -> list[Relationship]:
    return Relater(binder, threshold).run()
