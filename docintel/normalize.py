"""Value normalisation (dates, phones, names ...)."""
from __future__ import annotations

import re
from datetime import date

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def clean(text: str | None) -> str:
    return " ".join((text or "").split()).strip(" ,;")


def label_text(text: str) -> str:
    return clean(text).rstrip(":?").strip()


_NUM_DATE = re.compile(r"(?<![\d/.-])(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})(?![\d/.-])")
_US_HINT = re.compile(r"\(\d{3}\)\s?\d{3}-\d{4}|\b\d{3}[-.]\d{3}[-.]\d{4}\b|\b[A-Z]{2}\s\d{5}(-\d{4})?\b")


def infer_date_order(texts: list[str]) -> str | None:
    """Day/month order of numeric dates on one document: 'mdy', 'dmy', 'mixed' or None.

    Decided by unambiguous dates on the same document (13/05/2024 is day-first);
    without any, US phone or ZIP formats suggest month-first."""
    joined = " ".join(texts)
    mdy = dmy = 0
    for m in _NUM_DATE.finditer(joined):
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 >= b:
            dmy += 1
        elif b > 12 >= a:
            mdy += 1
    if mdy and dmy:
        return "mixed"
    if mdy:
        return "mdy"
    if dmy:
        return "dmy"
    if _US_HINT.search(joined):
        return "mdy"
    return None


def is_ambiguous_date(text: str) -> bool:
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", clean(text))
    return bool(m) and int(m.group(1)) <= 12 and int(m.group(2)) <= 12 and m.group(1).lstrip("0") != m.group(2).lstrip("0")


def parse_date(text: str, order: str = "mdy") -> str | None:
    t = clean(text)
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", t)
        if m:
            if order == "dmy":
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if mo > 12 and d <= 12:
                    mo, d = d, mo
            else:
                mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if y < 100:
                y += 1900 if y > 30 else 2000
            if mo > 12 and d <= 12:
                mo, d = d, mo
        else:
            m = re.fullmatch(r"([A-Za-z]{3,})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", t)
            m2 = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,})\.?,?\s+(\d{4})", t)
            if m:
                mo = _MONTHS.get(m.group(1)[:3].lower())
                d, y = int(m.group(2)), int(m.group(3))
            elif m2:
                mo = _MONTHS.get(m2.group(2)[:3].lower())
                d, y = int(m2.group(1)), int(m2.group(3))
            else:
                return None
            if not mo:
                return None
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def format_phone(text: str) -> str:
    digits = re.sub(r"\D", "", text or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return clean(text)


def normalise(value: str, vtype: str, date_order: str = "mdy"):
    """Return (normalised value, ok).  ``ok`` is False when the text does not fit the type."""
    v = clean(value)
    if not v:
        return None, False
    if vtype == "date":
        iso = parse_date(v, date_order)
        return (iso, True) if iso else (v, False)
    if vtype == "phone":
        p = format_phone(v)
        return p, len(re.sub(r"\D", "", v)) in (10, 11)
    if vtype == "sex":
        low = v.lower()
        if low in ("f", "female", "woman"):
            return "female", True
        if low in ("m", "male", "man"):
            return "male", True
        return low, True
    if vtype == "lower":
        return v.lower(), True
    if vtype == "state":
        return v.upper(), bool(re.fullmatch(r"[A-Za-z]{2}", v))
    if vtype == "zip":
        v = v.replace(" ", "")
        return v, bool(re.fullmatch(r"\d{5}(-\d{4})?", v))
    if vtype == "email":
        v = v.replace(" ", "")  # OCR may split an address at '@' or '.'
        return v.lower(), "@" in v
    if vtype == "year":
        v = _digits_fix(v)
        return v, bool(re.fullmatch(r"\d{4}", v))
    if vtype == "dosage":
        return fix_dosage(v)
    if vtype == "list":
        return split_list(v), True
    return v, True


def split_list(text: str) -> list[str]:
    parts = re.split(r",|;|\band\b", text)
    return [clean(p) for p in parts if clean(p)]


def split_person_name(full: str) -> tuple[str | None, str | None]:
    """'Rivera, Maria L.' -> ('Maria', 'Rivera');  'Maria L. Rivera' -> ('Maria', 'Rivera')."""
    full = clean(full)
    if not full:
        return None, None
    if "," in full:
        last, rest = full.split(",", 1)
        firsts = [w for w in rest.split() if len(w.rstrip(".")) > 1]
        return (firsts[0] if firsts else None), clean(last)
    words = [w for w in full.split() if len(w.rstrip(".")) > 1]
    if len(words) >= 2:
        return words[0], words[-1]
    return (words[0] if words else None), None


def name_key(name: str | None) -> str:
    n = (name or "").lower()
    n = re.sub(r"^/s/\s*", "", n)
    n = re.sub(r"\b(dr|mr|mrs|ms|md|do|jr|sr)\b\.?", " ", n)
    n = re.sub(r"[^a-z ]", " ", n)
    words = [w for w in n.split() if len(w) > 1]
    return " ".join(words)


def same_person(a: str | None, b: str | None) -> bool:
    ka, kb = name_key(a), name_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    wa, wb = set(ka.split()), set(kb.split())
    return len(wa & wb) >= 2 or (ka.split()[0] == kb.split()[0] and ka.split()[-1] == kb.split()[-1])


def display_date(iso: str | None) -> str:
    if not iso:
        return ""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", iso)
    return f"{m.group(2)}/{m.group(3)}/{m.group(1)}" if m else iso


# --------------------------------------------------------------------------- OCR-style confusions
_DIGIT_LIKE = str.maketrans({"o": "0", "O": "0", "l": "1", "I": "1", "|": "1"})
_UNITS = {"meg": "mcg", "mcq": "mcg", "rng": "mg", "mq": "mg", "rnl": "ml", "lU": "IU", "1U": "IU", "iu": "IU"}
_DOSE = re.compile(r"^(?P<num>[\dOoIl|.,/]+)\s*(?P<unit>[A-Za-z%]+)?(?P<rest>.*)$")


def _digits_fix(text: str) -> str:
    """Letters that OCR confuses with digits, fixed only inside a token that already has a digit."""
    return " ".join(w.translate(_DIGIT_LIKE) if re.search(r"\d", w) and re.fullmatch(r"[\dOoIl|.,/-]+", w) else w
                    for w in text.split())


def fix_dosage(text: str):
    """'75 meg' -> '75 mcg', '4o mg' -> '40 mg'.  Returns (value, looks_like_a_dose)."""
    m = _DOSE.match(text.strip())
    if not m or not re.search(r"\d", m.group("num")):
        return text, False
    num = m.group("num").translate(_DIGIT_LIKE)
    unit = m.group("unit") or ""
    unit = _UNITS.get(unit, _UNITS.get(unit.lower(), unit))
    value = clean(f"{num} {unit}{m.group('rest')}")
    ok = bool(re.match(r"^[\d.,/]+\s*(mg|mcg|g|ml|iu|units?|puffs?|tabs?|tablets?|caps?|capsules?|drops?|%|meq|mmol)\b",
                       value, re.I))
    return value, ok
