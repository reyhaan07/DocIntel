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
DATE_RX = (r"\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\.?[\s\-][^\W\d_]{3,9}\.?[\s\-,]+\d{2,4}"
           r"|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}")

# kind -> (value pattern, kind words)
KINDS = {"money": MONEY, "date": DATE_RX, "text": None, "id": r"[A-Z0-9][A-Z0-9/\-#.]{2,}"}

PROFILES: dict[str, dict] = {
    "invoice": {
        "words": ["invoice", "tax invoice", "bill to", "amount due", "total due", "invoice no", "invoice number",
                  "remit to", "due date", "balance due", "invoice date", "ship to", "sold to"],
        "facts": {
            "invoice_number": ("id", ["invoice number", "invoice no", "invoice #", "invoice", "inv no", "bill no",
                                      "bill number", "document no", "reference", "rechnungsnr", "rechnungsnummer",
                                      "rechnung nr", "facture no", "numero de facture", "factura no", "factura n",
                                      "numero de factura", "fattura n", "factuurnummer"]),
            "invoice_date": ("date", ["invoice date", "date of issue", "issue date", "date issued", "billing date", "date",
                                      "rechnungsdatum", "datum", "date de facture", "fecha de factura", "fecha",
                                      "data fattura", "factuurdatum"]),
            "due_date": ("date", ["due date", "payment due", "due by", "pay by"]),
            "seller": ("text", ["from", "seller", "vendor", "supplier", "sold by", "issued by"]),
            "buyer": ("text", ["bill to", "billed to", "customer", "client", "sold to", "invoice to", "buyer"]),
            "subtotal": ("money", ["subtotal", "sub total", "net amount", "total before tax", "total excl tax"]),
            "tax": ("money", ["tax", "vat", "gst", "sales tax", "tax amount"]),
            "total": ("money", ["total due", "amount due", "balance due", "grand total", "total amount", "total",
                                "invoice total", "amount payable", "total payable", "total for this invoice",
                                "gesamtbetrag", "rechnungsbetrag", "endbetrag", "montant total", "total ttc",
                                "importe total", "totale"]),
        },
    },
    "receipt": {
        "words": ["receipt", "cashier", "change", "cash", "thank you", "subtotal", "total", "qty", "tax invoice",
                  "gst", "rounding", "visa", "mastercard", "tendered", "member"],
        "facts": {
            "merchant": ("text", []),
            "receipt_number": ("id", ["receipt no", "receipt number", "receipt #", "bill no", "invoice no", "doc no",
                                      "transaction no", "trans no", "order no", "check no"]),
            "date": ("date", ["date", "date time", "transaction date", "bill date", "trans date", "receipt date",
                              "sales date", "doc date", "invoice date", "tarikh"]),
            "subtotal": ("money", ["subtotal", "sub total", "sub-total"]),
            "tax": ("money", ["tax", "gst", "vat", "service tax", "service charge"]),
            "total": ("money", ["grand total", "total amount", "total rm", "total", "net total", "amount due",
                                "total incl gst", "total inclusive gst", "total payable", "nett total", "rounded total",
                                "total rounded", "jumlah", "total bayar"]),
            "cash": ("money", ["cash", "cash tendered", "tendered", "tunai", "amount tendered", "paid"]),
            "change": ("money", ["change", "change due", "kembali", "kembalian", "balance change"]),
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
        "words": ["distribution", "copies to", "attached", "please"],
        "facts": {"to": ("text", ["to"]), "from": ("text", ["from"]), "date": ("date", ["date"]),
                  "subject": ("text", ["subject", "re", "regarding"])},
    },
    "email": {
        "words": ["forwarded", "reply", "attachment", "attachments", "importance", "inbox"],
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


# Phrases that *name* a document type (a title saying "Invoice", a closing "Sincerely").
# They outweigh the supporting words in PROFILES, which other types share.
NAMES: dict[str, list[str]] = {
    "invoice": ["invoice", "tax invoice", "invoice no", "invoice number", "invoice date", "commercial invoice",
                "factura", "facture", "rechnung", "fattura"],
    "receipt": ["receipt", "official receipt", "cash receipt", "sales receipt", "payment receipt", "kembalian",
                "tunai", "recibo"],
    "bank statement": ["bank statement", "account statement", "statement of account", "opening balance",
                       "closing balance"],
    "payslip": ["payslip", "pay slip", "pay stub", "salary slip", "earnings statement", "pay statement"],
    "utility bill": ["electricity bill", "water bill", "gas bill", "utility bill", "phone bill", "energy bill",
                     "meter reading"],
    "lab report": ["laboratory report", "lab report", "pathology report", "laboratory results", "reference range"],
    "prescription": ["prescription", "rx"],
    "discharge summary": ["discharge summary", "hospital course"],
    "purchase order": ["purchase order", "po number"],
    "contract": ["agreement", "contract", "whereas", "governing law"],
    "letter": ["dear", "sincerely", "yours sincerely", "yours faithfully", "very truly yours", "yours truly",
               "cordially", "respectfully yours", "best regards", "kind regards"],
    "memo": ["memorandum", "memo", "interoffice", "inter office", "internal correspondence", "office memo"],
    "email": ["original message", "forwarded message", "sent :", "mailto"],
    "resume": ["resume", "curriculum vitae", "work experience", "employment history", "professional experience"],
    "meeting minutes": ["minutes", "minutes of meeting", "meeting minutes", "action items"],
    "insurance": ["insurance policy", "certificate of insurance", "policy schedule", "claim form", "policyholder",
                  "policy number"],
    "tax form": ["internal revenue service", "tax return", "department of the treasury", "taxpayer"],
    "referral": ["referral", "reason for referral", "referred to"],
    "questionnaire": ["questionnaire", "survey", "screener", "respondent", "interviewer"],
    "scientific publication": ["abstract", "et al", "doi", "journal of", "proceedings"],
    "report": ["report", "final report", "progress report", "status report", "annual report"],
    "specification": ["specification", "specifications", "spec sheet", "data sheet", "product specification"],
    "budget": ["budget", "budget request", "proposed budget"],
    "press release": ["press release", "news release", "for immediate release"],
    "presentation": ["presentation"],
    "fax cover sheet": ["facsimile", "fax cover", "cover sheet", "fax transmittal", "facsimile transmission",
                        "telecopy", "pages including"],
    "form": ["application form", "registration form", "request form", "form"],
}
PROFILES["fax cover sheet"] = {"words": ["fax", "pages", "fax no", "fax number", "number of pages", "urgent"],
                               "facts": {"to": ("text", ["to"]), "from": ("text", ["from"]), "date": ("date", ["date"]),
                                         "fax_number": ("text", ["fax", "fax no", "fax number"])}}
PROFILES["press release"] = {"words": ["contact", "announced", "said", "today", "media", "press"], "facts": {
    "date": ("date", ["date", "for immediate release"]), "contact": ("text", ["contact", "media contact"])}}
# the header lines memos and e-mails share
_HEADER_WORDS = ["to :", "from :", "subject :", "date :", "re :", "cc :"]
_EMAIL_FROM = re.compile(r"(?im)^\W*(?:from|to|sent|cc)\s*:.{0,80}?[\w.+-]+@[\w-]+\.[\w.]+"
                         r"|^\W*from\s*:.{0,60}?\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)\b")
_SALUTATION = re.compile(r"(?im)^\W{0,3}dear\s+(?:mr|mrs|ms|dr|sir|madam|[A-Z][a-z]+)")


def _norm_text(text: str) -> str:
    t = re.sub(r"([:@#|])", r" \1 ", (text or "").lower().replace("\n", " | "))
    return " " + " ".join(re.sub(r"[^a-z0-9#@:|]+", " ", t).split()) + " "


def classify(head: str, body: str, n_fields: int = 0, n_words: int = 0) -> tuple[str | None, str, float]:
    """(type, basis, score) from the first page's title/headings and words.

    A phrase that names a type counts 4 in a title or heading and 2 in the text; a
    supporting word counts 2 in a heading and 1 (1.5 for a phrase) in the text.  The
    header lines memos and e-mails share (To:, From:, Subject:) count for both, and an
    e-mail address in such a line, or a 'Sent:' line, makes it an e-mail.  A document
    with many labelled fields and nothing more specific is a form."""
    heads, words = _norm_text(head), _norm_text(body)
    header_hits = [w for w in _HEADER_WORDS if _norm_text(w) in words]
    email_addr = bool(_EMAIL_FROM.search(body or ""))
    salutation = bool(_SALUTATION.search(body or ""))
    best, best_score, basis = None, 0.0, []
    scores: dict[str, float] = {}
    for dtype, prof in PROFILES.items():
        score, found = 0.0, []
        for w in NAMES.get(dtype, []):
            k = _norm_text(w)
            if k in heads:
                score += 4
                found.append(w)
            elif k in words:
                score += 2
                found.append(w)
        for w in prof["words"]:
            k = _norm_text(w)
            if not k.strip() or w in NAMES.get(dtype, []) or w in _HEADER_WORDS or w == "@":
                continue
            if k in heads:
                score += 2
                found.append(w)
            elif k in words:
                score += 1 if len(k.split()) == 1 else 1.5
                found.append(w)
        if dtype in ("memo", "email") and len(header_hits) >= 2:
            score += len(header_hits)
            found += header_hits
        if dtype == "email" and email_addr:
            score += 4
            found.append("an e-mail header line")
        if dtype == "letter" and salutation:
            score += 3
            found.append("a 'Dear ...' salutation")
        if dtype == "form":
            score = min(score, 3) + (2 if n_fields >= 6 else 0)
        if dtype in ("advertisement", "news article"):
            score *= 0.6  # their words are common elsewhere
        scores[dtype] = score
        if score > best_score:
            best, best_score, basis = dtype, score, found
    if best is None or best_score < 2:
        if n_words < 15:
            return None, "almost no text on the first page", 0.0
        return None, "nothing on the first page names a document type", 0.0
    return best, "words on page 1: " + ", ".join(f"'{w}'" for w in basis[:5]), best_score


def carried_type(head: str, body: str, best: str | None, n_fields: int = 0, n_words: int = 0) -> str | None:
    """A business document carried by an e-mail, letter or memo (an invoice in the body
    of an e-mail): its type, when its own words are strong, so its key facts are read too."""
    if best not in CARRIERS:
        return None
    heads, words = _norm_text(head), _norm_text(body)
    out, top = None, 0.0
    for dtype in CONTENT_TYPES:
        score = sum(4 if _norm_text(w) in heads else 2 if _norm_text(w) in words else 0 for w in NAMES.get(dtype, []))
        score += sum(1 for w in PROFILES[dtype]["words"] if _norm_text(w) in words)
        if score >= 5 and score > top:
            out, top = dtype, score
    return out


CARRIERS = ("email", "letter", "memo")
CONTENT_TYPES = ("invoice", "receipt", "bank statement", "payslip", "utility bill", "lab report", "prescription",
                 "discharge summary", "purchase order", "insurance", "referral")


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


_CUR = r"(?:RM|Rp\.?|Rs\.?|USD|EUR|GBP|IDR|INR|MYR|SGD|AUD|CAD|[$€£¥₹])"
# a plain number without separators is an amount up to six digits (longer runs, or
# runs with leading zeros, are numbers of a register or an account)
_AMOUNT_TOKEN = re.compile(rf"^\(?{_CUR}?\s*(-?)(\d{{1,3}}(?:[,.]\d{{3}})+|0|[1-9]\d{{0,5}})([.,]\d{{2}})?{_CUR}?\)?[:;,.]?$")
# words that turn 'total ...' into another line (a tax, a count, a payment)
_NOT_TOTAL = {"gst", "tax", "vat", "qty", "quantity", "items", "item", "discount", "disc", "saving", "savings", "change",
              "cash", "excl", "excluding", "points", "tendered", "paid", "weight", "units", "pcs", "unit", "before"}


def read_amount(text: str, decimals_expected: bool = False) -> tuple[str, str, list[str]] | None:
    """(value, status, notes) for the money amount a label's line or value gives.

    The amount is the rightmost one; other amounts on the same line, a value with
    no decimals where the document prints cents, and a decimal point OCR dropped
    ('88 17') all send it for review."""
    sep = re.sub(r"(?<![\d.,])(\d{1,3})(?:\s+([.,])\s*|([.,])\s+)(\d{3})(?![\d])", lambda m: m.group(1) + (m.group(2) or m.group(3)) + m.group(4), text or "")
    if sep != (text or ""):  # OCR set a space beside a thousands separator: '70, 000', '385 ,000'
        r = read_amount(sep, decimals_expected)
        if r:
            return r[0], "needs_review", r[2] + [f"read '{(text or '').strip()[:20]}' with a space beside the thousands separator"]
    spaced = re.sub(r"(\d)([.,])\s(\d{2})(?!\d)", r"\1\2\3", text or "")
    if spaced != (text or ""):  # OCR set a space after the decimal point: '68. 87'
        r = read_amount(spaced, decimals_expected)
        if r:
            return r[0], "needs_review", r[2] + [f"read '{(text or '').strip()[:20]}' with a space after the decimal point"]
    whole = re.fullmatch(rf"\(?({_CUR})?\s*(\d{{1,3}}(?:\s\d{{3}})+(?:[.,]\d{{2}})?)\s*({_CUR})?\)?", (text or "").strip())
    if whole:  # '1 036,58': thousands set apart by spaces
        num = whole.group(2).replace(" ", "")
        return (whole.group(1) or "") + num, "needs_review", [f"read '{text.strip()}' as one amount with spaces between thousands"]
    toks = [t for t in re.split(r"\s+", (text or "").strip()) if t]
    # a currency code standing apart from its number ('RM 62.80')
    merged = []
    for t in toks:
        if merged and re.fullmatch(_CUR, merged[-1]) and re.match(r"-?\d", t):
            merged[-1] = merged[-1] + t
        else:
            merged.append(t)
    found = []
    for t in merged:
        m = _AMOUNT_TOKEN.match(t)
        if m:
            found.append((t.strip("():;"), m))
    if not found:
        return None
    notes, status = [], "valid"
    numeric = [t for t in merged if re.search(r"\d", t)]
    if len(found) == 2 and len(numeric) == 2 and not found[0][1].group(3) and not found[1][1].group(3) \
            and re.fullmatch(r"\d{2}", found[1][0]) and re.fullmatch(r"\d{1,6}", found[0][0]):
        return f"{found[0][0]}.{found[1][0]}", "needs_review", [f"read as '{found[0][0]} {found[1][0]}': the decimal point is assumed"]
    tok, m = found[-1]
    if len({re.sub(r"[^\d]", "", f[0]) for f in found}) > 1:
        status = "needs_review"
        notes.append(f"the line holds {len(found)} amounts; the last one is taken")
    if len(numeric) > len(found):
        status = "needs_review"
        notes.append("the line also holds numbers that are not amounts")
    wordy = [t for t in merged if re.search(r"[A-Za-z]{2,}", t) and not _AMOUNT_TOKEN.match(t)
             and not re.fullmatch(rf"\(?{_CUR}\)?[:.]?", t)]
    if wordy:
        status = "needs_review"
        notes.append(f"words next to the amount: {' '.join(wordy)[:30]}")
    if decimals_expected and not m.group(3):
        status = "needs_review"
        notes.append("no cents, while the document's other amounts have them")
    return tok, status, notes


def read_date(text: str) -> tuple[str, str, list[str]] | None:
    text = re.sub(r"\s+,", ",", text or "")  # 'August 3 , 2014'
    m = re.search(DATE_RX, text)
    if not m:
        return None
    v = m.group(0).strip()
    ok = parse_date(v, "mdy") or parse_date(v, "dmy")
    before = (text or "")[max(0, m.start() - 1):m.start()]
    if not ok or re.search(r"[\w*#]", before):
        return v, "needs_review", [f"the date '{(text or '').strip()[:40]}' could not be read cleanly"]
    return v, "valid", []


def _fits(kind: str, value: str) -> bool:
    v = str(value or "").strip()
    if not v:
        return False
    if kind == "money":
        return read_amount(v) is not None
    if kind == "date":
        return read_date(v) is not None
    if kind == "id":
        return bool(re.search(r"\d", v)) and len(v) <= 40
    return len(v) <= 200


_ORG = re.compile(r"\b(ltd|llc|inc|corp|corporation|sdn|bhd|s/?b|co|company|gmbh|plc|enterprise|enterprises|trading|"
                  r"store|stores|restaurant|cafe|hotel|clinic|hospital|bank|pharmacy|mart|market|supermarket|"
                  r"hardware|station|bakery|services|industries|holdings|group|pte|pty|llp|ag|sa|bv|nv|"
                  r"limited|incorporated)\b", re.I)


def _plausible_name(t: str) -> bool:
    letters = re.sub(r"[^A-Za-z]", "", t)
    words = [w for w in re.findall(r"[A-Za-z]{3,}", t)]
    return len(letters) >= 5 and len(letters) >= 0.6 * len(re.sub(r"\s", "", t)) and len(words) >= 1


def amount_value(tok: str) -> float | None:
    m = _AMOUNT_TOKEN.match(str(tok or "").strip())
    if not m:
        return None
    whole = re.sub(r"[,.]", "", m.group(2))
    dec = (m.group(3) or "")[1:]
    try:
        v = float(f"{whole}.{dec}" if dec else whole)
    except ValueError:
        return None
    return -v if m.group(1) else v


def _first_line_org(doc: dict) -> tuple[str, dict, str, list[str]] | None:
    """The organisation the document comes from, from the top of page 1 before any
    labelled field: a line naming a company (Ltd, Sdn Bhd, Inc, Store...) is taken as
    read; otherwise the first line that reads as a name is offered for review."""
    pages = doc["document"].get("pages") or [{}]
    height = pages[0].get("height") or 792
    first = None
    for b in doc.get("blocks", []):
        if b.get("page") != 1:
            continue
        if b.get("type") in ("field", "table", "question") or (b.get("bbox") and b["bbox"][1] > 0.3 * height):
            break
        if b.get("type") not in ("heading", "text"):
            continue
        for t in (b.get("text") or "").split("\n")[:3]:
            t = t.strip()
            if not t or not _plausible_name(t):
                continue
            low = t.lower()
            generic = re.search(r"\b(invoice|receipt|statement|bill|tax|official|copy|page|sample|synthetic|ocr|report|"
                                r"welcome|thank|cash|order|table|date|time)\b", low)
            if _ORG.search(t) and not re.match(r"^(company|co|gst|reg|registration)\b", low):
                if first is not None and first[0] != t:
                    return t, b, "needs_review", [f"a company line, but '{first[0]}' is printed above it"]
                return t, b, "valid", []
            if first is None and not generic:
                first = (t, b)
    if first:
        return first[0], first[1], "needs_review", ["taken from the first line of the document; confirm it names the issuer"]
    return None


_ID_WORDS = {"no", "number", "reg", "registration", "id", "nr", "num", "code", "ref"}
_INCLUSIVE = {"incl", "inclusive", "including", "inc", "with"}


def _label_match_fact(label: str, aliases: list[str], money_total: bool, money: bool = False) -> tuple[int, str] | None:
    m = _label_match(label, aliases)
    if m and m[0] == 1:
        extra = set(_canon(label)[len(_canon(m[1])):])
        if money and extra & _ID_WORDS:
            return None  # 'GST No.' is a registration number, not an amount of tax
        if money_total and extra & _NOT_TOTAL and not extra & _INCLUSIVE:
            return None
    return m


def _decimals_expected(texts: list[str]) -> bool:
    cents = thousands = 0
    for t in texts:
        for tok in re.findall(r"\d[\d,.]*", t):
            if re.search(r"\d[.,]\d{2}$", tok):
                cents += 1
            elif re.search(r"\d[.,]\d{3}$", tok):
                thousands += 1
    return cents >= 2 and cents > thousands


def _alias_pattern(alias: str) -> str:
    # OCR misreads the letters of TOTAL on photos ('TOTAI', 'Tota]', 'T0TAL'); the word is
    # still recognised, and a fact read under a misspelt label goes to review
    words = [r"t[o0]t[a@][l1i|\]]" if w.lower() == "total" else re.escape(w) for w in alias.split()]
    return r"\s*".join(words)


def _after_label(txt: str, alias: str, fact: str):
    """Rest of the line after each occurrence of ``alias`` at a word start."""
    ap = _alias_pattern(alias)
    for mm in re.finditer(rf"(?<![A-Za-z]){ap}\b", txt, flags=re.I):
        before = txt[max(0, mm.start() - 12):mm.start()].lower()
        if fact in ("total", "amount_due", "net_pay", "gross_pay") and \
                re.search(r"(sub|qty|tax|items?|discount|savings|excl|gst|vat)[\W_]*$", before):
            continue
        line_start = txt.rfind("\n", 0, mm.start()) + 1
        if txt[line_start:mm.start()].strip(" :*-.#\t") and fact in ("total", "date", "invoice_date"):
            # the label must start its line ('Payment due date' is not 'date')
            continue
        end = txt.find("\n", mm.end())
        yield txt[mm.end(): end if end >= 0 else len(txt)], mm


def _value_part(rest: str) -> str:
    """The value after a label on a printed line whose pieces are joined by ' | ': the
    first piece that carries a digit, unless another label comes before it."""
    if " | " not in rest:
        return rest
    for piece in rest.split(" | "):
        if re.search(r"\d", piece):
            return piece
        if len(re.findall(r"[A-Za-z]{3,}", re.sub(_CUR, "", piece))) >= 1:
            return ""  # the next label comes first: this one's amount is not on the line
    return ""


def key_facts(doc: dict, printed_lines: list[dict] | None = None) -> dict:
    """The key facts of the document's type, each with its source and a status:
    'valid' when read cleanly, 'needs_review' when anything about it is uncertain.
    ``printed_lines`` are the page's lines as printed (pieces joined by ' | '), so that a
    label and its amount set far apart on one line ('TOTAL ........ 46,000') are read
    together even where the layout put them in separate blocks."""
    dtype = doc["document"].get("document_type")
    prof = PROFILES.get(dtype or "")
    generic = {"date": ("date", ["date", "dated"]),
               "total": ("money", ["grand total", "total amount", "total", "amount due", "total due"])}
    if prof is None:  # nothing names the type: its date and total are still worth stating
        prof = {"facts": generic}
    elif dtype == "form":  # an order or payment form states a total too
        prof = {"facts": {**prof["facts"], "total": generic["total"]}}
    carried = doc["document"].get("carries")
    if carried in PROFILES:
        facts = dict(PROFILES[carried]["facts"])
        facts.update(prof["facts"] if prof else {})
        prof = {"facts": facts}
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
    lines += [dict(ln, printed=True) for ln in printed_lines or []]
    texts = [b["text"] for b in lines] + [str(a.get("raw") or a["value"]) for _, _, a in attrs]
    cents = _decimals_expected(texts)

    def read(kind, text):
        if kind == "money":
            return read_amount(text, cents)
        if kind == "date":
            return read_date(text)
        v = str(text or "").strip()
        if kind == "id":
            # the first whole token that carries a digit and is not a date
            for tok in re.split(r"\s+", v)[:4]:
                tok = tok.strip(".,:;#()")
                if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/\-#._]{2,}", tok) and re.search(r"\d", tok) \
                        and not (parse_date(tok, "mdy") or parse_date(tok, "dmy")) and len(tok) <= 40:
                    return tok, "valid", []
            return None
        return (v, "valid", []) if v and len(v) <= 200 else None

    out: dict = {}
    for fact, (kind, aliases) in prof["facts"].items():
        totalish = kind == "money" and fact in ("total", "amount_due", "net_pay", "gross_pay", "subtotal")
        others = [al for f2, (_, als) in prof["facts"].items() if f2 != fact for al in als]
        cands = []
        for e, k, a in attrs:
            m = _label_match_fact(a["field_label"], aliases, totalish, kind == "money")
            if not m:
                continue
            if m[0] == 1 and (_label_match(a["field_label"], others) or (0,))[0] == 2:
                continue  # 'Invoice Date' names the date, not the invoice number
            r = read(kind, a.get("raw") or a["value"])
            if r:
                cands.append((m[0], aliases.index(m[1]), e, k, a, r))
        if cands:
            cands.sort(key=lambda c: (-c[0], c[1]))
            top = cands[0]
            same_rank = [c for c in cands if c[0] == top[0] and c[1] == top[1]]
            values = {re.sub(r"\s+", "", c[5][0]).lower() for c in same_rank}
            a = top[4]
            value, status, notes = top[5]
            if kind == "date" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(a.get("value") or "")):
                value = a["value"]  # the date as the document's own date order read it
            if a.get("status") and a["status"] != "valid":
                status = a["status"]
            if len(values) > 1:
                status = "needs_review"
                notes = notes + [f"{len(values)} different values are printed under '{a['field_label']}'"]
            out[fact] = {"value": value, "raw": a.get("raw") or a.get("value"), "label": a["field_label"],
                         "entity": top[2]["id"], "attribute": top[3], "page": a.get("page"), "bbox": a.get("bbox"),
                         "method": "labelled value", "status": status, "notes": notes}
            continue
        if totalish:
            row = _total_row(doc, aliases, read)
            if row:
                out[fact] = row
                continue
        if kind in ("money", "date", "id") and aliases:
            hits = []
            for rank, alias in enumerate(aliases):
                for b in lines:
                    for rest, mm in _after_label(b["text"], alias, fact):
                        if b.get("printed"):
                            rest = _value_part(rest)
                            if not rest:
                                continue
                        words = {w.lower() for w in re.findall(r"[A-Za-z]{2,}", rest.split("\n")[0])}
                        if totalish and words & _NOT_TOTAL and not words & _INCLUSIVE:
                            continue
                        if kind == "money" and words & _ID_WORDS and not re.search(r"\d[.,]\d{2}\b", rest):
                            continue
                        lead = re.split(r"\d", rest, maxsplit=1)[0]
                        if len(re.findall(r"[A-Za-z]{3,}", lead)) > 3:
                            continue  # the label is part of a sentence
                        r = read(kind, rest.strip(" :.#\t"))
                        if r:
                            said = re.sub(r"\s+", " ", mm.group(0)).lower()
                            if said.replace(" ", "") != alias.lower().replace(" ", ""):
                                r = (r[0], "needs_review", list(r[2]) + [f"the label was read as '{mm.group(0)}'"])
                            hits.append((rank, r, b, alias))
                if hits:
                    break
            if hits:
                vals = {re.sub(r"\s+", "", h[1][0]) for h in hits}
                h = hits[-1] if fact in ("total", "amount_due", "closing_balance") else hits[0]
                value, status, notes = h[1]
                if len(vals) > 1:
                    status = "needs_review"
                    notes = notes + [f"the line '{h[3]}' appears with {len(vals)} different values"]
                out[fact] = {"value": value, "label": h[3], "page": h[2].get("page"), "bbox": h[2].get("bbox"),
                             "method": "line starting with the label", "status": status, "notes": notes}
                continue
        if kind == "date" and fact == "date":
            seen = []
            sources = [(b["text"], b) for b in lines] + [(str(a.get("raw") or a["value"]), a) for _, _, a in attrs]
            for txt, b in sources:
                for mm in re.finditer(DATE_RX, txt):
                    r = read_date(mm.group(0))
                    if r and r[1] == "valid":
                        seen.append((r[0], b))
            if seen:
                days = {parse_date(v, "dmy") or v for v, _ in seen}
                v, b = seen[0]
                one = len(days) == 1
                scanned = "ocr" in str(doc["document"].get("extraction_method") or "")
                out[fact] = {"value": v, "label": "the date printed on the document", "page": b.get("page"),
                             "bbox": b.get("bbox"), "method": "only date printed" if one else "first date printed",
                             "status": "valid" if one and not scanned else "needs_review",
                             "notes": ([] if one else [f"{len(days)} different dates are printed; the first is taken"])
                             + (["read by OCR with no label to confirm it"] if scanned else [])}
                continue
        if fact in ("merchant", "seller", "name") or (fact == "sender" and dtype == "letter"):
            org = _first_line_org(doc)
            if org:
                t, b, status, notes = org
                if status == "valid" and "ocr" in str(doc["document"].get("extraction_method") or ""):
                    status, notes = "needs_review", notes + ["read by OCR from the top of the page, with no label to "
                                                             "confirm the spelling"]
                if fact == "seller" and status == "valid":
                    status, notes = "needs_review", ["taken from the company named at the top; confirm it is the seller"]
                out[fact] = {"value": t, "label": "top of the document", "page": b.get("page"), "bbox": b.get("bbox"),
                             "method": "document heading", "status": status, "notes": notes}
    _check_sums(out)
    return out


_TOTAL_COLUMNS = ("gross worth", "gross amount", "gross", "total", "amount", "amount due", "total amount", "balance",
                  "line total", "value", "price")


def _total_row(doc: dict, aliases: list[str], read) -> dict | None:
    """A 'Total' row of a table: the amount in its total column ('Gross worth',
    'Amount'); without such a column, the last amount of the row, for review."""
    for e in reversed(list(doc["entities"].values())):
        if e["type"] != "TableRow" or not _label_match(e.get("label") or "", aliases):
            continue
        if _label_match(e.get("label") or "", aliases)[0] != 2:
            continue
        cells = [(k, a) for k, a in e["attributes"].items() if a.get("value") not in (None, "")
                 and str(a.get("value")) != e.get("label")]
        named = [(rank, k, a) for k, a in cells for rank, col in enumerate(_TOTAL_COLUMNS)
                 if _canon(a.get("field_label") or "") == _canon(col)]
        if named:
            _, k, a = min(named, key=lambda x: x[0])
            r = read("money", a.get("raw") or a["value"])
            if r:
                status, notes = r[1], list(r[2])
                v = amount_value(r[0])
                rest = [amount_value(read("money", b.get("raw") or b["value"])[0]) for k2, b in cells
                        if k2 != k and "%" not in str(b.get("value")) and read("money", b.get("raw") or b["value"])]
                if v is not None and any(x is not None and x > v + 0.011 for x in rest):
                    status = "needs_review"
                    notes.append("smaller than another amount in its own row")
                return {"value": r[0], "raw": a.get("raw") or a.get("value"), "label": f"{e['label']} / {a.get('field_label')}",
                        "entity": e["id"], "attribute": k, "page": a.get("page"), "bbox": a.get("bbox"),
                        "method": "table row", "status": status, "notes": notes}
        money = [(k, a, read("money", a.get("raw") or a["value"])) for k, a in cells]
        money = [m for m in money if m[2]]
        if money:
            k, a, r = money[-1]
            return {"value": r[0], "raw": a.get("raw") or a.get("value"), "label": f"{e['label']} / {a.get('field_label')}",
                    "entity": e["id"], "attribute": k, "page": a.get("page"), "bbox": a.get("bbox"),
                    "method": "table row", "status": "needs_review",
                    "notes": r[2] + ["the last amount of the total row is taken"]}
    return None


def _like(example: str, value: float) -> str:
    """An amount written the way the document writes its amounts ('50.000' -> '31.500')."""
    m = _AMOUNT_TOKEN.match(str(example).strip())
    dec = m.group(3) if m else None
    thousands = re.search(r"\d([,.])\d{3}", m.group(2)) if m else None
    sep = thousands.group(1) if thousands else ("," if not dec or dec[0] == "." else ".")
    if dec:
        whole, cents = f"{value:.2f}".split(".")
        return f"{int(whole):,}".replace(",", sep) + dec[0] + cents
    return f"{int(round(value)):,}".replace(",", sep)


def _check_sums(out: dict) -> None:
    """Totals that disagree with the document's own arithmetic go to review."""
    def num(f):
        return amount_value(out[f]["value"]) if f in out else None

    def flag(f, note):
        out[f]["status"] = "needs_review"
        out[f].setdefault("notes", []).append(note)

    def day(f):
        v = str(out[f]["value"]) if f in out else ""
        return v if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else (parse_date(v, "dmy") or parse_date(v, "mdy"))

    issued, due = day("invoice_date"), day("due_date")
    if issued and due and due < issued:
        flag("due_date", f"due before the invoice date {out['invoice_date']['value']}")
    import datetime as _dt

    today = _dt.date.today().isoformat()
    for f in ("date", "invoice_date", "pay_date", "collected", "admission_date", "discharge_date", "order_date"):
        d = day(f)
        if d and (d > today or d < "1900-01-01") and out[f].get("status") == "valid":
            flag(f, f"the date {out[f]['value']} lies in the future" if d > today else "the year is implausible")
    total, sub, tax, cash, change = num("total"), num("subtotal"), num("tax"), num("cash"), num("change")
    if total is not None and tax is not None and tax > 0 and total <= tax + 0.001:
        flag("total", f"not more than the tax {out['tax']['value']}")
    if total is not None and cash is not None and change is not None and cash >= change:
        if abs(cash - change - total) > 0.011 and abs(cash - total) > 0.011:
            flag("total", f"cash {out['cash']['value']} - change {out['change']['value']} does not give the total")
    if total is None and cash is not None and change is not None and cash > change >= 0 and "cash" in out:
        # the total line could not be read, but the payment can: cash - change is the total;
        # it stands as read only when the subtotal printed on the receipt says the same
        derived = cash - change
        agrees = sub is not None and abs(sub - derived) <= 0.011
        out["total"] = {"value": _like(out["cash"]["value"], derived), "label": "cash - change",
                        "page": out["cash"].get("page"), "bbox": out["cash"].get("bbox"),
                        "method": "worked out from the payment",
                        "status": "valid" if agrees and out["cash"]["status"] == "valid" and
                        out["change"]["status"] == "valid" else "needs_review",
                        "notes": [f"cash {out['cash']['value']} - change {out['change']['value']}"
                                  + ("; equals the subtotal" if agrees else "; the total line itself was not read")]}
    if total is not None and sub is not None:
        ok = abs(sub - total) <= 0.011 or (tax is not None and abs(sub + tax - total) <= 0.051)
        if not ok and sub > total + 0.011:
            flag("total", f"the subtotal {out['subtotal']['value']} is larger than the total")
            flag("subtotal", f"the subtotal is larger than the total {out['total']['value']}")
