# Recording the docintel demo

A 10-12 minute screen recording that shows what docintel does: it reads any document -
forms, scans, photos, invoices, receipts, Word / Excel / e-mail files - on your own
computer, with no AI model and no online service, ties every value to the spot on the page
it came from, and sends anything it is unsure of to review instead of guessing.

Every file used below is in the repository. The people, companies and numbers in them are
invented.

## The ten demo documents (`samples/demo/`)

| file | what it is | what docintel reads |
|---|---|---|
| `01_invoice.pdf` | invoice, text PDF | invoice no 51840277, date, seller and client blocks, items table, total $224,95 (flagged: three amounts on the total row) |
| `02_receipt_photo.jpg` | cafe receipt, phone photo, tilted | merchant (flagged), bill no, date, subtotal 94,000 + tax 9,400 = total 103,400, cash, change |
| `03_bank_statement.pdf` | bank statement, text PDF | holder, account 4471 0092 5813, period, opening $3,240.18, closing $4,105.62, transactions |
| `04_payslip.docx` | payslip, Word | employee, ID NL-20417, March 2026, pay date, gross $4,665.00, net $3,648.50 |
| `05_utility_bill_scan.png` | electricity bill, scanned image | account 88-301-4472, address, period, meter, 612 kWh, $128.47 due 2026-03-20 |
| `06_discharge_summary.pdf` | hospital discharge summary | patient, admission and discharge dates, physician, diagnosis, medications table |
| `07_prescription_scan.pdf` | prescription, scanned PDF | patient Mateo Silva, Dr. Priya Shah, date, the Rx lines (scan: some lines for review) |
| `08_purchase_order.xlsx` | purchase order, Excel | PO-2026-0381, date, vendor, ship-to, items table, total $1,284.00 |
| `09_payment_reminder.eml` | e-mail about an invoice | invoice SE-77120, invoice date, due date, total $128.47, sender |
| `10_insurance_claim_form.pdf` | fillable PDF form | policy and claim numbers, insured, every filled box, the ticked 'No' |

`python samples/demo/make_demo.py` rebuilds them (needs `pip install python-docx openpyxl`).

**A ready-made recording.** `samples/demo/record_video.js` records the whole demo by itself, like
a screen recording: a mouse pointer moves to each button, uploads the ten documents one by
one and opens what was read. Start the app (`python -m docintel serve --data demo_data
--no-seed`), then run `node samples/demo/record_video.js out` (Node.js with Playwright). It
writes a 1920 x 1080 WebM and `scenes.json` with the time of each scene, for captions.

---

## 1. Before you record (once)

### Get the latest code

In VS Code, open the `DocIntel` folder and run in the terminal:

```bash
git fetch origin
git checkout ccr-b2b8b104-gc612d
git pull origin ccr-b2b8b104-gc612d
```

