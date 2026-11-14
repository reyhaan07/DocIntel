"""Relationship questions answered from a document's JSON (no model, no guessing).

Questions
---------
find <text>          where a value appears, and whose it is
entity <ID>          everything that belongs to an entity
owner <ID|ref>       who an entity or value belongs to
section <ref>        which section, heading, page and box a value came from
related <ID> <ID>    how two elements are related (shortest relationship path)
evidence <REL_ID>    which page locations support a relationship
"""
from __future__ import annotations

import re
from collections import deque

PERSON_TYPES = {"Patient", "Spouse", "EmergencyContact", "FamilyMember", "AuthorizedPerson", "Doctor"}
OWNERSHIP = ["HAS_CONDITION", "TAKES_MEDICATION", "HAS_ALLERGY", "HAD_SURGERY", "HAS_FAMILY_HISTORY", "HAS_INSURANCE",
             "PROVIDES_CONSENT", "SIGNS", "HAS_SPOUSE", "HAS_EMERGENCY_CONTACT", "AUTHORIZES_RELEASE_TO", "ISSUED_BY",
             "PERFORMED_AT", "PRESCRIBED_BY"]

QUESTIONS = {
    "find": "Find where a value appears (and whose it is)",
    "entity": "What belongs to an entity",
    "owner": "Who an entity or value belongs to",
    "section": "Which section a value came from",
    "related": "How two elements are related",
    "evidence": "Which page supports a relationship",
}


class AskError(ValueError):
    pass


def _value_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return str(v)


