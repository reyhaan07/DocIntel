# docintel

**Relationship-aware document understanding. Pure Python, runs locally: no LLM, no external API.**

`PDF → entities + relationships → validated JSON (+ standardized form)`

Ordinary PDF text extraction reads the words but loses *who owns what*: which dose and
doctor belong to which drug, which member ID is the primary policy, whether
"hypertension" is the patient's condition or the mother's, and whether the patient
actually signed. docintel keeps that structure. Every value and every link can be traced
back to the exact spot on the page it came from, and anything doubtful is flagged for a
person instead of being guessed.

It reads **any** PDF (fillable, flattened or scanned, in any layout) as well as photos and scans
as PNG, JPG or TIFF. Documents of a known
type (today: patient intake packets) also get that type's meaning: patients, medications,
policies, consents and the relationships between them. Every other document is read
with the template-free structure: sections, fields, tables, check-box questions and
signatures. Nothing on the page is dropped.

## How it works

| Stage | What happens |
|---|---|
| **1 Read** | Filled form fields are read directly; flattened pages word by word with positions; ticked boxes are detected visually or from printed `[X]` / `[ ]`; drawn signatures are kept as ink. Scanned pages go through local OCR (below). |
| **2 Locate** | Headings become rectangular page regions: known headings by meaning (template aliases), unknown ones by how they are printed (bold, larger, capitals, space above). Side-by-side headings get their own column regions. An unknown heading also closes the section above it, so its content can never leak into a known section. |
| **3 Bind** | A value can only join an entity if it was found in the same section and, for tables, on the same row, never because it is merely *near* something. |
| **4 Relate** | Typed relationships (`TAKES_MEDICATION`, `PRESCRIBED_BY`, `HELD_BY`, `HAS_CONDITION`, `SIGNS`, `CONTAINS`, `DATED` …), each `explicit` or `uncertain`, with the reason it exists (`basis`) and the page locations that support it (`evidence`). |
| **5 Structure** | Template-free reading of every region: `Label: value` fields, tables (header row + aligned rows), check-box questions, signatures and text. Each piece of text gets exactly one role. On known documents, anything the template did not capture is kept as a generic entity and reported. |
| **6 Validate** | Nine checks. Anything doubtful goes to the review queue. |

**The checks:** evidence provenance, predicate signatures, medication record integrity,
insurance policy separation, family history separation, consent decision integrity,
signature–agreement binding, **text coverage** (every piece of text is accounted
for) and **cross-field consistency** (facts written twice agree: the insured's birth
date and the holder's, ZIP code and state, a birth date before the signature date, the
patient not named as their own contact).

**Uncertain, not guessed.** These are kept, marked uncertain and sent for review:

* a medication row whose text wraps onto the next line
* a question with both *Yes* and *No* ticked, or an answer line where a box or its label could not be read
* a signature whose printed name matches nobody on the form (a name that *does* match the
  spouse, emergency contact or an authorized person links the signature to that person)
* a field answered by ticking options where none, or more than one, is ticked
* a `Dose/Frequency` cell that does not start with a dose, so the two cannot be told apart
* `NKDA` / `None` in a table that also lists entries
* a value that does not fit its field (a phone number with letters, an impossible date)
* a date like `03/04/2026` when nothing else on the document settles whether it is day-first
* a value joined from two lines
* text sitting between fields that belongs to no field
* an OCR word read with low confidence, or a value OCR had to correct

No doctor is invented for a row that has none; the gap is reported as missing.

### Guards against silent errors

