"""Document types and their key facts.

A profile names a kind of document (invoice, receipt, bank statement, payslip, ...): the
words that identify it, and its *key facts* with the labels they are printed under.
Profiles add meaning to the template-free reading of any document: the type is a label
(nothing is read differently because of it), and each key fact points at the field,
table cell or line it came from, with the printed label and the page box.

Key facts are taken, in this order of trust:
  1. a labelled value whose label is one of the fact's names ("Total Due: $307.80");
  2. a line that starts with the fact's name and ends with a value of the fact's kind,
     with no colon ("TOTAL   9.00" on a receipt);
  3. for the issuer (merchant, seller, sender), the document's first line, when it reads
     like an organisation's name.
A fact found more than one way with different values, or found only by a weaker rule
where doubt remains, is sent for review rather than picked silently.
"""
from __future__ import annotations

import re

from .normalize import parse_date
from .template import canon_tokens

MONEY = r"(?:[A-Z]{3}|RM|Rp\.?|Rs\.?|[$€£¥₹])?\s*-?\d{1,3}(?:[,.\s]\d{3})*(?:[.,]\d{1,2})?|-?\d+(?:[.,]\d{1,2})?"
DATE_RX = (r"\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}[\s\-][A-Za-z]{3,9}[\s\-,]+\d{2,4}"
           r"|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}")

# kind -> (value pattern, kind words)
KINDS = {"money": MONEY, "date": DATE_RX, "text": None, "id": r"[A-Z0-9][A-Z0-9/\-#.]{2,}"}