### Install

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate        macOS / Linux:  source .venv/bin/activate
pip install -e .
```

Install the free Tesseract OCR program (needed for scans and photos):

| system | command |
|---|---|
| Windows | installer from <https://github.com/UB-Mannheim/tesseract/wiki>, then add `C:\Program Files\Tesseract-OCR` to `PATH` |
| macOS | `brew install tesseract` |
| Ubuntu / Debian | `sudo apt-get install tesseract-ocr` |

Check: `tesseract --version` prints a version.

### Check that everything works

```bash
python -m pytest -q                       # 98 tests, all pass
python samples/demo/make_demo.py          # (optional) rebuilds the two demo files
```

### Start the app with an empty document list

```bash
python -m docintel serve --data demo_data --no-seed
```

Open <http://localhost:8000>. (To start over later, stop the server, delete the
`demo_data` folder and start it again.)

### Recording set-up

* Screen 1920 x 1080, browser zoom 90-100 %, one browser window, notifications off.
* Have a file explorer open on the repository folder, so files can be dragged onto the
  page (or use the **Upload files** button).
* Process each file once before recording (then delete `demo_data` and restart), so you
  have seen every screen and the first OCR run is not on camera.

---

## 2. The script

Times are a guide. *Say* lines are suggestions; the **expected** lines are what the screen
should show.

### Scene 1 - What it is (0:00-0:45)

Show the empty app.

*Say:* "This is docintel. It reads documents - forms, scans, phone photos, invoices,
receipts, Word, Excel and e-mail files - entirely on this computer: plain Python and the
Tesseract OCR engine, no AI model, no cloud service. Everything it extracts points back to
the exact spot on the page, and whatever it is not sure of goes to a review list instead of
being passed off as fact."

### Scene 2 - A patient intake form, every section and relationship (0:45-3:00)

Drop **`samples/stress/intake_S_field_value_tables.pdf`** (3 pages, field/value tables).

**Expected:** type *patient intake*, status *Completed*, about 28 entities, 84 traced values,
29 relationships, 0 validation errors.

1. **Entities** tab: patient, insurance, pharmacy, allergies, medications, consents and
   agreements, each as a card. Click a value - the page on the right jumps to it (solid box
   = the value, dashed box = its printed label).
2. Open a **medication** card: name, dosage and prescribing doctor are separate values of one
   medication. *Say:* "It doesn't just copy text: it knows this dose belongs to this drug and
   this doctor prescribed it."
3. **Relationships** tab: PRESCRIBED_BY, SIGNS, USES_PHARMACY ... Click one: both ends light
   up on the page.
4. **Validation** tab: the nine checks (dates, insurance holder, signatures per agreement ...).
5. **Missing** tab: what the form asks for but was left blank.
6. **Ask** tab: try *find* with a name, or *owner* of a condition.
7. **Standardized** (viewer toggle): the same answers filled into one standard form.

### Scene 3 - A scanned form (3:00-4:15)

Drop **`samples/input/intake_D_scanned_rivera.pdf`** (an image-only scan).

**Expected:** extraction *ocr*, status *Needs review*, about 6 review items.

1. Point at *extraction: ocr* in the header. *Say:* "There is no text in this PDF at all -
   it's a picture. Tesseract reads it locally; the page was straightened first."
2. **Review** tab: each item says *why* it is in doubt (a medication row that runs onto a
   second line, a consent answer it could not settle...). Click **Confirm value** on one, **Correct...** on another
   and type the right value. The counters update; the decision is kept in the audit log.

Optional: drop **`samples/stress/photo_J_sideways.png`** - a photo taken sideways. It is
turned upright before reading.

### Scene 4 - An invoice: key facts (4:15-5:45)

Drop **`samples/demo/01_invoice.pdf`**.

**Expected:** type *invoice*. **Document** tab, top panel *Key facts*:

| fact | value |
|---|---|
| invoice number | 51840277 |
| invoice date | 2026-03-02 |
| seller | Harbor Lab Supply Ltd, 41 Wharf Road, Portland, OR 97209 |
| buyer | Riverside Family Clinic, 300 Elm Street, Suite 4, Springfield, IL 62704 |
| total | $224,95 - marked **review** |

*Say:* "Seller and client are printed side by side, each over a block of lines - it keeps
them apart. The total row holds three amounts - net, VAT and gross. It takes the gross
amount, the last one, but marks it for review because the line is ambiguous. It never
silently picks."

Below the key facts: the items table with every column, then the summary table.

### Scene 5 - A phone photo of a receipt (5:45-7:00)

Drop **`samples/demo/02_receipt_photo.jpg`** (a receipt on a table, tilted, unevenly lit).

**Expected:** type *receipt*, key facts:

| fact | value |
|---|---|
| merchant | KOPI SENJA CAFE - **review** (a name read by OCR with no label to confirm it) |
| receipt number | 0418-2207 |
| date | 14/03/2026 |
| subtotal / tax / total | 94,000 / 9,400 / 103,400 |
| cash / change | 110,000 / 6,600 |

*Say:* "A photo, not a scan: the lighting is evened out, the tilt is measured from the
words themselves and levelled, and the text is read at the size OCR handles best. The total
is checked against the receipt's own arithmetic - subtotal plus tax equals the total - so
it stands as read. The shop name has nothing to confirm it, so it is offered for review."

Hover over a fact to see where it came from and any notes.

### Scene 6 - Any file type (7:00-8:30)

Drop these one after another (from `tests/fixtures/formats/`):

1. **`invoice.docx`** (Word) - *expected:* type *invoice*, fields Invoice Number INV-20931,
   Total Due $307.80, and the items table.
2. **`invoice.eml`** (an e-mail) - *expected:* type *email*, key facts header says
   *email carrying invoice*: the invoice number, due date and total are read from the
   body, as well as From / To / Subject.
3. **`items.xlsx`** (Excel) - *expected:* the sheet comes out as a table with every row and
   column.

*Say:* "Word, Excel, PowerPoint, OpenDocument, HTML, e-mail, text, Markdown, CSV, JSON, RTF,
images and PDFs all go through the same reader, so the same checks and the same review
apply to all of them."

### Scene 7 - Outputs (8:30-9:15)

On any document: **Download JSON** (every value with page, box, confidence and status),
**Markdown** (the whole document in reading order), **Source PDF**. Optionally show the
command line:

```bash
python -m docintel process samples/input -o output
```

which writes one JSON (+ standardized PDF) per document, a batch `index.json` and a combined
`review_queue.json`.

### Scene 8 - How we know it works (9:15-11:00)

Open `README.md` at **Benchmarks** and show the held-out table.

*Say:* "We measured it on 1,346 documents it was never built from - real receipts from
Malaysia and Indonesia, invoices in many layouts, 1980s office scans, US government forms,
and files in ten formats. Half were used to find and fix the causes of mistakes; the other
half was only ever measured. The number we watch is the *silent error*: a wrong value that
was not flagged. Those are the ones that cost money, so every round drives them down."

Results of the latest round (held-out half, measured once):

| held-out half (623 documents, measured once) | before | now |
|---|---|---|
| invoice facts (number, dates, total) - FATURA, 50 invoices | 16 of 200 | **195 of 200** |
| receipt facts (total, date, merchant) - SROIE, 75 scanned receipts | 57 of 225 | **104 of 225** |
| receipt photo totals - CORD, 50 phone photos | 4 of 46 | **16 of 46** |
| office documents typed correctly - RVL-CDIP, 200 scans | 20.5 % | **35.5 %** |
| form fields / table cells - OCR test suite, 100 scans | 99.0 % / 100 % | 99.0 % / 100 % |
| files in 10 formats - every field | 100 % | 100 % |
| **silent errors, all sets** | **158** | **56** |

### Scene 9 - Close (11:00-11:30)

*Say:* "Local, explainable, every value traceable, and honest about its doubts.
That's docintel."

---

## 3. If something goes wrong while recording

| problem | fix |
|---|---|
| "Needs OCR" on a scan | Tesseract is not installed or not on `PATH`; `tesseract --version` must work in the same terminal |
| port 8000 busy | `python -m docintel serve --data demo_data --no-seed --port 8010` |
| an old result is shown | stop the server, delete `demo_data`, start again |
| a photo takes a few seconds | normal: photos are read three ways and at the best size |
| numbers differ slightly from this guide | OCR can vary between Tesseract versions; anything uncertain still shows **review** |
