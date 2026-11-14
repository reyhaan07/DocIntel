# Benchmarks

Two benchmarks measure docintel on documents it was not built from. Both split their
documents **before** any result is looked at:

* the **development** half is where failures are inspected and their causes fixed;
* the **held-out** half is only ever measured.

The held-out numbers are the honest ones. They show how docintel does on documents
nobody tuned it for.

| benchmark | documents | what is marked by hand | command |
|---|---|---|---|
| OCR test suite (10 domains: student, HR, medical, identity, finance/banking, utility, legal, retail, insurance, business) | 200 scanned images | every field (label → value), every table cell, the full text | `python benchmarks/run_suite.py <ocr_test_suite_200> --split heldout` |
| [FUNSD](https://guillaumejaume.github.io/FUNSD/) (real 1980s–90s business forms, faxed and scanned) | 199 scanned forms | every question → answer link | `python benchmarks/run_funsd.py <FUNSD> --split heldout` |

**Silent errors** count as before: a wrong value, a value under the wrong label, or a
wrong link that docintel did **not** flag for review. A flagged error costs a reviewer one
click. The goal is zero silent errors.

Results are written to `bench_out/` (ignored by git). Add `-v` to `run_suite.py` to list
every failure.
