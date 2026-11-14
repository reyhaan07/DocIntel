"""Fill the standardized reference form from a document's structured JSON.

Values are placed by *structure*, never by position on the source page:
medication row 3 goes to form row 3, the mother's record goes to the mother
row, a consent goes to its own yes/no boxes.  Anything still awaiting review is
left blank, so an unconfirmed value is never printed on the official form.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .normalize import display_date
from .template import TEMPLATE_DIR

_PATH = re.compile(r"^(?P<sec>[a-z_]+)(?:\[(?P<idx>[^\]]+)\])?(?:\.(?P<rest>.+))?$")


@lru_cache(maxsize=4)
def load_field_map(template_id: str = "patient_intake_v1") -> dict:
    path = TEMPLATE_DIR / f"{template_id}.fieldmap.json"
    return json.loads(path.read_text(encoding="utf-8"))


def reference_pdf(template_id: str = "patient_intake_v1") -> Path:
    return TEMPLATE_DIR / f"{template_id}.pdf"


def _fmt(attr: dict, key: str) -> str:
    v = attr.get("value")
    if v is None:
        return ""
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    v = str(v)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return display_date(v)
    if key in ("sex", "marital_status", "relationship", "policy_holder_relationship", "living_status"):
        return v[:1].upper() + v[1:]
    return v


class _Resolver:
    def __init__(self, doc: dict):
        self.doc = doc
        self.ents = doc["entities"]
        self.by_section: dict[str, list[dict]] = {}
        for e in self.ents.values():
            if e.get("derived"):
                continue
            self.by_section.setdefault(e.get("section_key") or "", []).append(e)
        if "patient_information" not in self.by_section:
            pat = next((e for e in self.ents.values() if e["type"] == "Patient"), None)
            if pat:
                self.by_section["patient_information"] = [pat]

    def _consent(self, key: str):
        return next((e for e in self.ents.values() if e["type"] == "Consent" and e.get("consent_key") == key), None)

    def resolve(self, path: str):
        """-> (value, ref, status) where value is str for text fields / bool for check boxes."""
        m = _PATH.match(path)
        if not m:
            return None, None, "unmapped"
        sec, idx, rest = m.group("sec"), m.group("idx"), m.group("rest") or ""
        ents = self.by_section.get(sec, [])
        if sec == "medical_history":
            conds = [e for e in self.ents.values() if e["type"] == "Condition" and e.get("section_key") == sec]
            if rest.startswith("options."):
                key = rest.split(".", 1)[1]
                hit = next((c for c in conds if c.get("option") == key), None)
                return bool(hit), (f"{hit['id']}.name" if hit else None), "filled"
            if rest == "other":
                known = {o for o in self._options()}
                others = [c for c in conds if c.get("option") not in known]
                if not others:
                    return "", None, "empty"
                return ", ".join(c["attributes"]["name"]["value"] for c in others), f"{others[0]['id']}.name", "filled"
        if sec == "communication_consent" or (sec == "release_of_information" and rest.startswith("decision.")):
            if sec == "communication_consent":
                ckey, answer = rest.split(".", 1)
            else:
                ckey, answer = "release_of_information", rest.split(".", 1)[1]
            c = self._consent(ckey)
            if not c:
                return False, None, "empty"
            d = c["attributes"].get("decision", {})
            ref = f"{c['id']}.decision"
            if d.get("status") != "valid" or d.get("value") is None:
                return False, ref, "withheld"
            return d["value"] == answer, ref, "filled"
        if idx is not None:
            if sec == "family_history":
                ent = next((e for e in ents if e["type"] == "FamilyMember"
                            and e["attributes"].get("relation", {}).get("value") == idx), None)
            else:
                ent = next((e for e in ents if str(e.get("row")) == idx), None)
        else:
            ent = ents[0] if ents else None
        if not ent:
            return "", None, "empty"
        attr = ent["attributes"].get(rest)
        if not attr:
            return "", None, "empty"
        ref = f"{ent['id']}.{rest}"
        if attr.get("status") != "valid":
            return "", ref, "withheld"
        if rest == "signature" and attr.get("extraction_method") in ("layout_signature", "ocr_signature"):
            printed = ent["attributes"].get("printed_name", {}).get("value")
            return (f"/s/ {printed}" if printed else f"(signed, see source page {attr.get('page')})"), ref, "filled"
        return _fmt(attr, rest), ref, "filled"

    @lru_cache(maxsize=1)
    def _options(self):
        fm = load_field_map(self.doc["document"].get("template", "patient_intake_v1"))
        return tuple(v["path"].split(".")[-1] for v in fm["fields"].values() if v["path"].startswith("medical_history.options."))


def placements(doc: dict, field_map: dict | None = None) -> list[dict]:
    field_map = field_map or load_field_map(doc["document"].get("template", "patient_intake_v1"))
    res = _Resolver(doc)
    out = []
    for name, f in field_map["fields"].items():
        value, ref, status = res.resolve(f["path"])
        out.append({"field": name, "path": f["path"], "kind": f["kind"], "page": f["page"], "bbox": f["rect"],
                    "ref": ref, "value": value, "status": status})
    return out


def fill_standardized(doc: dict, out_path: str | Path, template_id: str | None = None) -> dict:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject

    template_id = template_id or doc["document"].get("template", "patient_intake_v1")
    field_map = load_field_map(template_id)
    places = placements(doc, field_map)
    reader = PdfReader(str(reference_pdf(template_id)))
    writer = PdfWriter(clone_from=reader)

    on_states: dict[str, str] = {}
    for page in writer.pages:
        for ref in page.get("/Annots") or []:
            a = ref.get_object()
            ap = a.get("/AP")
            if a.get("/FT") == "/Btn" and ap is not None and "/N" in ap:
                states = [k for k in ap["/N"].keys() if k != "/Off"]
                if states:
                    on_states[str(a.get("/T"))] = states[0]

    by_page: dict[int, dict] = {}
    for p in places:
        if p["kind"] == "checkbox":
            if p["value"] is True and p["status"] == "filled":
                by_page.setdefault(p["page"], {})[p["field"]] = on_states.get(p["field"], "/Yes")
        elif p["value"]:
            by_page.setdefault(p["page"], {})[p["field"]] = str(p["value"])
    for pno, values in by_page.items():
        page = writer.pages[pno - 1]
        text_vals = {k: v for k, v in values.items() if not v.startswith("/")}
        if text_vals:
            writer.update_page_form_field_values(page, text_vals, auto_regenerate=False)
        for ref in page.get("/Annots") or []:
            a = ref.get_object()
            name = str(a.get("/T"))
            if name in values and values[name].startswith("/"):
                a[NameObject("/V")] = NameObject(values[name])
                a[NameObject("/AS")] = NameObject(values[name])
    # NeedAppearances is deliberately left off: viewers would regenerate every widget and
    # drop the printed borders; pypdf already wrote appearance streams for the filled values.
    writer.add_metadata({"/Title": f"Standardized intake - {doc['document']['doc_id']}",
                         "/Subject": f"Filled from {doc['document']['filename']} by docintel"})
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as fh:
        writer.write(fh)

    filled = sum(1 for p in places if p["status"] == "filled" and (p["value"] is True or (p["kind"] == "text" and p["value"])))
    withheld_refs = sorted({p["ref"] for p in places if p["status"] == "withheld" and p["ref"]})
    return {
        "form": template_id,
        "file": out_path.name,
        "page_count": field_map["page_count"],
        "page_sizes": field_map["page_sizes"],
        "fields_total": len(places),
        "fields_filled": filled,
        "fields_withheld": len(withheld_refs),
        "withheld": [{"ref": r, "fields": [p["field"] for p in places if p["ref"] == r and p["status"] == "withheld"],
                      "reason": "awaiting review"} for r in withheld_refs],
        "placements": [p for p in places if p["status"] in ("filled", "withheld") and (p["value"] or p["status"] == "withheld" or p["kind"] == "checkbox")],
    }
