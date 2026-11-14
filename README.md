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
| **6 Validate** | Eight checks. Anything doubtful goes to the review queue. |

**The checks:** evidence provenance, predicate signatures, medication record integrity,
insurance policy separation, family history separation, consent decision integrity,
signature–agreement binding, and **text coverage** (every piece of text is accounted
for).

**Uncertain, not guessed.** These are kept, marked uncertain and sent for review:

* a medication row whose text wraps onto the next line
* a question with both *Yes* and *No* ticked, or an answer line where a box or its label could not be read
* a signature whose printed name is someone else's
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

## Quick start

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
TOTAL                                        541    99.45%    100%       0        3
```

The stress set (`samples/stress`, `samples/stress/ground_truth`) covers the cases in
*Guards against silent errors* above:

```
$ python -m docintel evaluate samples/stress --truth samples/stress/ground_truth
TOTAL                                        377   100.00%    100%       0        0
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

## Document types and templates

`docintel/templates/patient_intake_v1.json` describes the patient-intake type: sections and
the headings they may be printed under, field labels, table columns, and the
relationship types allowed between entity types. A document is treated as this type only
when at least three of its sections are recognised. Anything else is read with the
template-free structure. Adding a document type means adding a template file, not code.

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
  validate.py     stage 6: eight checks + review queue
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