PROFILES: dict[str, dict] = {
    "invoice": {
        "words": ["invoice", "tax invoice", "bill to", "amount due", "total due", "invoice no", "invoice number",
                  "remit to", "due date", "balance due", "invoice date", "ship to", "sold to"],
        "facts": {
            "invoice_number": ("id", ["invoice number", "invoice no", "invoice #", "invoice", "inv no", "bill no",
                                      "bill number", "document no", "reference"]),
            "invoice_date": ("date", ["invoice date", "date of issue", "issue date", "date issued", "billing date", "date"]),
            "due_date": ("date", ["due date", "payment due", "due by", "pay by"]),
            "seller": ("text", ["from", "seller", "vendor", "supplier", "sold by", "issued by"]),
            "buyer": ("text", ["bill to", "billed to", "customer", "client", "sold to", "invoice to", "buyer"]),
            "subtotal": ("money", ["subtotal", "sub total", "net amount", "total before tax", "total excl tax"]),
            "tax": ("money", ["tax", "vat", "gst", "sales tax", "tax amount"]),
            "total": ("money", ["total due", "amount due", "balance due", "grand total", "total amount", "total",
                                "invoice total", "amount payable", "total payable"]),
        },
    },
    "receipt": {
        "words": ["receipt", "cashier", "change", "cash", "thank you", "subtotal", "total", "qty", "tax invoice",
                  "gst", "rounding", "visa", "mastercard", "tendered", "member"],
        "facts": {
            "merchant": ("text", []),
            "receipt_number": ("id", ["receipt no", "receipt number", "receipt #", "bill no", "invoice no", "doc no",
                                      "transaction no", "trans no", "order no", "check no"]),
            "date": ("date", ["date", "date time", "transaction date"]),
            "subtotal": ("money", ["subtotal", "sub total", "sub-total"]),
            "tax": ("money", ["tax", "gst", "vat", "service tax", "service charge"]),
            "total": ("money", ["grand total", "total amount", "total rm", "total", "net total", "amount due",
                                "total incl gst", "total inclusive gst", "total payable", "nett total", "amount"]),
            "payment_method": ("text", ["payment method", "paid by", "payment", "tender"]),
        },
    },
    "bank statement": {
        "words": ["statement", "account statement", "opening balance", "closing balance", "account number",
                  "statement period", "beginning balance", "ending balance", "transactions", "withdrawal", "deposit"],
        "facts": {
            "account_holder": ("text", ["account holder", "customer name", "account name", "name"]),
            "account_number": ("id", ["account number", "account no", "account", "acct no", "account reference"]),
            "statement_period": ("text", ["statement period", "period", "statement date"]),
            "opening_balance": ("money", ["opening balance", "beginning balance", "previous balance", "balance brought forward"]),
            "closing_balance": ("money", ["closing balance", "ending balance", "new balance", "balance carried forward"]),
        },
    },
    "payslip": {
        "words": ["payslip", "pay slip", "pay stub", "earnings", "deductions", "net pay", "gross pay", "pay period",
                  "salary", "employee id"],
        "facts": {
            "employee_name": ("text", ["employee name", "employee", "name"]),
            "employee_id": ("id", ["employee id", "employee no", "emp id", "staff id", "employee number"]),
            "pay_period": ("text", ["pay period", "period", "month"]),
            "pay_date": ("date", ["pay date", "payment date", "date paid"]),
            "gross_pay": ("money", ["gross pay", "gross earnings", "gross salary", "total earnings"]),
            "net_pay": ("money", ["net pay", "net salary", "take home pay", "net amount"]),
        },
    },
    "utility bill": {
        "words": ["electricity", "water", "gas", "meter", "kwh", "usage", "consumption", "service address",
                  "billing period", "utility", "internet", "broadband", "bill"],
        "facts": {
            "account_number": ("id", ["account number", "customer account", "account no", "consumer number",
                                      "connection number", "service number"]),
            "service_address": ("text", ["service address", "supply address", "premises address", "address"]),
            "billing_period": ("text", ["billing period", "bill period", "service period", "billing month"]),
            "meter_number": ("id", ["meter number", "meter no", "meter id"]),
            "usage": ("text", ["usage", "consumption", "units consumed", "kwh used"]),
            "amount_due": ("money", ["amount due", "total due", "total amount due", "amount payable", "bill amount"]),
            "due_date": ("date", ["due date", "pay by", "payment due"]),
        },
    },
    "lab report": {
        "words": ["laboratory", "lab report", "test results", "reference range", "specimen", "collected",
                  "result", "units", "pathology"],
        "facts": {
            "patient_name": ("text", ["patient name", "patient", "name"]),
            "patient_id": ("id", ["mrn", "patient id", "medical record number", "patient number"]),
            "collected": ("date", ["collected", "collection date", "date collected", "specimen collected"]),
            "ordering_physician": ("text", ["ordering physician", "ordered by", "physician", "referring physician"]),
        },
    },
    "prescription": {
        "words": ["prescription", "rx", "prescriber", "dispense", "refills", "sig", "pharmacy"],
        "facts": {
            "patient_name": ("text", ["patient", "patient name", "name"]),
            "prescriber": ("text", ["prescriber", "prescribing physician", "doctor", "physician"]),
            "date": ("date", ["date", "date written", "prescription date"]),
        },
    },
    "discharge summary": {
        "words": ["discharge summary", "discharge", "admission date", "discharge date", "attending", "diagnosis",
                  "hospital course"],
        "facts": {
            "patient_name": ("text", ["patient name", "patient", "name"]),
            "admission_date": ("date", ["admission date", "date of admission", "admitted"]),
            "discharge_date": ("date", ["discharge date", "date of discharge", "discharged"]),
            "attending_physician": ("text", ["attending physician", "attending", "consultant", "physician"]),
            "diagnosis": ("text", ["diagnosis", "principal diagnosis", "discharge diagnosis", "final diagnosis"]),
        },
    },
    "purchase order": {
        "words": ["purchase order", "po number", "order date", "ship to", "vendor", "delivery date"],
        "facts": {
            "po_number": ("id", ["po number", "purchase order no", "purchase order number", "po no", "po #", "order number"]),
            "order_date": ("date", ["order date", "date", "po date"]),
            "vendor": ("text", ["vendor", "supplier", "seller"]),
            "ship_to": ("text", ["ship to", "deliver to", "delivery address"]),
            "total": ("money", ["order total", "total", "total amount", "grand total"]),
        },
    },
    "contract": {
        "words": ["agreement", "contract", "party", "parties", "governing law", "term", "effective date",
                  "termination", "hereby", "whereas", "witness"],
        "facts": {
            "effective_date": ("date", ["effective date", "agreement date", "dated", "date"]),
            "parties": ("text", ["parties", "party", "provider", "client", "between"]),
            "term": ("text", ["term", "duration", "contract period"]),
            "governing_law": ("text", ["governing law", "jurisdiction", "applicable law"]),
        },
    },
    "letter": {
        "words": ["dear", "sincerely", "yours faithfully", "kind regards", "regards", "yours truly", "respectfully"],
        "facts": {"date": ("date", ["date"]), "recipient": ("text", ["to", "dear"]),
                  "subject": ("text", ["subject", "re", "regarding"]), "sender": ("text", ["from"])},
    },
    "memo": {
        "words": ["memorandum", "memo", "interoffice", "inter office"],
        "facts": {"to": ("text", ["to"]), "from": ("text", ["from"]), "date": ("date", ["date"]),
                  "subject": ("text", ["subject", "re", "regarding"])},
    },
    "email": {
        "words": ["from:", "sent:", "to:", "subject:", "cc:", "original message", "forwarded", "@", "reply"],
        "facts": {"from": ("text", ["from"]), "to": ("text", ["to"]), "date": ("date", ["date", "sent"]),
                  "subject": ("text", ["subject"])},
    },
    "resume": {
        "words": ["resume", "curriculum vitae", "experience", "education", "skills", "employment history",
                  "objective", "references", "qualifications", "professional experience"],
        "facts": {"name": ("text", []), "email": ("text", ["email", "e-mail"]), "phone": ("text", ["phone", "mobile", "tel"]),
                  "location": ("text", ["location", "address", "city"])},
    },
    "meeting minutes": {
        "words": ["minutes", "meeting", "attendees", "present", "agenda", "action items", "chair", "absent", "apologies"],
        "facts": {"meeting": ("text", ["meeting", "committee"]), "date": ("date", ["date", "meeting date"]),
                  "chair": ("text", ["chair", "chairperson", "chaired by"]), "attendees": ("text", ["attendees", "present"])},
    },
    "insurance": {
        "words": ["policy", "insured", "premium", "claim", "coverage", "beneficiary", "deductible", "policyholder",
                  "insurance"],
        "facts": {"policy_number": ("id", ["policy number", "policy no", "policy #", "policy"]),
                  "claim_number": ("id", ["claim number", "claim no", "claim #"]),
                  "insured": ("text", ["insured", "policyholder", "policy holder", "insured name"]),
                  "premium": ("money", ["premium", "premium amount", "total premium"])},
    },
    "tax form": {
        "words": ["internal revenue service", "irs", "tax year", "taxpayer", "social security number", "employer identification",
                  "form w-", "1040", "return", "department of the treasury"],
        "facts": {"taxpayer_name": ("text", ["name", "taxpayer name", "your first name", "name of taxpayer"]),
                  "tax_year": ("text", ["tax year", "year"])},
    },
    "referral": {
        "words": ["referral", "referring physician", "referred to", "reason for referral", "referred by"],
        "facts": {"patient_name": ("text", ["patient", "patient name", "name"]),
                  "referring_physician": ("text", ["referring physician", "referred by", "from"]),
                  "reason": ("text", ["reason for referral", "reason"])},
    },
    "questionnaire": {
        "words": ["questionnaire", "survey", "please check", "please circle", "how often", "how satisfied",
                  "strongly agree", "disagree", "rate", "screening", "over the last 2 weeks"],
        "facts": {},
    },
    "scientific publication": {
        "words": ["abstract", "introduction", "references", "et al", "journal", "methods", "results", "discussion",
                  "conclusion", "doi", "vol", "university"],
        "facts": {},
    },
    "report": {
        "words": ["report", "summary", "findings", "recommendations", "conclusion", "project", "objective",
                  "results", "analysis", "prepared by"],
        "facts": {"date": ("date", ["date", "report date"]), "prepared_by": ("text", ["prepared by", "author"])},
    },
    "specification": {
        "words": ["specification", "specifications", "spec", "tolerance", "dimensions", "material", "standard",
                  "requirements", "parameter", "weight", "length", "pressure drop"],
        "facts": {},
    },
    "budget": {
        "words": ["budget", "fiscal year", "expenses", "expenditures", "variance", "actual", "forecast",
                  "allocation", "total costs", "ytd"],
        "facts": {},
    },
    "news article": {
        "words": ["said", "according to", "reported", "news", "press", "associated press", "reuters", "times",
                  "daily", "editor", "journal"],
        "facts": {},
    },
    "advertisement": {
        "words": ["free", "call now", "offer", "sale", "save", "new", "buy", "limited", "only", "order now",
                  "visit", "discover", "introducing"],
        "facts": {},
    },
    "presentation": {
        "words": ["slide", "agenda", "overview", "objectives", "key points", "next steps", "q&a", "questions"],
        "facts": {},
    },
    "form": {
        "words": ["signature", "please print", "please complete", "date of birth", "name", "address", "phone",
                  "form", "applicant", "check one"],
        "facts": {"name": ("text", ["name", "full name", "applicant name"]), "date": ("date", ["date"])},
    },
}


