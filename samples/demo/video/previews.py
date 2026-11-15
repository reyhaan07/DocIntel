"""Previews of the original documents, as their own programs show them: PDF pages (with
filled form fields), photos as they are, Word / Excel through LibreOffice, e-mails as a
mail reading pane.  Writes prev/<file name>.png (or .html) and folders.json for the
recording's file dialog."""
import email
import email.policy
import html
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

REPO = Path(sys.argv[1])
OUT = Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
FOLDERS = {"demo": REPO / "samples" / "demo", "stress": REPO / "samples" / "stress"}
SHOW = {"demo": None, "stress": ["intake_S_field_value_tables.pdf", "intake_Q_written_lists.pdf",
                                 "invoice_O_right_aligned.pdf", "photo_J_sideways.png", "referral_H_eu_letter.pdf",
                                 "scan_P_real_world.pdf", "scan_T_field_value_tables.pdf"]}
TYPES = {".pdf": "PDF Document", ".jpg": "JPG File", ".png": "PNG File", ".docx": "Microsoft Word Document",
         ".xlsx": "Microsoft Excel Worksheet", ".eml": "Email Message"}
WIDTH = 1100


def pdf_png(pdf: Path, dest: Path, pages: int = 3) -> int:
    """Every page (up to three), one under the other with a gap, as a reader shows them."""
    doc = pdfium.PdfDocument(str(pdf))
    try:
        doc.init_forms()
    except Exception:
        pass
    imgs = []
    for i in range(min(pages, len(doc))):
        page = doc[i]
        imgs.append(page.render(scale=WIDTH / page.get_width(), may_draw_forms=True).to_pil().convert("RGB"))
    n = len(doc)
    doc.close()
    gap = 22
    out = Image.new("RGB", (WIDTH, sum(i.height for i in imgs) + gap * (len(imgs) - 1)), (82, 86, 89))
    y = 0
    for im in imgs:
        out.paste(im, (0, y))
        y += im.height + gap
    out.save(dest)
    return n


def office_png(src: Path, dest: Path) -> None:
    with tempfile.TemporaryDirectory() as t:
        subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", t, str(src)], check=True,
                       capture_output=True, timeout=180)
        pdf_png(Path(t) / (src.stem + ".pdf"), dest)


def xlsx_html(src: Path, dest: Path) -> None:
    """The sheet as the spreadsheet program shows it: column letters, row numbers, grid."""
    import openpyxl

    ws = openpyxl.load_workbook(src).active
    cols = [c for c in "ABCDEF"][:max(4, ws.max_column)]
    widths = {c: max(70, int((ws.column_dimensions[c].width or 10) * 7.2)) for c in cols}
    out = ['<div class="xl"><div class="xlbar"><span class="cellref">A1</span><span class="fx">fx</span>'
           f'<span class="formula">{html.escape(str(ws["A1"].value or ""))}</span></div><table class="grid"><tr><th class="corner"></th>']
    out += [f'<th style="width:{widths[c]}px">{c}</th>' for c in cols] + ["</tr>"]
    for r in range(1, max(ws.max_row, 20) + 1):
        out.append(f'<tr><th class="rn">{r}</th>')
        for c in cols:
            cell = ws[f"{c}{r}"]
            v = "" if cell.value is None else str(cell.value)
            b = " b" if cell.font and cell.font.bold else ""
            big = ' style="font-size:15px"' if cell.font and cell.font.size and cell.font.size > 12 else ""
            num = " num" if v[:1] in "$0123456789" else ""
            out.append(f'<td class="{b}{num}"{big}>{html.escape(v)}</td>')
        out.append("</tr>")
    out.append(f'</table><div class="tabs"><span class="tab on">{html.escape(ws.title)}</span><span class="plus">+</span></div></div>')
    dest.write_text("".join(out))


def eml_html(src: Path, dest: Path) -> None:
    m = email.message_from_bytes(src.read_bytes(), policy=email.policy.default)
    body = m.get_body(preferencelist=("plain", "html")).get_content()
    dest.write_text(f"""<div class="mail"><div class="subj">{html.escape(m['Subject'] or '')}</div>
<div class="from"><span class="avatar">{html.escape((m['From'] or '?')[:1])}</span><div><b>{html.escape(m['From'] or '')}</b>
<div class="to">To: {html.escape(m['To'] or '')}</div><div class="to">{html.escape(m['Date'] or '')}</div></div></div>
<pre class="body">{html.escape(body)}</pre></div>""")


folders = {}
for key, folder in FOLDERS.items():
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in TYPES)
    if SHOW[key]:
        files = [folder / n for n in SHOW[key] if (folder / n).exists()]
    rows = []
    for p in files:
        prev = OUT / (p.name + (".html" if p.suffix in (".eml", ".xlsx") else ".png"))
        if not prev.exists():
            if p.suffix == ".pdf":
                pdf_png(p, prev)
            elif p.suffix in (".jpg", ".png"):
                im = Image.open(p).convert("RGB")
                im.thumbnail((WIDTH, 1600))
                im.save(prev)
            elif p.suffix == ".docx":
                office_png(p, prev)
            elif p.suffix == ".xlsx":
                xlsx_html(p, prev)
            elif p.suffix == ".eml":
                eml_html(p, prev)
        st = p.stat()
        npages = len(pdfium.PdfDocument(str(p))) if p.suffix == ".pdf" else 1
        rows.append({"name": p.name, "path": str(p), "type": TYPES[p.suffix.lower()], "pages": npages,
                     "size": f"{max(1, round(st.st_size / 1024)):,} KB",
                     "date": time.strftime("%d-%m-%Y %H:%M", time.localtime(st.st_mtime)), "preview": str(prev)})
    folders[key] = {"crumbs": ["This PC", "Documents", "DocIntel", "samples", key], "files": rows}
folders["samples"] = {"crumbs": ["This PC", "Documents", "DocIntel", "samples"],
                      "files": [{"name": n, "folder": True, "type": "File folder", "size": "",
                                 "date": time.strftime("%d-%m-%Y %H:%M", time.localtime((REPO / "samples" / n).stat().st_mtime))}
                                for n in ("demo", "ground_truth", "input", "stress", "upload")]}
(OUT / "folders.json").write_text(json.dumps(folders, indent=1))
print({k: len(v["files"]) for k, v in folders.items()})
