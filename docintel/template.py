"""Template loading and alias matching.

The template describes the canonical intake schema: which sections exist, the
headings each section may be printed under, the labels each field may carry and
the relationship types that are allowed between entity types.  Layout never has
to match the template -- only the *meaning* of headings and labels does.
"""
from __future__ import annotations

import copy
import difflib
import json
import re
from functools import lru_cache
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent / "templates"
DEFAULT_TEMPLATE = "patient_intake_v1"

_PUNCT = re.compile(r"[^a-z0-9#]+")


def norm(text: str) -> str:
    """Normalise printed text for alias comparison."""
    text = (text or "").lower().replace("&", " and ")
    text = _PUNCT.sub(" ", text)
    return " ".join(text.split())


def norm_tokens(text: str) -> list[str]:
    return norm(text).split()


_NUMBERING = re.compile(r"^\s*(?:(?:section|part|step|page)\s+)?(?:\d{1,2}(?:\.\d{1,2})?|[A-Za-z]|[IVXivx]{1,4})[.):\-]\s+")


def strip_numbering(text: str) -> str:
    """'1. PATIENT INFORMATION' / 'Section B: Insurance' / 'IV) Allergies' -> the heading itself."""
    t = text.strip()
    m = _NUMBERING.match(t)
    if m and len(t) > m.end():
        rest = t[m.end():]
        # a single letter followed by a real word ("A Patient") is only stripped with punctuation
        return rest
    return t


# words that mean the same thing in a label ("Policy No." = "Policy Number", "Tel" = "Phone")
SYNONYMS = {"no": "number", "num": "number", "nbr": "number", "#": "number", "tel": "phone",
            "telephone": "phone", "ph": "phone", "e": "e", "addr": "address", "dob": "dob"}


def canon_tokens(text: str) -> list[str]:
    toks = norm_tokens(text)
    out = []
    i = 0
    while i < len(toks):
        if toks[i] == "e" and i + 1 < len(toks) and toks[i + 1] == "mail":  # "e-mail"
            out.append("email")
            i += 2
            continue
        out.append(SYNONYMS.get(toks[i], toks[i]))
        i += 1
    return out


class Template:
    def __init__(self, data: dict):
        self.data = data
        self.template_id: str = data["template_id"]
        self.document_type: str = data.get("document_type", "document")
        self.review_threshold: float = float(data.get("review_threshold", 0.6))
        self.relationship_types: dict = data["relationship_types"]
        self.sections: list[dict] = []
        field_sets = data.get("field_sets", {})
        by_key = {s["key"]: s for s in data["sections"]}
        for raw in data["sections"]:
            sec = copy.deepcopy(raw)
            fields = sec.get("fields")
            if isinstance(fields, str) and fields.startswith("@"):
                ref = fields[1:]
                if ref in field_sets:
                    sec["fields"] = copy.deepcopy(field_sets[ref])
                else:
                    sec["fields"] = copy.deepcopy(by_key[ref]["fields"])
            self.sections.append(sec)
        self.by_key = {s["key"]: s for s in self.sections}
        # pre-tokenised aliases, longest first
        self._section_aliases = []
        for s in self.sections:
            for a in [s["name"], *s.get("aliases", [])]:
                self._section_aliases.append((norm(a), s["key"]))

    # ------------------------------------------------------------------ headings
    def match_section(self, text: str, fuzzy: bool = True) -> str | None:
        text = strip_numbering(text).rstrip(" :")
        t = norm(re.sub(r"\(?\b(?:continued|cont\.)(?=\W|$)\)?", "", text, flags=re.I))
        if not t or len(t) > 60:
            return None
        for alias, key in self._section_aliases:
            if t == alias:
                return key
        if fuzzy and len(t) >= 6:
            best, best_key = 0.0, None
            for alias, key in self._section_aliases:
                r = difflib.SequenceMatcher(None, t, alias).ratio()
                if r > best:
                    best, best_key = r, key
            if best >= 0.9:
                return best_key
        return None

    def match_sections(self, text: str) -> list[str]:
        """Every section a combined heading names: "Allergies and Family History" ->
        [allergies, family_history].  Each part must be a section heading by itself."""
        t = strip_numbering(text).rstrip(" :")
        parts = [p for p in re.split(r"\s+(?:and|&)\s+|\s*/\s*|\s*,\s*|\s+\+\s+", t, flags=re.I) if p.strip()]
        if len(parts) < 2:
            return []
        keys = []
        for part in parts:
            k = self.match_section(part, fuzzy=False)
            if not k:
                return []
            if k not in keys:
                keys.append(k)
        return keys

    # ------------------------------------------------------------------ labels
    @staticmethod
    def alias_table(specs: list[dict]) -> list[tuple[list[str], dict]]:
        """[(alias tokens, spec)] sorted longest alias first."""
        out = []
        for spec in specs:
            names = [spec.get("label", ""), *spec.get("aliases", [])]
            seen = set()
            for a in names:
                toks = canon_tokens(a)
                if toks and tuple(toks) not in seen:
                    seen.add(tuple(toks))
                    out.append((toks, spec))
        out.sort(key=lambda x: -len(x[0]))
        return out

    def field_spec(self, section_key: str, field_key: str) -> dict | None:
        sec = self.by_key.get(section_key)
        if not sec:
            return None
        for f in sec.get("fields", []) + sec.get("columns", []):
            if f["key"] == field_key:
                return f
        return None

    def allowed(self, predicate: str, subj_type: str, obj_type: str) -> bool:
        sig = self.relationship_types.get(predicate)
        if not sig:
            return False
        return subj_type in sig[0] and obj_type in sig[1]


@lru_cache(maxsize=8)
def _load(name: str) -> Template:
    path = Path(name)
    if not path.suffix:
        path = TEMPLATE_DIR / f"{name}.json"
    with open(path, encoding="utf-8") as fh:
        return Template(json.load(fh))


def load_template(name: str = DEFAULT_TEMPLATE) -> Template:
    return _load(str(name))