def _norm_text(text: str) -> str:
    t = re.sub(r"([:@#])", r" \1 ", (text or "").lower())
    return " " + " ".join(re.sub(r"[^a-z0-9#@:]+", " ", t).split()) + " "


def classify(head: str, body: str, n_fields: int = 0, n_words: int = 0) -> tuple[str | None, str, float]:
    """(type, basis, score) from the first page's headings and words.  Headings count
    three times; a document with many labelled fields and nothing more specific is a form."""
    heads, words = _norm_text(head), _norm_text(body)
    best, best_score, basis = None, 0.0, []
    for dtype, prof in PROFILES.items():
        score, found = 0.0, []
        for w in prof["words"]:
            k = _norm_text(w)
            if k.strip() and k in heads:
                score += 3
                found.append(w)
            elif k.strip() and k in words:
                score += 1 if len(k.split()) == 1 else 1.5
                found.append(w)
        if dtype == "form":
            score = min(score, 2) + (2 if n_fields >= 6 else 0)
        if dtype in ("advertisement", "news article"):
            score *= 0.6  # their words are common elsewhere
        if score > best_score:
            best, best_score, basis = dtype, score, found
    if best is None or best_score < 2:
        if n_words < 15:
            return None, "almost no text on the first page", 0.0
        return None, "nothing on the first page names a document type", 0.0
    return best, "words on page 1: " + ", ".join(f"'{w}'" for w in basis[:5]), best_score


