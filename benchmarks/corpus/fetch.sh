#!/usr/bin/env bash
# Download the public datasets of the corpus benchmark into $1 (default: ./corpus).
# Everything fetched is data: keep it in its own folder and read it with `python -I`.
set -euo pipefail
C=$(realpath -m "${1:-corpus}")
mkdir -p "$C/hf" "$C/govraw"
cd "$C/hf"
for f in "jordyvl/rvl_cdip_100_examples_per_class/resolve/main/data/test-00000-of-00001-d5e0db6590d27073.parquet rvl_test.parquet" \
         "katanaml-org/invoices-donut-data-v1/resolve/main/data/test-00000-of-00001-56af6bd5ff7eb34d.parquet katanaml_test.parquet" \
         "mathieu1256/FATURA2-invoices/resolve/main/data/test-00000-of-00001.parquet fatura_test.parquet" \
         "naver-clova-ix/cord-v2/resolve/main/data/test-00000-of-00001-9c204eb3f4e11791.parquet cord_test.parquet"; do
  set -- $f; [ -s "$2" ] || curl -sS -L --max-time 900 -o "$2" "https://huggingface.co/datasets/$1"
done
# SROIE receipts (the 150 picked in sroie_pick.txt) and invoice2data's test invoices
[ -d "$C/sroie/repo" ] || git clone -q --depth 1 --filter=blob:none --sparse https://github.com/zzzDavid/ICDAR-2019-SROIE "$C/sroie/repo"
(cd "$C/sroie/repo" && { echo 'data/key/*'; sed 's#.*#data/img/&.jpg#' "$(dirname "$0")/sroie_pick.txt"; } \
   | git sparse-checkout set --no-cone --stdin)
[ -d "$C/invoice2data/repo" ] || git clone -q --depth 1 --filter=blob:none --sparse https://github.com/invoice-x/invoice2data "$C/invoice2data/repo"
(cd "$C/invoice2data/repo" && git sparse-checkout set tests/compare)
# FUNSD
[ -d "$C/funsd/dataset" ] || { mkdir -p "$C/funsd" && curl -sS -L -o "$C/funsd/dataset.zip" https://guillaumejaume.github.io/FUNSD/dataset.zip \
   && (cd "$C/funsd" && unzip -q dataset.zip); }
# blank government forms (filled in by gov_fill.py with known values)
cd "$C/govraw"
for u in https://www.irs.gov/pub/irs-pdf/fw9.pdf https://www.irs.gov/pub/irs-pdf/fw4.pdf https://www.irs.gov/pub/irs-pdf/f4506c.pdf \
  https://www.irs.gov/pub/irs-pdf/f8821.pdf https://www.irs.gov/pub/irs-pdf/fss4.pdf https://www.irs.gov/pub/irs-pdf/f9465.pdf \
  https://www.irs.gov/pub/irs-pdf/f8822.pdf https://www.irs.gov/pub/irs-pdf/f2848.pdf https://www.irs.gov/pub/irs-pdf/f4868.pdf \
  https://www.irs.gov/pub/irs-pdf/f8832.pdf https://www.irs.gov/pub/irs-pdf/fw7.pdf https://www.irs.gov/pub/irs-pdf/f1040.pdf \
  https://www.irs.gov/pub/irs-pdf/f941.pdf https://www.cms.gov/medicare/cms-forms/cms-forms/downloads/cms10106.pdf \
  https://www.cms.gov/medicare/cms-forms/cms-forms/downloads/cms40b-e.pdf https://www.cms.gov/medicare/cms-forms/cms-forms/downloads/cms-l564e.pdf \
  https://www.cms.gov/medicare/cms-forms/cms-forms/downloads/cms1490s-english.pdf https://www.vba.va.gov/pubs/forms/VBA-21-4142-ARE.pdf \
  "https://www.va.gov/vaforms/medical/pdf/VA%20Form%2010-10EZ.pdf" https://www.dol.gov/sites/dolgov/files/WHD/legacy/files/WH-380-E.pdf \
  https://www.dol.gov/sites/dolgov/files/WHD/legacy/files/WH-380-F.pdf; do
  n=$(basename "$u" | sed 's/%20/_/g'); [ -s "$n" ] || curl -sS -L --max-time 60 -o "$n" "$u" || true
  head -c 5 "$n" 2>/dev/null | grep -q '%PDF' || rm -f "$n"
done
echo "fetched into $C"
