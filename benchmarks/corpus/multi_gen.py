"""Generated documents of 14 types in 10 file formats, each with its expected fields and table."""
import json, random, subprocess, sys
from email.message import EmailMessage
from pathlib import Path

OUT = Path(sys.argv[1])
rnd = random.Random(2026)
FIRST = ["Priya", "Daniel", "Amara", "Lucas", "Mei", "Omar", "Sofia", "Kofi", "Elena", "Ravi", "Hana", "Mateo"]
LAST = ["Shah", "Okafor", "Lindqvist", "Moreau", "Tanaka", "Haddad", "Rossi", "Mensah", "Novak", "Iyer", "Kim", "Silva"]
ORGS = ["Harbor Lab Supply", "Northwind Clinic", "Cedar Valley Bank", "Summit Utilities", "Brightpath Health",
        "Oakridge Hospital", "Lakeside Pharmacy", "Pioneer Logistics", "Evergreen Insurance", "Bluebay Legal"]


def person():
    return f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"


def date():
    return f"{rnd.randint(1, 12):02d}/{rnd.randint(1, 28):02d}/2026"


def money():
    return f"${rnd.randint(10, 9999):,}.{rnd.randint(0, 99):02d}"


def pick(*labels):
    return rnd.choice(labels)


def doc(kind):
    org = rnd.choice(ORGS)
    f, table, prose = {}, None, []
    if kind == "invoice":
        title = "INVOICE"
        f[pick("Invoice Number", "Invoice No.", "Invoice #")] = f"INV-{rnd.randint(10000, 99999)}"
        f[pick("Invoice Date", "Date of Issue")] = date()
        f[pick("Due Date", "Payment Due")] = date()
        f[pick("Bill To", "Customer")] = person()
        rows = [[pick("Gloves (box)", "Syringes", "Masks", "Gauze pads", "Test strips"), str(rnd.randint(1, 20)), money()] for _ in range(3)]
        table = {"headers": ["Description", "Qty", "Amount"], "rows": rows}
        f[pick("Total Due", "Amount Due", "Total")] = money()
    elif kind == "receipt":
        title = org.upper()
        f[pick("Receipt No", "Receipt Number")] = f"R{rnd.randint(100000, 999999)}"
        f["Date"] = date()
        f["Cashier"] = rnd.choice(FIRST)
        rows = [[pick("Coffee", "Bagel", "Juice", "Muffin", "Sandwich"), money()] for _ in range(3)]
        table = {"headers": ["Item", "Price"], "rows": rows}
        f[pick("Payment Method", "Paid By")] = pick("Visa", "Cash", "Mastercard", "UPI")
        f["Total"] = money()
    elif kind == "bank_statement":
        title = f"{org} - Account Statement"
        f[pick("Account Holder", "Customer Name")] = person()
        f[pick("Account Number", "Account No.")] = f"XXXX-XXXX-{rnd.randint(1000, 9999)}"
        f["Statement Period"] = f"{date()} to {date()}"
        f[pick("Opening Balance", "Beginning Balance")] = money()
        rows = [[date(), pick("ATM withdrawal", "Salary credit", "Card payment", "Transfer"), money()] for _ in range(4)]
        table = {"headers": ["Date", "Description", "Amount"], "rows": rows}
        f[pick("Closing Balance", "Ending Balance")] = money()
    elif kind == "payslip":
        title = "Payslip"
        f["Employee Name"] = person()
        f[pick("Employee ID", "Employee No.")] = f"E{rnd.randint(1000, 9999)}"
        f["Pay Period"] = pick("March 2026", "April 2026", "May 2026")
        f["Pay Date"] = date()
        rows = [[pick("Basic salary", "Overtime", "Allowance", "Bonus"), money()] for _ in range(3)]
        table = {"headers": ["Earning", "Amount"], "rows": rows}
        f["Gross Pay"] = money()
        f["Net Pay"] = money()
    elif kind == "utility_bill":
        title = f"{org} - Electricity Bill"
        f[pick("Account Number", "Customer Account")] = f"{rnd.randint(10000000, 99999999)}"
        f["Service Address"] = f"{rnd.randint(10, 999)} {pick('Elm', 'Lake', 'Hill')} Street, Springfield"
        f["Billing Period"] = f"{date()} - {date()}"
        f["Meter Number"] = f"M-{rnd.randint(100000, 999999)}"
        f[pick("Usage", "Consumption")] = f"{rnd.randint(100, 900)} kWh"
        f[pick("Amount Due", "Total Due")] = money()
        f["Due Date"] = date()
    elif kind == "lab_report":
        title = "Laboratory Report"
        f["Patient Name"] = person()
        f[pick("MRN", "Patient ID")] = f"MRN{rnd.randint(100000, 999999)}"
        f[pick("Collected", "Collection Date")] = date()
        f[pick("Ordering Physician", "Ordered By")] = "Dr. " + person()
        rows = [[t, f"{rnd.uniform(1, 200):.1f}", u, r] for t, u, r in rnd.sample(
            [("Glucose", "mg/dL", "70-99"), ("Hemoglobin", "g/dL", "13.5-17.5"), ("Sodium", "mmol/L", "135-145"),
             ("Potassium", "mmol/L", "3.5-5.1"), ("Creatinine", "mg/dL", "0.7-1.3")], 3)]
        table = {"headers": ["Test", "Result", "Units", "Reference Range"], "rows": rows}
    elif kind == "prescription":
        title = "Prescription"
        f["Patient"] = person()
        f[pick("Date of Birth", "DOB")] = f"{rnd.randint(1, 12):02d}/{rnd.randint(1, 28):02d}/{rnd.randint(1940, 2010)}"
        f["Prescriber"] = "Dr. " + person()
        f["Date"] = date()
        rows = [[m, d, fr] for m, d, fr in rnd.sample([("Amoxicillin", "500 mg", "three times daily"), ("Lisinopril", "10 mg", "once daily"),
                                                       ("Metformin", "500 mg", "twice daily"), ("Atorvastatin", "20 mg", "at bedtime")], 2)]
        table = {"headers": ["Medication", "Dose", "Frequency"], "rows": rows}
    elif kind == "discharge_summary":
        title = "Discharge Summary"
        f["Patient Name"] = person()
        f["Admission Date"] = date()
        f["Discharge Date"] = date()
        f["Attending Physician"] = "Dr. " + person()
        f[pick("Diagnosis", "Principal Diagnosis")] = pick("Community-acquired pneumonia", "Acute appendicitis", "Cellulitis of left leg")
        prose = ["The patient was admitted and treated with intravenous antibiotics.", "Follow up with primary care in one week."]
    elif kind == "letter":
        title = org
        f["Date"] = date()
        f["To"] = person()
        f[pick("Subject", "Re")] = pick("Your account review", "Appointment confirmation", "Policy renewal")
        prose = ["Dear customer,", "Thank you for your continued business. Please find the details of your request below.",
                 "Kind regards,", person()]
    elif kind == "memo":
        title = "MEMORANDUM"
        f["To"] = pick("All Staff", "Finance Team", "Nursing Staff")
        f["From"] = person()
        f["Date"] = date()
        f["Subject"] = pick("Holiday schedule", "New expense policy", "System maintenance")
        prose = ["Please note the changes described in this memo.", "Contact the office with any questions."]
    elif kind == "resume":
        title = person()
        f["Email"] = f"{rnd.choice(FIRST).lower()}@example.com"
        f["Phone"] = f"({rnd.randint(201, 989)}) 555-{rnd.randint(1000, 9999)}"
        f["Location"] = pick("Chicago, IL", "Austin, TX", "Seattle, WA")
        rows = [[pick("Analyst", "Nurse", "Engineer", "Accountant"), pick("Acme Corp", "City Hospital", "Delta Bank"), f"{rnd.randint(2010, 2020)}-{rnd.randint(2021, 2026)}"] for _ in range(2)]
        table = {"headers": ["Role", "Employer", "Years"], "rows": rows}
    elif kind == "minutes":
        title = "Meeting Minutes"
        f["Meeting"] = pick("Quality Committee", "Board Meeting", "Project Review")
        f["Date"] = date()
        f["Chair"] = person()
        f["Attendees"] = ", ".join(person() for _ in range(3))
        rows = [[pick("Update policy", "Send report", "Book venue", "Review budget"), person(), date()] for _ in range(3)]
        table = {"headers": ["Action", "Owner", "Due"], "rows": rows}
    elif kind == "purchase_order":
        title = "PURCHASE ORDER"
        f[pick("PO Number", "Purchase Order No.")] = f"PO-{rnd.randint(1000, 9999)}"
        f["Order Date"] = date()
        f["Vendor"] = rnd.choice(ORGS)
        f["Ship To"] = f"{rnd.randint(10, 999)} {pick('Oak', 'Pine', 'Bay')} Road, Riverton"
        rows = [[pick("Printer paper", "Toner", "Folders", "Pens"), str(rnd.randint(1, 50)), money()] for _ in range(3)]
        table = {"headers": ["Item", "Quantity", "Price"], "rows": rows}
        f[pick("Total", "Order Total")] = money()
    else:  # contract
        title = "SERVICE AGREEMENT"
        f[pick("Effective Date", "Agreement Date")] = date()
        f["Provider"] = rnd.choice(ORGS)
        f["Client"] = person()
        f["Term"] = pick("12 months", "24 months", "36 months")
        f["Governing Law"] = pick("State of Illinois", "State of Texas", "State of New York")
        prose = ["The Provider agrees to deliver the services described in Schedule A.", "Either party may end this agreement with 30 days notice."]
    return title, f, table, prose