# --------------------------------------------------------------------------- key facts
def _canon(text: str) -> list[str]:
    return canon_tokens(text or "")


def _label_match(label: str, aliases: list[str]) -> tuple[int, str] | None:
    """(strength, alias) - 2: the label is the alias; 1: the label starts with it."""
    lw = _canon(label)
    if not lw:
        return None
    best = None
    for a in aliases:
        aw = _canon(a)
        if not aw:
            continue
        if lw == aw:
            return 2, a
        if lw[:len(aw)] == aw and len(lw) <= len(aw) + 3 and best is None:
            best = (1, a)
    return best


def _fits(kind: str, value: str) -> bool:
    v = str(value or "").strip()
    if not v:
        return False
    if kind == "money":
        return bool(re.search(r"\d", v)) and bool(re.fullmatch(rf"\s*(?:{MONEY})(?:\s*[A-Z]{{3}})?\s*", v)) or \
            bool(re.search(r"\d[\d,.]*\d|\d", v) and len(re.sub(r"[\d.,\s$€£¥₹RMUSDEURINRp-]", "", v)) <= 3)
    if kind == "date":
        return bool(parse_date(v, "mdy") or parse_date(v, "dmy") or re.search(DATE_RX, v))
    if kind == "id":
        return bool(re.search(r"\d", v)) and len(v) <= 40
    return len(v) <= 200


def _first_line_org(doc: dict) -> tuple[str, dict] | None:
    """The document's first line when it names an organisation: only the top of page 1,
    before any labelled field."""
    pages = doc["document"].get("pages") or [{}]
    height = pages[0].get("height") or 792
    for b in doc.get("blocks", []):
        if b.get("page") != 1:
            continue
        if b.get("type") in ("field", "table", "question") or (b.get("bbox") and b["bbox"][1] > 0.3 * height):
            break
        if b.get("type") not in ("heading", "text"):
            continue
        t = (b.get("text") or "").strip()
        if not t or re.fullmatch(r"[\W\d_]+", t):
            continue
        low = t.lower()
        if re.search(r"\b(invoice|receipt|statement|bill|tax|official|copy|page|sample|synthetic|ocr|report)\b", low) \
                and not re.search(r"\b(ltd|llc|inc|corp|sdn|bhd|co|company|gmbh|plc|enterprise|trading|store|restaurant|hotel|clinic|hospital|bank)\b", low):
            continue
        return t, b
    return None