| Situation | What docintel does |
|---|---|
| Two patients' forms scanned into one PDF | Splits them into separate documents (one per form). Read as one, the file fails validation: forms are never merged |
| `Work Phone:` next to `Home Phone:` | A qualified label is a different field, never the patient's phone |
| `Yes [X]  No [ ]` (labels before their boxes) | The label side is decided by spacing, which still holds when OCR drops a box |
| `14/03/2026` and `05/04/1980` on one letter | The day/month order is decided once per document from unambiguous dates (or US phone/ZIP formats) |
| `943 476 5919` labelled *NHS Number* | Typed by its label: an identifier, not a phone number |
| Address on two lines | The second line is joined (and flagged) when it sits tight under the value, aligned with it |
| Table continuing on the next page without a header | Read with the same columns, numbering carried on |
| Labels printed above boxed values, or no colon | Read from the drawn boxes |
| Fillable fields with no printed label | Named after the field's own description (tooltip) |
| Running headers and footers | Recognised as page furniture and never read as data |
| A heading the template does not know | Closes the section above it, so its values cannot leak into a known section |
| Sideways or upside-down scans and photos | Turned upright before reading, and shown upright |
| A scan whose hidden text layer is garbage | Detected and read again with OCR |
| A scan embedded in a digital page | The embedded image is read with OCR as well |
| Encrypted PDF | Opened when no password is needed; a clear error when one is |
| `Sex: [ ] F [X] M`, `Marital Status: [ ] Single [X] Married …` | The ticked option is the value. None or two ticked → review, never the text of every option |
| Check boxes drawn with a symbol font (ZapfDingbats ■ / ❑) | Text extraction reads every glyph alike, so the rendered glyph decides: ink inside the box = ticked |
| `Date of Birth (MM/DD/YYYY):`, `Name (Last, First, MI):` | The hint is part of the label and sets the date order and the name order; a value that breaks the printed format goes to review |
| `1. PATIENT INFORMATION:`, `Section B – Insurance` | Numbering and a trailing colon are not part of the heading |
| `Policy No.`, `Tel`, `Insured's DOB`, `e-mail` | Abbreviations read as the words they stand for |
| `Dose/Frequency` in one column | Split into dose (`50 mg`) and frequency (`once daily`) |
| A header printed over two lines (`Prescribing` / `Physician`, `Unit` / `Price`) | Joined into one column label |
| A table column the template does not know (`Reason`) | Kept on the row as printed, not dropped and not merged into a neighbour |
| Numbers right-aligned under their header | Assigned by the header they sit under, not by where they start |
| `NKDA` / `None` in a table | Recorded as an answer (`allergies_status: no known drug allergies`), not as an allergy called "NKDA" |
| A consent signed by the spouse | `SIGNS` links the person whose name is printed, not the patient |
| Soft hyphens, ligatures, en dashes in numbers, duplicated (bold-by-overprint) characters | Cleaned before reading |
| Solid ■ boxes on a scan | A ticked box only when the page also has empty boxes of that size; otherwise a bullet |
| A digit or word read inside a box-shaped blob (`88`) | Kept as text, never swallowed as a check box |
| Fillable radio groups and digital-signature fields | The selected option (its printed label, or its export name when none is printed); a signed `/Sig` field is the signature (`digitally signed by …`, not cryptographically verified) |
| `Allergies: Penicillin (hives), Sulfa (rash)`, `Medications: Lisinopril 10 mg daily; …` | A list written on a line becomes one record per item (allergen + reaction, drug + dose + frequency, procedure + year). Text under the heading without a label is read for review only; instruction lines are never read as items. On scans, a `;` read as `:` does not start a new field |
| `Name: ____Ana Lopez____`, `Phone.........555-0182` | Underscores and dotted leaders are fill lines, not part of the value; leader dots separate a label from its value |
| Signature blocks with the label under the line (`Signature of Patient`, `Date`, `Printed Name`) | Each label takes the value (or the ink) above it |
| A sentence that resembles a heading (`I consent to treatment.`) | Not a heading: a near (fuzzy) heading match counts only when printed like a heading |
| Every section a two-column **Field \| Value** table (practice-system exports) | Each row is a labelled field; wrapped labels stay with their row; a section with only one or two rows takes its columns from the rest of the page (headers lost in a scan are not needed) |
| `Spouse Name`, `Emergency Phone` printed under Patient Information; `Primary …` / `Secondary …` in one Insurance section; `Pharmacy Name` under "Prescription Information" | Routed by the label to the record it names; `Relationship` right after `Emergency Contact` follows it. Policies sharing a section are kept apart by their labels |
| `Medication 1 / Dosage 1 / Prescribing Doctor 1`, or a single `Surgery / Year / Doctor / Location` block | One record per number (or per repetition), each medication with its own dose and its own doctor |
| `4. Allergies and Family History` | One heading, two sections: both are read from it |
| Social history, `Do you have secondary insurance? No`, `Not applicable` | Social history joins the patient; insurance questions are kept and checked against the policies found; "Not applicable" fills nothing |
| Yes/No written as text (`Permission to leave voicemail \| Yes`), `Selected medical conditions \| Heart disease; Arthritis` | Consents decided from the word; conditions mapped to their options |
| A signature block at the end of a consent-preferences section, or of an agreement that lists what it acknowledges | Each block becomes that section's own agreement, signed and dated; the acknowledged items are kept on it |
| `State: California`, `Location: Los Angeles, California` | Full state names become codes; a city and state is a location, not a hospital |
| `Dr. Test Provider 1` and `Dr. Test Provider 2` | Different people: numbers in a name are never ignored |
| OCR `lyer` among capitalised words | Probably `Iyer` (capital I and small l look alike): sent for review |
| Labels printed small above their values (`ISSUED ON` over the date), two boxes per row or one alone | Each label takes the value under it, even when part of the row was not read; a row of labels under a row of labels means empty boxes, so nothing is paired |
| A list of labelled values with no header (`Size … FULL PAGE`, `Written by … D. Schickedantz`) | Read as fields. A line that holds data (a measurement, a code, a person's name, a sentence) is never a column header |
| A "table" of one row, or one whose rows do not fill several columns | Not a table: a table holds records. A row of capitals labels, a capitals heading or a sentence ends a table |
| White text on a dark table-header bar (scans) | The bar is found, inverted and cleaned to black on white before OCR; a bold word is not mistaken for a bar |
| A larger value under a small capitals label (`STATUS` / `SUCCESS`, `MANAGER` / `Diya Raman`) | The value, not a heading. A small label over a larger value is a label, not a heading |
| OCR `FIN-O600`, `UTROO00000616`, `neiljosepho8` | O/0 and l/1 inside numbers corrected (`FIN-0600`) **and sent for review**; whole words are never changed |
| A value that reads like a label on a scan (`Date`, `Authorized Signature`, `Total Contract`) | Most likely the next label over an empty box: sent for review |
| `+44 20 7946 0958`, `0049 30 1234567`, `ext. 12` | International numbers kept as written (never re-grouped as US numbers); extensions kept |

## File types

| kind | formats | how it is read |
|---|---|---|
| PDF | `.pdf` (digital, fillable, flattened, scanned, encrypted without password) | text layer, form fields, drawn boxes and ink; OCR for scanned pages |
| Images | `.png .jpg .jpeg .tif .tiff .bmp .gif .webp` | OCR, straightened and turned upright |
| Office | `.docx .xlsx .pptx` and OpenDocument `.odt .ods .odp` | headings, paragraphs, tables, lists and tick boxes read from the file itself |
| Web and e-mail | `.html .htm .eml` | headings, paragraphs, tables, form inputs with their labels, definition lists; e-mail headers, body and attachment names |
| Text and data | `.txt .md .rtf .csv .tsv .json .xml` | Markdown headings and pipe tables, RTF tables, delimited tables, nested JSON as labelled values and tables |

Every non-PDF file is laid out as a clean PDF of its structure (headings larger and bold,
`Label: value` lines, ruled tables). The same reading rules then apply to every
format, and every value still points at a box on a page in the viewer. All readers are
pure Python (standard library); nothing is sent anywhere.

## Quick start

**Step by step for Windows, macOS and Linux: [`HOW_TO_RUN.md`](HOW_TO_RUN.md).** In short:
install Python 3.10+ and Tesseract, then double-click `run_windows.bat` (Windows) or run
`./run_mac_linux.sh` (macOS / Linux). The browser opens at http://localhost:8000.

Or by hand:

```bash
# Python 3.10+
pip install -e .
# for scanned PDFs: the Tesseract OCR program (free, local)
#   Debian/Ubuntu: sudo apt-get install tesseract-ocr     macOS: brew install tesseract
python -m docintel serve        # web app at http://localhost:8000
```

On first start the web app processes the samples in `samples/input/`. Drop more PDFs on
the page (for example `samples/upload/new_patient_riverside.pdf`).

## Command line

```bash
python -m docintel serve                                    # web app at http://localhost:8000
python -m docintel process samples/input -o output          # one JSON (+ standardized PDF) per file
python -m docintel ask output/DOC_003.json owner COND_006   # relationship questions
python -m docintel evaluate samples/input                   # accuracy against ground truth
python -m docintel truth output/DOC_003.json -o t.json      # export a checked result as ground truth
python -m docintel scan-template <reference.pdf>            # map your real reference form
python -m docintel samples --stress                         # regenerate the sample (and stress) PDFs
```

OCR runs automatically on scanned pages when Tesseract is installed. `--no-ocr` turns it
off (pages are marked *Needs OCR*); `process --ocr` fails if no engine is installed.

`process` writes, per form, `DOC_xxx.json` and `DOC_xxx.md`, plus `DOC_xxx_standardized.pdf`
for known document types. It also writes `DOC_xxx_source.pdf` when the form was split out
of a larger file, converted from an image or turned upright. Finally it writes a batch
`index.json` and a combined `review_queue.json`.

`ask` questions (also in the web app's **Ask** tab):

| question | argument | answers |
|---|---|---|
| `find` | text | where a value appears, and whose it is |
| `entity` | `MED_003` | everything that belongs to an entity |
| `owner` | `COND_006` or `FAM_001.conditions` | who an entity or value belongs to, and via which link |
| `section` | `MED_003.dosage` | section, heading, printed label, page and box of a value |
| `related` | `DR_002 PAT_001` | the relationship path between two elements |
| `evidence` | `REL_039` | the pages and boxes that support a relationship |

## The web app

* **Sidebar:** every processed document with its status: *Completed*, *Needs review* or *Needs OCR*.
* **Summary:** entities, traced values, relationships, uncertain links, review items,
  missing items, validation errors, share of the page text that was read, and standardized
  fields filled / withheld.
* **Document:** the whole document in reading order: headings, fields, tables, questions,
  signatures, paragraphs, and running headers and footers. Click any block to see it on the
  page. **Markdown** downloads the same as a `.md` file.
* **Entities:** one card per entity. Each row shows the field, the value, the label exactly as
  printed, the confidence and the status.
* **Review:** every flagged item with an action: *Confirm value* / *Correct…* for values,
  *Confirm link* / *Reject link* for relationships, *Acknowledge* for check findings.
  Decisions update the result, the standardized form and the audit log (`review_log`).
  When nothing is open, **Save as ground truth** adds the checked result to the
  accuracy suite.
* **Relationships**, **Missing**, **Validation** and **Ask** tabs.
* **Viewer:** click any value, relationship or review item and the page jumps to the exact
  spot: a solid box for the value, a dashed box for its printed label or heading.
  **Standardized** shows the field the value filled.

## Scanned documents (OCR)

Everything runs on your machine; nothing is sent anywhere.

1. The page image is **straightened** (skew found from the ink profile, pure numpy/PIL).
2. **Ruled lines and form-box borders are erased** so they are not read as characters.
3. **Tesseract** reads the page in two layouts (sparse and block), and the two readings
   are merged word by word, keeping the more confident one.
4. **Drawn check boxes** (ticked or empty) and **ink signatures** are found in the image itself.
5. Every box is mapped back onto the original scan, so highlights land on the page as
   scanned (under 1 pt off on a page rotated by 2°).
6. Words read with low confidence, and values OCR had to correct (`75 meg` → `75 mcg`,
   `4o mg` → `40 mg`), are **flagged for review**, never trusted silently.

## Accuracy: measuring the way to 100 %

`samples/ground_truth/` holds, for each sample, every value and relationship a perfect
reading would produce. Entities are addressed by meaning (`Medication[Sertraline].dosage`),
not by ID.

```
$ python -m docintel evaluate samples/input
document                                  values  accuracy   links  silent  flagged
intake_A_fillable_okafor.pdf                 105   100.00%    100%       0        0
intake_B_flattened_lindqvist.pdf              72   100.00%    100%       0        0
intake_C_other_clinic_rivera.pdf             105   100.00%    100%       0        0
intake_D_scanned_rivera.pdf                  105    99.05%    100%       0        1
intake_E_scanned_lindqvist.pdf                72    97.22%    100%       0        2
invoice_northwind.pdf                         38   100.00%    100%       0        0
lab_report_harper.pdf                         44   100.00%    100%       0        0
TOTAL                                        543    99.45%    100%       0        3
```

The stress set (`samples/stress`, `samples/stress/ground_truth`) covers the cases in
*Guards against silent errors* above:

```
$ python -m docintel evaluate samples/stress --truth samples/stress/ground_truth
TOTAL                                        711    99.86%    100%       0        1
```

The number that matters most is **silent errors**: a value or link that is wrong, invented
or missed *and not flagged*. A flagged mistake costs a reviewer one click; a silent one
reaches the record. The bar is zero silent errors, then fewer flags. The three
remaining mistakes above are OCR misreads on the scans, and all three are flagged.

How the suite grows toward 100 %:

1. Process real documents, resolve their review items in the web app, and press
   **Save as ground truth** (or `python -m docintel truth`).
2. Run `python -m docintel evaluate <folder> --truth <folder> --strict` on every change. It
   fails on any silent error.
3. Every error it shows becomes a rule, an alias or a template for a new document type.

### Benchmarks on documents docintel was not built from

`benchmarks/` measures docintel on outside sets: two form benchmarks and a 1,346-document
corpus of every kind. Each is split into a development
half (failures inspected, causes fixed) and a held-out half (only measured). See
[`benchmarks/README.md`](benchmarks/README.md).

| held-out half | before this round | now |
|---|---|---|
| OCR test suite, 100 scanned documents in 10 domains: fields correct | 86.7 % | 99.0 % |
| … table cells correct | 3.4 % | 100 % |
| … words of the text read | 97.8 % | 98.8 % |
| … **silent errors** | 42 | 1 |
| FUNSD, 50 noisy scanned forms: label → value links stated correctly (precision) | 52.1 % | 58.8 % |
| … links found (recall) | 20.5 % | 22.5 % |
| … **silent errors** | 88 | 80 |

FUNSD's faxed 1980s forms (handwriting, stamps, 100 dpi scans, labels without colons)
remain hard for any reader without a template. The silent errors left there are the
work still ahead: each one is a case where docintel cannot yet see its own doubt.

#### Any document: the 1,346-document corpus

The corpus (`benchmarks/corpus/`) adds receipts, invoices, office correspondence,
reports, news, adverts, government forms and files in ten formats to the two sets above,
1,346 documents in all, each scored against its own dataset's labels. Its split is fixed
by position before anything is looked at: 723 development documents, 623 held out. Each
round fixes causes found on the development half only; the held-out half is then measured
once, on the code as committed (round 1: `3b17f63`, round 2: `d8bdb88`).

| held-out half (623 documents) | before | round 1 | round 2 |
|---|---|---|---|
| **Invoices** - FATURA, 50 images, many layouts: total / number / date / due date | 5 / 1 / 5 / 5 | 50 / 46 / 50 / 49 | 50 / 46 / 50 / 49 |
| … document type 'invoice' | 10 % | 100 % | 100 % |
| katanaml invoices, 13 images: number, date, seller, buyer, total (65 facts) | 0 | 64 | 64 |
| invoice2data, 5 real PDF invoices (several languages): total, number, date (14 facts) | 3 | 5 | 5 |
| **Receipts** - SROIE, 75 scanned: total / date / merchant | 10 / 15 / 32 | 19 / 38 / 39 | **27** / 38 / 39 |
| … silent errors in those facts | 54 | 7 | **3** |
| **Receipt photos** - CORD, 50 phone photos: total | 4 of 46 | 5 of 46 | **16** of 46 |
| … document type 'receipt' | 34 % | 28 % | **52 %** |
| **Office documents** - RVL-CDIP, 200 scans in 16 classes: type correct | 20.5 % | 35.5 % | 35.5 % |
| **Government forms** - IRS / CMS / VA / DOL, 20 PDFs, 358 filled values: read | 192 | 196 | 196 |
| … silent errors | 17 | 13 | 13 |
| **Files** - 60 Word / Excel / PowerPoint / OpenDocument / HTML / e-mail / Markdown / RTF / JSON / CSV: fields, cells | 100 %, 91 % | 100 %, 91 % | 100 %, 91 % |
| … silent errors | 0 | 0 | 0 |
| **Forms** - OCR test suite, 100 scans in 10 domains: fields, cells, text | 99.0 %, 100 %, 98.8 % | same | same |
| … silent errors | 1 | 1 | 1 |
| FUNSD, 50 faxed forms: links found, precision | 22.5 %, 58.4 % | 24.1 %, 58.0 % | 24.1 %, 58.0 % |
| … silent errors | 80 | 88 | **31** |
| **all key facts of receipts and invoices** (550) | 80 correct, 60 silent | 365 correct, 15 silent | **384 correct, 11 silent** |
| **all silent errors measured** | 158 | 117 | **56** |

What moved the numbers, all general rules found on the development halves:

* *Round 1* - words read in reading order (OCR returns them by confidence); title lines and
  type-naming phrases weighted over shared words; amounts read token by token, with a
  dropped decimal point or a second amount sent to review instead of passed as read;
  'Seller:' / 'Bill To:' labels over name-and-address blocks; 'Total' rows read from their
  total column; dates in the future, totals below their tax and subtotals above their
  total flagged; uneven lighting evened out on photos; pages that read poorly tried upside
  down.
* *Round 2, scanned forms* - a pairing is only as good as its evidence: a table whose values
  do not line up under its headings is a form read as a grid; a value spread across the
  line like separate entries is check-box choices or a second label; a text value far from
  its label, or stacked under it in the same size of print (two labels), goes to review;
  ink beside a label that asks for no signature is handwriting, not a signature.
* *Round 2, photos* - a photo is not straightened by its ink profile nor stripped of ruled
  lines (both cost words on curled paper); its tilt is measured from the words Tesseract
  places on each line; it is read at the print size OCR handles best, by three passes that
  vote; a total is read from its printed row even where the amount drifted onto a line of
  its own; the receipt's own arithmetic (subtotal + tax, cash - change) confirms exact
  readings and supplies a missing total for review.

What is still hard: phone photos where no total is found at all (27 of 46 in CORD's held-out
half: faint thermal print, crumpled paper, blurred-out text); RVL's handwritten pages and
image-only adverts, which have almost no readable text (docintel says so: "the page reads
poorly"); and FUNSD's faxed forms, where more answers are found than before but many are
sent to review rather than trusted.

## Document types and key facts

Every document gets a type from its first page, with the evidence in
`document_type_basis`. 28 types are known: invoice, receipt, bank statement, payslip,
utility bill, lab report, prescription, discharge summary, purchase order, contract,
letter, memo, e-mail, fax cover sheet, press release, resume, meeting minutes, insurance,
tax form, referral, questionnaire, scientific publication, report, specification, budget,
news article, advertisement, presentation and form (see `docintel/profiles.py`).

How the type is decided:

- the words are read in reading order (OCR hands them back by confidence), with a break
  between columns so that no phrase is read across a gap;
- a phrase that *names* a type ("Invoice", "Memorandum", "Statement of Account",
  "Dear ...", "Sincerely") counts 4 in the title or a heading and 2 in the text; words a
  type merely shares with others ("total", "summary") count 2 and 1;
- the title is the larger, bold or capitals lines in the top third of page 1;
- memos and e-mails share their header lines (To:, From:, Subject:); an e-mail address
  or a time stamp in the From line, or a Sent: line, makes it an e-mail;
- a page with almost no text, or nothing that names a type, is `unknown` and says why;
- an e-mail, letter or memo that carries a business document (an invoice in the body
  of an e-mail) keeps its own type and names the carried one in `carries`; the key
  facts of both are read.

For types with key facts, `key_facts` names each one with its source and a status:

```json
"key_facts": {
  "invoice_number": {"value": "97159829", "label": "Invoice no", "method": "labelled value", "status": "valid", "page": 1, "bbox": [...]},
  "seller": {"value": "Bradley-Andrade, 9879 Elizabeth Common, Lake Jonathan, RI 12335", "label": "Seller", ...},
  "total":  {"value": "$978,12", "label": "Total / Gross worth", "method": "table row", "status": "valid", ...}
}
```

A fact comes from a labelled value first (including 'Seller:' / 'Bill To:' labels printed
over a name-and-address block), then from the 'Total' row of a table (the amount in its
total column), then from a line that starts with the fact's name (`TOTAL   9.00` on a
receipt), and the issuer from a line at the top that names a company. Amounts are read
token by token, and anything uncertain goes to review rather than being passed as read:

- a line holding several amounts, or words next to the amount (`GST 5.71` under 'Total');
- a decimal point OCR dropped (`88 17` is offered as 88.17, flagged);
- a whole number where the document's other amounts carry cents;
- a date with stray characters (`*3/01/2018`);
- a total that disagrees with the document's own arithmetic (cash − change, a subtotal
  larger than the total);
- an issuer taken from the first line when that line does not name a company.

The type is only a label: nothing on the page is read differently because of it.

## Templates

`docintel/templates/patient_intake_v1.json` describes the patient-intake type: sections and
the headings they may be printed under, field labels, table columns, and the
relationship types allowed between entity types. A document is treated as this type only
when at least three of its sections are recognised. Anything else is read with the
template-free structure and gets a document type guessed from the words on its first page
(`invoice`, `lab report`, `referral` …, with the words that decided it in
`document_type_basis`). The guess is a label only; nothing is read differently because of it.
Adding a document type means adding a template file, not code.

Besides the reference form's fields, the template knows the fields real intake packets
add: middle name, preferred name, SSN, preferred language, race, ethnicity, employer,
occupation, primary care physician, a second address line, and a **Preferred Pharmacy**
section (`USES_PHARMACY`). These appear in the JSON; the standardized reference form only
holds the fields it has boxes for.

The standardized reference form `patient_intake_v1.pdf` has a field map
(`patient_intake_v1.fieldmap.json`) that places values **by structure**: medication row 3
goes to row 3 of the form, the mother's record goes to the mother row. When your real
reference form is ready, `scan-template` maps its fields the same way values are located.

## Output

Every attribute carries its value, the printed label, the page, the bounding box
(PDF points, top-left origin: `[x0, top, x1, bottom]`), the extraction method, its
confidence and its validation status:

```json
"MED_003": {
  "type": "Medication", "label": "Sertraline", "section": "Current Medications", "row": 3,
  "attributes": {
    "name":   {"value": "Sertraline", "field_label": "Drug", "page": 1,
               "bbox": [54.0, 506.5, 94.7, 516.0], "extraction_method": "layout_table",
               "confidence": 0.9, "status": "valid"},
    "dosage": {"value": "50 mg", "field_label": "Dose", "page": 1, "...": "..."}
  },
  "prescribing_doctor_id": "DR_002"
}
```

Every relationship records subject, predicate, object, `explicit` or `uncertain`, the reason
it exists and the page locations that support it:

```json
{"relationship_id": "REL_014", "subject": "MED_003", "predicate": "PRESCRIBED_BY", "object": "DR_002",
 "support": "explicit", "confidence": 0.9,
 "basis": "'Prescribed By' recorded on the same table row as the medication (row 3 of 'Current Medications')",
 "evidence": [{"page": 1, "bbox": [...], "text": "Sertraline", "role": "subject"}, "..."]}
```

The document JSON also holds:

* `sections`: the located regions
* `coverage`: the role of every piece of text
* `blocks`: the whole document in reading order (also rendered as Markdown)
* `packet`: for a form split out of a larger file, its pages in that file
* `review_queue`, `missing` and `validation`
* `standardized`: fields filled, withheld and where each value was placed
* after review, `review_log`

## Samples

All sample data is synthetic.

| file | exercises |
|---|---|
| `intake_A_fillable_okafor.pdf` | the reference form filled in as AcroForm fields |
| `intake_B_flattened_lindqvist.pdf` | the same form flattened: drawn check boxes, ink signatures, a signer who is not the patient |
| `intake_C_other_clinic_rivera.pdf` | another clinic's layout and headings: side-by-side insurance, a wrapped medication row, both consent boxes ticked, a signature by the patient's sister |
| `intake_D_scanned_rivera.pdf` | a scan of C (image only, read through OCR) |
| `intake_E_scanned_lindqvist.pdf` | a scan of B: boxed fields and drawn check boxes on an image |
| `lab_report_harper.pdf` | a laboratory report: not an intake form, read without a template |
| `invoice_northwind.pdf` | a supplier invoice: outside healthcare entirely |
| `samples/upload/new_patient_riverside.pdf` | a packet to upload through the web app |

Stress documents (`samples/stress`):

| file | exercises |
|---|---|
| `intake_F_tight_labels.pdf` | single-spaced labels, Home/Work Phone, a two-line address, labels before boxes, a row without prescriber |
| `intake_G_two_packets.pdf` | two different patients' forms in one file |
| `referral_H_eu_letter.pdf` | narrative letter, day-first dates, an NHS number, a signature block |
| `screening_I_stacked_two_pages.pdf` | labels above boxes, running header/footer, a table continued on page 2 |
| `photo_J_sideways.png` | a phone photo, turned 90° |
| `scan_K_bad_text_layer.pdf` | a scan whose hidden text layer is garbage |
| `intake_L_encrypted.pdf` | an encrypted PDF |
| `order_M_fillable_unlabeled.pdf` | fillable fields with no printed labels |
| `intake_N_real_world.pdf` | numbered headings with colons, choices ticked inside fields, format hints in labels, one "Insurance Information" section, a `Dose/Frequency` column with a two-line header and a `Reason` column, NKDA, a pharmacy, symbol-font check boxes, a consent signed by the spouse |
| `invoice_O_right_aligned.pdf` | right-aligned amounts and a two-line `Unit / Price` header |
| `scan_P_real_world.pdf` | N printed and scanned, tilted: symbol boxes and ticked choices read from the image |
| `intake_Q_written_lists.pdf` | allergies, medications and surgeries written as lines of text, an instruction line in between |
| `intake_R_fill_lines_signature_blocks.pdf` | values typed over underscores and leader dots, signature blocks with labels under the line, an ink-only signature |
| `intake_S_field_value_tables.pdf` | every section a Field \| Value table: prefixed labels, one insurance section for two policies, numbered medications, a heading for two sections, social history, three signature blocks |
| `scan_T_field_value_tables.pdf` | S printed and scanned: header rows and bold lost |

## Development

```bash
pip install -e ".[dev]"
python -m pytest            # OCR tests are skipped when Tesseract is not installed
```

```
docintel/
  read.py         stage 1: form fields, positioned words, check boxes, ink
  ocr.py          scanned pages: deskew, line removal, Tesseract, boxes and ink in images
  layout.py       stage 2: lines, headings -> regions, tables
  bind.py         stage 3: template entities from regions / rows / check boxes
  relate.py       stage 4: typed relationships with evidence
  generic.py      stage 5: template-free structure, reading-order blocks, Markdown
  validate.py     stage 6: nine checks + review queue
  pipeline.py     runs the stages, assembles the JSON
  review.py       human decisions: confirm / correct / reject, audit log
  evaluate.py     accuracy against ground truth (silent errors)
  standardize.py  fills the reference form by structure
  scan.py         scan-template
  ask.py          relationship questions
  store.py        document store and batch files
  server.py       web API;  static/ = single-page UI
  samples.py      sample and reference PDF generators
  stress.py       stress documents (layouts and conditions that break readers)
  templates/      template (aliases, relationship types), reference form, field map
```