def markdown(title, f, table, prose):
    out = [f"# {title}", ""]
    for k, v in f.items():
        out += [f"**{k}:** {v}", ""]
    if table:
        out += ["| " + " | ".join(table["headers"]) + " |", "|" + "---|" * len(table["headers"])]
        out += ["| " + " | ".join(r) + " |" for r in table["rows"]] + [""]
    out += [p + "\n" for p in prose]
    return "\n".join(out)


KINDS = ["invoice", "receipt", "bank_statement", "payslip", "utility_bill", "lab_report", "prescription",
         "discharge_summary", "letter", "memo", "resume", "minutes", "purchase_order", "contract"]
FORMATS = ["docx", "html", "md", "odt", "rtf", "pptx", "txt", "eml", "json", "xlsx"]
n = 0
for kind in KINDS:
    for k, fmt in enumerate(FORMATS[:8] if kind not in ("invoice", "bank_statement", "payslip", "purchase_order") else FORMATS):
        title, f, table, prose = doc(kind)
        n += 1
        stem = f"multi_{n:03d}_{kind}"
        md = markdown(title, f, table, prose)
        path = OUT / f"{stem}.{fmt}"
        if fmt in ("md", "txt"):
            path.write_text(md, encoding="utf-8")
        elif fmt == "json":
            data = {k2.lower().replace(" ", "_").replace(".", "").replace("#", "number"): v for k2, v in f.items()}
            if table:
                data["items"] = [dict(zip([h.lower().replace(" ", "_") for h in table["headers"]], r)) for r in table["rows"]]
            path.write_text(json.dumps({"document": title, **data}, indent=2), encoding="utf-8")
        elif fmt == "eml":
            m = EmailMessage()
            m["From"] = f"{rnd.choice(ORGS)} <noreply@example.com>"
            m["To"] = "inbox@example.com"
            m["Subject"] = title
            m.set_content(md.replace("**", "").replace("# ", ""))
            path.write_bytes(bytes(m))
        elif fmt == "xlsx":
            csvp = OUT / f"{stem}.csv"
            lines = [f'"{k2}","{v}"' for k2, v in f.items()] + [""]
            if table:
                lines += [",".join(f'"{h}"' for h in table["headers"])] + [",".join(f'"{c}"' for c in r) for r in table["rows"]]
            csvp.write_text("\n".join(lines), encoding="utf-8")
            subprocess.run(["soffice", "--headless", "--convert-to", "xlsx", "--outdir", str(OUT), str(csvp)],
                           capture_output=True, timeout=120)
            csvp.unlink()
        else:
            src = OUT / f"{stem}.src.md"
            src.write_text(md, encoding="utf-8")
            args = ["pandoc", str(src), "-o", str(path)] + (["-s", "--metadata", f"title={title}"] if fmt in ("html", "rtf") else [])
            subprocess.run(args, capture_output=True, timeout=120)
            src.unlink()
        truth = {"type": kind, "format": fmt, "fields": f, "table": table, "split": "dev" if n % 2 == 1 else "heldout"}
        (OUT / f"{stem}.truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
print(n, "documents")