def key_facts(doc: dict) -> dict:
    """The key facts of the document's type, each with its source."""
    dtype = doc["document"].get("document_type")
    prof = PROFILES.get(dtype or "")
    if not prof or not prof["facts"]:
        return {}
    attrs = []
    for e in doc["entities"].values():
        if e["type"] in ("Section",):
            continue
        for k, a in e["attributes"].items():
            if a.get("value") in (None, "") or not a.get("field_label"):
                continue
            attrs.append((e, k, a))
    attrs.sort(key=lambda x: (x[2].get("page") or 0, (x[2].get("bbox") or [0, 0])[1], (x[2].get("bbox") or [0])[0]))
    lines = [b for b in doc.get("blocks", []) if b.get("type") in ("text", "heading") and b.get("text")]
    out: dict = {}
    for fact, (kind, aliases) in prof["facts"].items():
        cands = []
        for e, k, a in attrs:
            m = _label_match(a["field_label"], aliases)
            if m and _fits(kind, a.get("raw") or a["value"]):
                cands.append((m[0], aliases.index(m[1]), e, k, a))
        if cands:
            cands.sort(key=lambda c: (-c[0], c[1]))
            top = cands[0]
            same_rank = [c for c in cands if c[0] == top[0] and c[1] == top[1]]
            values = {str(c[4].get("raw") or c[4]["value"]).strip().lower() for c in same_rank}
            a = top[4]
            status = a.get("status", "valid")
            notes = []
            if len(values) > 1:
                status = "needs_review"
                notes.append(f"{len(values)} different values are printed under '{top[4]['field_label']}'")
            out[fact] = {"value": a.get("value"), "raw": a.get("raw"), "label": a["field_label"], "entity": top[2]["id"],
                         "attribute": top[3], "page": a.get("page"), "bbox": a.get("bbox"), "method": "labelled value",
                         "status": status, "notes": notes}
            continue
        if kind in ("money", "date", "id") and aliases:
            hits = []
            for b in lines:
                txt = b["text"]
                for alias in aliases:
                    ap = r"\s*".join(re.escape(w) for w in alias.split())
                    pat = rf"(?<![A-Za-z]){ap}\b[\s:.#]*({KINDS[kind]})"
                    for mm in re.finditer(pat, txt, flags=re.I):
                        before = txt[max(0, mm.start() - 12):mm.start()].lower()
                        if fact == "total" and re.search(r"(sub|qty|tax|items?|discount|savings|excl)\W*$", before):
                            continue
                        hits.append((aliases.index(alias), mm.group(1).strip(), b, alias))
                    if hits:
                        break
            if hits:
                hits.sort(key=lambda h: h[0])
                best = [h for h in hits if h[0] == hits[0][0]]
                vals = {re.sub(r"\s+", "", h[1]) for h in best}
                h = best[-1] if fact in ("total", "amount_due", "closing_balance") else best[0]
                out[fact] = {"value": h[1], "label": h[3], "page": h[2].get("page"), "bbox": h[2].get("bbox"),
                             "method": "line starting with the label", "status": "valid" if len(vals) == 1 else "needs_review",
                             "notes": [] if len(vals) == 1 else [f"the line '{h[3]}' appears with {len(vals)} different values"]}
                continue
        if fact in ("merchant", "seller", "name") or (fact == "sender" and dtype == "letter"):
            org = _first_line_org(doc)
            if org:
                t, b = org
                out[fact] = {"value": t, "label": "first line of the document", "page": b.get("page"), "bbox": b.get("bbox"),
                             "method": "document heading", "status": "valid" if fact != "seller" else "needs_review",
                             "notes": [] if fact != "seller" else ["taken from the first line; confirm it is the seller"]}
    return out
