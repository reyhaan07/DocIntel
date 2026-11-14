"""Stage 5 - Validate.

Seven independent relationship checks run on every document.  A check either
passes, asks for review (something doubtful that a person should confirm) or
fails (a hard inconsistency).  Everything doubtful lands in the review queue.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from .bind import Binder
from .models import Entity, Relationship
from .template import Template

CHECKS = [
    ("evidence_provenance", "Evidence provenance",
     "every traced value points at content that exists in this file, on a real page"),
    ("predicate_signatures", "Predicate signatures",
     "every relationship has an allowed type between allowed entity types"),
    ("medication_record_integrity", "Medication record integrity",
     "each medication keeps the values of exactly one table row"),
    ("insurance_policy_separation", "Insurance policy separation",
     "values of one policy never come from another policy's region"),
    ("family_history_separation", "Family history separation",
     "each condition has exactly one owner, the patient or one family member"),
    ("consent_decision_integrity", "Consent decision integrity",
     "each consent has one resolved answer that matches its permissions"),
    ("signature_agreement_binding", "Signature agreement binding",
     "each signature belongs to exactly one agreement"),
    ("text_coverage", "Text coverage",
     "every piece of text on the page is accounted for: a value, a label, a heading or instructions"),
]
GENERIC_ENTITY_TYPES = {"Field", "TableRow", "Question", "Signature"}


def _inside(bbox, region, pad=1.0) -> bool:
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return region.x0 - pad <= cx <= region.x1 + pad and region.top - pad <= cy <= region.bottom + pad


def validate(binder: Binder, rels: list[Relationship], template: Template, structure=None, coverage=None,
             template_used: bool = True) -> dict:
    ents = binder.entities
    regions = {r.region_id: r for r in binder.regions}
    pages = {p.number: p for p in binder.pages}
    results = []

    def run(check_id, checked, issues):
        name, desc = next((n, d) for c, n, d in CHECKS if c == check_id)
        status = "failed" if any(i["severity"] == "error" for i in issues) else ("review" if issues else "passed")
        results.append({"check_id": check_id, "name": name, "description": desc, "checked": checked,
                        "status": status, "issues": issues})

    def issue(target, message, severity="review"):
        return {"target": target, "message": message, "severity": severity}

    # 1. evidence provenance -------------------------------------------------
    issues, checked = [], 0
    for e in ents.values():
        for k, a in e.attributes.items():
            if a.bbox is None:
                continue
            checked += 1
            pd = pages.get(a.page)
            if pd is None:
                issues.append(issue(f"{e.id}.{k}", f"page {a.page} does not exist in this file", "error"))
                continue
            x0, t, x1, b = a.bbox
            if x0 < -1 or t < -1 or x1 > pd.width + 1 or b > pd.height + 1:
                issues.append(issue(f"{e.id}.{k}", "bounding box lies outside the page", "error"))
                continue
            hit = any(tok.page == a.page and tok.x1 >= x0 - 1 and tok.x0 <= x1 + 1 and tok.bottom >= t - 1 and tok.top <= b + 1
                      for tok in pd.tokens) or any(m.x1 >= x0 and m.x0 <= x1 and m.bottom >= t and m.top <= b for m in pd.marks)
            if not hit:
                issues.append(issue(f"{e.id}.{k}", "no content of this file found at the recorded location", "error"))
    run("evidence_provenance", checked, issues)

    # 2. predicate signatures ------------------------------------------------
    issues = []
    for r in rels:
        s, o = ents.get(r.subject), ents.get(r.object)
        if not s or not o:
            issues.append(issue(r.id, "relationship points at an entity that does not exist", "error"))
        elif r.predicate not in template.relationship_types:
            issues.append(issue(r.id, f"'{r.predicate}' is not an allowed relationship type", "error"))
        elif not template.allowed(r.predicate, s.type, o.type):
            issues.append(issue(r.id, f"{s.type} {r.predicate} {o.type} is not an allowed signature", "error"))
    run("predicate_signatures", len(rels), issues)

    incoming: dict[str, list[Relationship]] = defaultdict(list)
    for r in rels:
        incoming[r.object].append(r)

    # 3. medication record integrity ----------------------------------------
    meds = [e for e in ents.values() if e.type == "Medication"]
    issues = []
    for m in meds:
        rows = {a.row for a in m.attributes.values()}
        regs = {a.region_id for a in m.attributes.values()}
        if len(rows) > 1 or len(regs) > 1:
            issues.append(issue(m.id, "values were taken from more than one table row", "error"))
        if m.extra.get("row_wrapped"):
            issues.append(issue(m.id, "row text wraps onto a following line; merged values must be confirmed"))
        takes = [r for r in incoming[m.id] if r.predicate == "TAKES_MEDICATION"]
        if len(takes) != 1:
            issues.append(issue(m.id, f"medication has {len(takes)} owners (expected exactly one)", "error"))
        presc = [r for r in rels if r.subject == m.id and r.predicate == "PRESCRIBED_BY"]
        if len(presc) > 1:
            issues.append(issue(m.id, "medication is linked to more than one prescriber", "error"))
    run("medication_record_integrity", len(meds), issues)

    # 4. insurance policy separation -----------------------------------------
    pols = [e for e in ents.values() if e.type == "InsurancePolicy"]
    issues = []
    for p in pols:
        own = regions.get(p.region_id)
        others = [regions[o.region_id] for o in pols if o is not p and o.region_id in regions]
        for k, a in p.attributes.items():
            if not a.bbox or k == "policy_type":
                continue
            if own and a.page == own.page and not _inside(a.bbox, own):
                issues.append(issue(f"{p.id}.{k}", "value lies outside the policy's own region", "error"))
            for o in others:
                if a.page == o.page and _inside(a.bbox, o, pad=-1):
                    issues.append(issue(f"{p.id}.{k}", f"value was read from another policy's region ({o.heading})", "error"))
        if p.extra.get("holder_unresolved"):
            issues.append(issue(p.id, p.extra["holder_unresolved"]))
        held = [r for r in rels if r.subject == p.id and r.predicate == "HELD_BY"]
        if len(held) > 1:
            issues.append(issue(p.id, "policy is held by more than one person", "error"))
    ids = Counter(str(p.attributes["member_id"].value).upper() for p in pols if "member_id" in p.attributes)
    for mid, n in ids.items():
        if n > 1:
            issues.append(issue(mid, f"member ID {mid} appears on {n} policies", "error"))
    run("insurance_policy_separation", len(pols), issues)

    # 5. family history separation -------------------------------------------
    conds = [e for e in ents.values() if e.type == "Condition"]
    fams = [e for e in ents.values() if e.type == "FamilyMember"]
    issues = []
    for c in conds:
        owners = [r for r in incoming[c.id] if r.predicate == "HAS_CONDITION"]
        if len(owners) != 1:
            issues.append(issue(c.id, f"condition has {len(owners)} owners (expected exactly one)", "error"))
            continue
        owner = ents[owners[0].subject]
        sec = c.section_key
        if owner.type == "Patient" and sec == "family_history":
            issues.append(issue(c.id, "a family-history condition was assigned to the patient", "error"))
        if owner.type == "FamilyMember" and sec != "family_history":
            issues.append(issue(c.id, "a patient condition was assigned to a family member", "error"))
    for f in fams:
        if not any(r.predicate == "HAS_FAMILY_HISTORY" for r in incoming[f.id]):
            issues.append(issue(f.id, "family member is not linked to the patient", "error"))
    run("family_history_separation", len(conds) + len(fams), issues)

    # 6. consent decision integrity ------------------------------------------
    cons = [e for e in ents.values() if e.type == "Consent"]
    issues = []
    for c in cons:
        d = c.attributes.get("decision")
        key = c.extra.get("consent_key", c.label)
        if d is None or d.value is None:
            issues.append(issue(c.id, f"consent decision for '{key}' could not be resolved"))
        if not any(r.predicate == "PROVIDES_CONSENT" for r in incoming[c.id]):
            issues.append(issue(c.id, "consent is not linked to the patient", "error"))
        people = c.links.get("authorized_person_ids", [])
        if people and d is not None and d.value == "no":
            issues.append(issue(c.id, "release was refused but people are listed to receive information"))
    run("consent_decision_integrity", len(cons), issues)

    # 7. signature agreement binding -----------------------------------------
    agrs = [e for e in ents.values() if e.type == "Agreement"]
    agr_regions = [r for r in binder.regions if template.by_key.get(r.key, {}).get("kind") == "agreement"]
    issues, checked = [], 0
    for a in agrs:
        sig = a.attributes.get("signature")
        if sig and sig.bbox:
            checked += 1
            holders = [r for r in agr_regions if r.page == sig.page and _inside(sig.bbox, r)]
            if len(holders) != 1 or holders[0].region_id != a.region_id:
                issues.append(issue(a.id, "signature is not inside exactly one agreement section", "error"))
    signs = [r for r in rels if r.predicate == "SIGNS"]
    for r in signs:
        checked += 1
        if "signature" not in ents[r.object].attributes:
            issues.append(issue(r.id, "SIGNS points at an agreement without a signature", "error"))
    targets = Counter(r.object for r in signs)
    for t, n in targets.items():
        if n > 1:
            issues.append(issue(t, "agreement has more than one signer link", "error"))
    run("signature_agreement_binding", checked, issues)

    # 8. text coverage ----------------------------------------------------------
    if structure is not None:
        from .generic import unexplained_tokens

        issues = []
        stray = unexplained_tokens(binder, structure)
        for t in stray[:20]:
            issues.append(issue(f"page {t.page}", f"text '{t.text}' could not be placed in any structure"))
        if template_used:
            by_section: dict[str, list[Entity]] = defaultdict(list)
            for e in ents.values():
                if e.type in GENERIC_ENTITY_TYPES:
                    by_section[e.section or "(no section)"].append(e)
            for sec, items in by_section.items():
                known = any(e.section_key and not e.section_key.startswith("other:") for e in items)
                for e in items[:10]:
                    where = f"section '{sec}'" + ("" if known else " (not part of the template)")
                    issues.append(issue(e.id, f"'{e.label}' in {where} is not part of the template; kept as a generic "
                                              f"{e.type.lower().replace('tablerow', 'table row')}"))
        run("text_coverage", (coverage or {}).get("tokens_total", 0), issues)

    errors = [dict(i, check=r["check_id"]) for r in results for i in r["issues"] if i["severity"] == "error"]
    warnings = [dict(i, check=r["check_id"]) for r in results for i in r["issues"] if i["severity"] != "error"]
    return {"checks": results, "errors": errors, "warnings": warnings}


def review_queue(binder: Binder, rels: list[Relationship], validation: dict, ocr_pages: list[dict]) -> list[dict]:
    items = []

    def add(**kw):
        kw["review_id"] = f"REV_{len(items) + 1:03d}"
        items.append(kw)

    for p in ocr_pages:
        add(kind="ocr", target=f"page {p['page']}", entity=None, attribute=None, page=p["page"], bbox=None,
            reason=p["reason"])
    for w in validation["warnings"] + validation["errors"]:
        target = w["target"]
        add(kind="validation", target=target, entity=target.split(".")[0], attribute=None, check=w["check"],
            severity=w["severity"], reason=f"[{w['check']}] {w['message']}")
    for e in binder.entities.values():
        for k, a in sorted(e.attributes.items(), key=lambda kv: kv[1].order):
            if a.status != "valid":
                add(kind="attribute", target=f"{e.id}.{k}", entity=e.id, attribute=k, value=a.value, page=a.page,
                    bbox=a.bbox, reason="; ".join(a.notes) or "value needs confirmation")
    for r in rels:
        if r.support == "uncertain":
            add(kind="relationship", target=r.id, entity=r.subject, subject=r.subject, predicate=r.predicate,
                object=r.object, page=r.page, reason="; ".join(r.warnings) or "relationship is uncertain")
    return items
