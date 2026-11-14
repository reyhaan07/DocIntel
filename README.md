# docintel

**Relationship-aware document understanding for patient intake forms.**

`PDF → entities + relationships → validated JSON → standardized form`

Ordinary PDF text extraction reads the words but loses *who owns what*: which dose and
doctor belong to which drug, which member ID is the primary policy, whether
"hypertension" is the patient's condition or the mother's, and whether the patient
actually signed. docintel keeps that structure, and every value and every link can be
traced back to the exact spot on the page it came from.

## How it works

| Stage | What happens |
|---|---|
| **1 Read** | Filled form fields are read directly from the AcroForm; flattened pages are read word by word with their positions; ticked boxes are detected visually (ink inside printed squares) or from printed `[X]` / `[ ]` markers; drawn signatures are kept as ink marks; scanned pages are flagged and can go through OCR. |
| **2 Locate** | Every recognised heading becomes a rectangular page region. Headings printed side by side (primary / secondary insurance) get their own column regions. Tables are split into rows and columns using the document's own header labels. |
| **3 Bind** | A value can only join an entity if it was found in the same section, and for tables on the same row. Nothing is bound because it happens to be *near* something else. |
| **4 Relate** | Typed relationships such as `TAKES_MEDICATION`, `PRESCRIBED_BY`, `HELD_BY`, `HAS_CONDITION`, `SIGNS`. Each is `explicit` or `uncertain`, says why it exists (`basis`) and lists the page locations that support it (`evidence`). |
| **5 Validate** | Seven checks run on every document. Anything doubtful goes to a review queue instead of being guessed. |

The seven checks: evidence provenance, predicate signatures, medication record integrity,
insurance policy separation, family history separation, consent decision integrity and
signature–agreement binding.

**Different layouts.** Headings and column labels are matched by meaning using the
aliases in [`docintel/templates/patient_intake_v1.json`](docintel/templates/patient_intake_v1.json),
so another clinic's packet ("PATIENT DEMOGRAPHICS", "MEDICATION LIST" with *Drug /
Prescribed By / Dose / How Often*, "FINANCIAL POLICY") is understood without a new template.

**Uncertain, not guessed.** A medication row whose text wraps onto the next line, a consent
question with both *Yes* and *No* ticked, or a signature whose printed name is someone
else's (a guardian or representative) are kept but marked uncertain, and sent for review.
No doctor is invented for a row that has none; the gap is reported as missing information.

## Quick start

```bash
pip install -e .              # or: pip install -r requirements.txt
python -m docintel serve      # web app at http://localhost:8000
```

On first start the web app processes the four sample packets in `samples/input/`.
Drop more PDFs on the page (for example `samples/upload/new_patient_riverside.pdf`).

## Command line

```bash
python -m docintel serve                                 # web app at http://localhost:8000
python -m docintel process samples/input -o output       # one JSON + standardized PDF per file
python -m docintel ask output/DOC_003.json owner COND_006   # relationship questions from the terminal
python -m docintel scan-template <reference.pdf>         # map your real reference form
python -m docintel samples                               # regenerate the sample PDFs
```

`process` writes, per PDF, `DOC_xxx.json` and `DOC_xxx_standardized.pdf`, plus a batch
`index.json` and a combined `review_queue.json`.