class Asker:
    def __init__(self, doc: dict):
        self.doc = doc
        self.ents: dict = doc["entities"]
        self.rels: list = doc["relationships"]
        self.rel_by_id = {r["relationship_id"]: r for r in self.rels}

    # ------------------------------------------------------------------ helpers
    def _entity(self, eid: str) -> dict:
        eid = eid.strip().upper()
        if eid not in self.ents:
            raise AskError(f"unknown entity '{eid}'")
        return self.ents[eid]

    def _split_ref(self, ref: str):
        ref = ref.strip()
        if "." in ref:
            eid, attr = ref.split(".", 1)
            ent = self._entity(eid)
            if attr not in ent["attributes"]:
                raise AskError(f"{ent['id']} has no attribute '{attr}'")
            return ent, attr
        return self._entity(ref), None

    def describe(self, eid: str) -> str:
        e = self.ents.get(eid)
        return f"{eid} {e['label']}" if e else eid

    def owner_of(self, eid: str, _seen=None) -> tuple[str, list[str]]:
        """-> (owner entity id, chain of relationship ids)."""
        seen = _seen or set()
        seen.add(eid)
        e = self.ents[eid]
        if e["type"] in PERSON_TYPES:
            return eid, []
        incoming = [r for r in self.rels if r["object"] == eid and r["subject"] not in seen]
        incoming.sort(key=lambda r: OWNERSHIP.index(r["predicate"]) if r["predicate"] in OWNERSHIP else 99)
        for r in incoming:
            owner, chain = self.owner_of(r["subject"], seen)
            return owner, [r["relationship_id"], *chain]
        return eid, []

    # ------------------------------------------------------------------ questions
    def find(self, text: str) -> list[dict]:
        q = text.strip().lower()
        if not q:
            raise AskError("type a value to look for")
        out = []
        for e in self.ents.values():
            for k, a in e["attributes"].items():
                vt = _value_text(a.get("value"))
                if q in vt.lower():
                    owner, _ = self.owner_of(e["id"])
                    out.append({"ref": f"{e['id']}.{k}", "value": a.get("value"), "page": a.get("page"),
                                "owner": self.ents[owner]["label"]})
        out.sort(key=lambda r: (r["page"] or 0, r["ref"]))
        return out

    def entity(self, eid: str) -> dict:
        e = self._entity(eid)
        owner, _ = self.owner_of(e["id"])
        return {
            "entity": e["id"], "type": e["type"], "label": e["label"], "section": e.get("section"),
            "page": e.get("page"), "owner": self.ents[owner]["label"] if owner != e["id"] else None,
            "attributes": {k: a.get("value") for k, a in e["attributes"].items()},
            "relationships": [
                f"{r['relationship_id']}: {self.describe(r['subject'])} {r['predicate']} {self.describe(r['object'])}"
                + (" (uncertain)" if r["support"] == "uncertain" else "")
                for r in self.rels if e["id"] in (r["subject"], r["object"])
            ],
        }

    def owner(self, ref: str) -> dict:
        ent, attr = self._split_ref(ref)
        owner, chain = self.owner_of(ent["id"])
        out = {"ref": f"{ent['id']}.{attr}" if attr else ent["id"], "name": ent["label"], "owner": owner,
               "owner_name": self.ents[owner]["label"]}
        if attr:
            a = ent["attributes"][attr]
            out.update({"value": a.get("value"), "page": a.get("page")})
        out["via"] = [f"{rid}: {self.describe(self.rel_by_id[rid]['subject'])} {self.rel_by_id[rid]['predicate']} "
                      f"{self.describe(self.rel_by_id[rid]['object'])}" for rid in chain]
        if chain:
            out["basis"] = self.rel_by_id[chain[0]]["basis"]
        return out

    def section(self, ref: str) -> dict:
        ent, attr = self._split_ref(ref)
        if not attr:
            return {"ref": ent["id"], "section": ent.get("section"), "page": ent.get("page"), "row": ent.get("row")}
        a = ent["attributes"][attr]
        sec = next((s for s in self.doc["sections"] if s["section_id"] == ent.get("section_id")), None)
        return {"ref": f"{ent['id']}.{attr}", "value": a.get("value"), "section": a.get("section"),
                "heading": sec["heading"] if sec else None, "printed_label": a.get("field_label"),
                "page": a.get("page"), "bbox": a.get("bbox"), "row": a.get("row"),
                "extraction_method": a.get("extraction_method"), "confidence": a.get("confidence")}

    def related(self, a: str, b: str) -> dict:
        a_ent, _ = self._split_ref(a)
        b_ent, _ = self._split_ref(b)
        start, goal = a_ent["id"], b_ent["id"]
        adj: dict[str, list] = {}
        for r in self.rels:
            adj.setdefault(r["subject"], []).append((r["object"], r))
            adj.setdefault(r["object"], []).append((r["subject"], r))
        prev: dict[str, tuple] = {start: None}  # type: ignore[dict-item]
        dq = deque([start])
        while dq:
            cur = dq.popleft()
            if cur == goal:
                break
            for nxt, r in adj.get(cur, []):
                if nxt not in prev:
                    prev[nxt] = (cur, r)
                    dq.append(nxt)
        if goal not in prev:
            return {"from": start, "to": goal, "related": False, "path": []}
        path = []
        cur = goal
        while prev[cur] is not None:
            p, r = prev[cur]
            path.append(r)
            cur = p
        path.reverse()
        return {"from": start, "to": goal, "related": True, "hops": len(path),
                "path": [{"relationship_id": r["relationship_id"],
                          "statement": f"{self.describe(r['subject'])} {r['predicate']} {self.describe(r['object'])}",
                          "support": r["support"], "basis": r["basis"]} for r in path]}

    def evidence(self, rid: str) -> dict:
        rid = rid.strip().upper()
        r = self.rel_by_id.get(rid)
        if not r:
            raise AskError(f"unknown relationship '{rid}'")
        return {"relationship_id": rid,
                "statement": f"{self.describe(r['subject'])} {r['predicate']} {self.describe(r['object'])}",
                "support": r["support"], "confidence": r["confidence"], "basis": r["basis"],
                "pages": sorted({e["page"] for e in r["evidence"]}),
                "evidence": r["evidence"], "warnings": r["warnings"]}


def ask(doc: dict, question: str, *args: str):
    question = question.strip().lower()
    a = Asker(doc)
    if question == "find":
        return a.find(" ".join(args))
    if question in ("entity", "owner", "section", "evidence"):
        if len(args) != 1:
            raise AskError(f"'{question}' takes one reference")
        return getattr(a, question)(args[0])
    if question == "related":
        refs = [x for x in re.split(r"[\s,]+", " ".join(args)) if x]
        if len(refs) != 2:
            raise AskError("'related' takes two references")
        return a.related(*refs)
    raise AskError(f"unknown question '{question}' (choose from: {', '.join(QUESTIONS)})")


def suggestions(doc: dict) -> list[str]:
    out = list(doc["entities"])
    out += [f"{e['id']}.{k}" for e in doc["entities"].values() for k in e["attributes"]]
    out += [r["relationship_id"] for r in doc["relationships"]]
    return out
