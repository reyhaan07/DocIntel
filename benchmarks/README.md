# Benchmarks

Three benchmarks measure docintel on documents it was not built from. All split their
documents **before** any result is looked at:

* the **development** half is where failures are inspected and their causes fixed;
* the **held-out** half is only ever measured.

The held-out numbers are the honest ones. They show how docintel does on documents
nobody tuned it for.

| benchmark | documents | what is marked by hand | command |
|---|---|---|---|
| OCR test suite (10 domains: student, HR, medical, identity, finance/banking, utility, legal, retail, insurance, business) | 200 scanned images | every field (label → value), every table cell, the full text | `python benchmarks/run_suite.py <ocr_test_suite_200> --split heldout` |
| [FUNSD](https://guillaumejaume.github.io/FUNSD/) (real 1980s–90s business forms, faxed and scanned) | 199 scanned forms | every question → answer link | `python benchmarks/run_funsd.py <FUNSD> --split heldout` |

A third benchmark, the **corpus** in [`corpus/`](corpus/), takes docintel beyond forms:
1,346 documents of every kind - receipts, invoices, letters, memos, e-mails, reports,
news, adverts, government forms, and generated Word / Excel / PowerPoint / OpenDocument /
HTML / e-mail / Markdown / RTF / JSON / CSV files - each scored against its own dataset's
labels:

| dataset | documents | what is checked |
|---|---|---|
| [RVL-CDIP](https://adamharley.com/rvl-cdip/) (100 per class sample) | 400 scanned office documents, 16 classes | the document type |
| [SROIE](https://rrc.cvc.uab.es/?ch=13) | 150 scanned Malaysian receipts | total, date, merchant |
| [CORD v2](https://github.com/clovaai/cord) | 100 photographed Indonesian receipts | total |
| [FATURA](https://huggingface.co/datasets/mathieu1256/FATURA2-invoices) | 100 invoice images, many layouts | total, invoice number, date, due date |
| [katanaml invoices](https://huggingface.co/datasets/katanaml-org/invoices-donut-data-v1) | 26 invoice images | number, date, seller, buyer, total |
| [invoice2data](https://github.com/invoice-x/invoice2data) test invoices | 11 real PDF invoices (4 languages) | total, number, date |
| US government forms (IRS, CMS, VA, DOL), filled by `gov_fill.py` | 40 PDFs: 20 fillable, 20 flattened | every filled-in value |
| generated documents (`multi_gen.py`) | 120 files: 14 types x 10 formats | every field and table cell |
| the OCR test suite and FUNSD above | 399 | as above |

```
benchmarks/corpus/fetch.sh <corpus>            # download the public sets
python -I benchmarks/corpus/prepare.py <corpus> [<ocr_test_suite_200>]
python -I benchmarks/corpus/run.py <corpus> --split heldout
```

**Silent errors** count as before: a wrong value, a value under the wrong label, or a
wrong link that docintel did **not** flag for review. A flagged error costs a reviewer one
click. The goal is zero silent errors.

Results are written to `bench_out/` (ignored by git). Add `-v` to `run_suite.py` to list
every failure.