`ask` questions (also available in the web app's **Ask** tab):

| question | argument | answers |
|---|---|---|
| `find` | text | where a value appears, and whose it is |
| `entity` | `MED_003` | everything that belongs to an entity |
| `owner` | `COND_006` or `FAM_001.conditions` | who an entity or value belongs to, and via which link |
| `section` | `MED_003.dosage` | section, heading, printed label, page and box of a value |
| `related` | `DR_002 PAT_001` | the relationship path between two elements |
| `evidence` | `REL_039` | the pages and boxes that support a relationship |

## The web app

* **Sidebar**: every processed document with its status: *Completed*, *Needs review* or
  *Needs OCR* (a *Run OCR* button appears when an OCR engine is installed).
* **Summary**: entities, traced values, relationships, uncertain links, review items,
  missing items, validation errors, standardized fields filled / withheld.
* **Entities**: one card per entity. Each row is an attribute: field name, extracted value,
  the label exactly as printed, confidence and validation status. Relationships are listed
  under each card.
* **Relationships** (all / uncertain), **Review**, **Missing**, **Validation** and **Ask** tabs.
* **Viewer**: click any value, relationship or review item and the page jumps to the exact
  spot. The solid box is the value; the dashed box is the printed label or heading it was
  read under. The trace line shows label, page, extraction method and confidence.
  Switch to **Standardized** to see the field the value filled. Values still awaiting
  review are left blank on the standardized form.

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

Every relationship records its subject, predicate and object, whether it is explicit or
uncertain, the reason it exists and the page locations that support it:

```json
{"relationship_id": "REL_014", "subject": "MED_003", "predicate": "PRESCRIBED_BY", "object": "DR_002",
 "support": "explicit", "confidence": 0.9,
 "basis": "'Prescribed By' recorded on the same table row as the medication (row 3 of 'Current Medications')",
 "evidence": [{"page": 1, "bbox": [...], "text": "Sertraline", "role": "subject"}, "..."]}
```

The document JSON also holds `sections` (the located regions), `review_queue`, `missing`,
`validation` (per-check results, errors, warnings) and `standardized` (fields filled,
withheld and where each value was placed).

## Standardized reference form

`docintel/templates/patient_intake_v1.pdf` is a fillable reference form, and
`patient_intake_v1.fieldmap.json` maps each of its fields to a path in the extracted
structure (`patient_information.date_of_birth`, `current_medications[3].dosage`,
`family_history[mother].conditions`, `communication_consent.text_message.no` ...).

Values are placed **by structure**: medication row 3 of the JSON goes to row 3 of the form
and the mother's record goes to the mother row. When your real reference form is ready,
run `scan-template` on it: its fields are located the same way values are (section
heading, printed label, table column and row, check-box option), and the field map is
written next to it.

## OCR (optional)

Scanned, image-only pages are reported as *Needs OCR*. To read them:

```bash
pip install pytesseract        # and install the tesseract binary (e.g. apt-get install tesseract-ocr)
python -m docintel process scans/ -o output --ocr
python -m docintel serve --ocr  # or use the "Run OCR" button per document
```

OCR output is less certain than text or form fields; confidences reflect that and
anything unclear goes to review.

## Samples

All sample data is synthetic.

| file | exercises |
|---|---|
| `intake_A_fillable_okafor.pdf` | the reference form filled in as AcroForm fields |
| `intake_B_flattened_lindqvist.pdf` | the same form flattened: drawn check boxes, ink signatures, a signer who is not the patient |
| `intake_C_other_clinic_rivera.pdf` | another clinic's layout and headings: side-by-side insurance, a wrapped medication row, both consent boxes ticked, a signature by the patient's sister |
| `intake_D_scanned_rivera.pdf` | a scan of packet C (image only) |
| `samples/upload/new_patient_riverside.pdf` | a packet to upload through the web app |

## Development

```bash
pip install -e ".[dev]"
python -m pytest
```

```
docintel/
  read.py         stage 1: form fields, positioned words, check boxes, ink, OCR
  layout.py       stage 2: lines, headings -> regions, tables
  bind.py         stage 3: entities from regions / rows / check boxes
  relate.py       stage 4: typed relationships with evidence
  validate.py     stage 5: seven checks + review queue
  pipeline.py     runs the stages, assembles the JSON
  standardize.py  fills the reference form by structure
  scan.py         scan-template
  ask.py          relationship questions
  store.py        document store and batch files
  server.py       web API;  static/ = single-page UI
  samples.py      sample and reference PDF generators
  templates/      template (aliases, relationship types), reference form, field map
```
