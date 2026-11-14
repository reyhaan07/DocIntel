"""Any document file -> a PDF the pipeline reads.

PDFs are read directly and images become image pages (see pipeline).  Everything else -
Word, Excel, PowerPoint, OpenDocument, HTML, e-mail, text, Markdown, CSV, JSON, RTF -
is read for its *structure* (headings, paragraphs, label/value lines, tables, lists,
tick boxes) with the Python standard library and laid out as a clean PDF.  The PDF is
what the user sees in the viewer, so every extracted value still points at a box on a
page, and the same reading rules apply to every format.

Nothing is guessed during conversion: text is copied as written, cells stay cells.
"""
from __future__ import annotations

import csv
import email
import email.policy
import html
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

FORMATS = {
    ".docx": "Word document", ".docm": "Word document", ".xlsx": "Excel workbook", ".xlsm": "Excel workbook",
    ".pptx": "PowerPoint presentation", ".odt": "OpenDocument text", ".ods": "OpenDocument spreadsheet",
    ".odp": "OpenDocument presentation", ".html": "web page", ".htm": "web page", ".xhtml": "web page",
    ".eml": "e-mail", ".txt": "text", ".text": "text", ".md": "Markdown", ".markdown": "Markdown",
    ".csv": "CSV table", ".tsv": "tab-separated table", ".json": "JSON data", ".rtf": "rich text",
    ".xml": "XML data", ".log": "text",
}


@dataclass
class Block:
    kind: str  # heading | para | kv | table | item | check | rule | page
    text: str = ""
    level: int = 1
    label: str = ""
    rows: list = field(default_factory=list)
    header: bool = True
    bold: bool = False
    checked: bool | None = None


def can_convert(path: str | Path) -> bool:
    return Path(path).suffix.lower() in FORMATS


def describe(path: str | Path) -> str:
    return FORMATS.get(Path(path).suffix.lower(), "document")


# --------------------------------------------------------------------------- shared helpers
_BOX_ON = "☒☑✔✓■▣"
_BOX_OFF = "☐□▢"


def _boxes(text: str) -> str:
    """Tick-box characters become the printed boxes the reader knows: [X] / [ ]."""
    for ch in _BOX_ON:
        text = text.replace(ch, "[X]")
    for ch in _BOX_OFF:
        text = text.replace(ch, "[ ]")
    return text


def _clean(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\t", "    ")
    return _boxes(re.sub(r"[ \u2000-\u200b]+", " ", text).strip())


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _kv_or_para(line: str, bold: bool = False) -> Block:
    return Block("para", _clean(line), bold=bold)


# --------------------------------------------------------------------------- Word (.docx)
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx_par_text(p) -> tuple[str, bool]:
    parts, bolds = [], []
    for node in p.iter():
        t = _local(node.tag)
        if t == "t":
            parts.append(node.text or "")
        elif t == "tab":
            parts.append("    ")
        elif t in ("br", "cr"):
            parts.append("\n")
        elif t == "sym":  # Wingdings tick boxes
            ch = node.get(W + "char", "")
            parts.append("[X]" if ch.upper() in ("F0FE", "F078", "F0FD", "F0FC") else "[ ]" if ch.upper() in ("F0A8", "F06F", "F071") else "")
        elif t == "checkbox":  # content-control check box (w14:checkbox)
            state = next((c for c in node.iter() if _local(c.tag) == "checked"), None)
            on = state is not None and state.get("{http://schemas.microsoft.com/office/word/2010/wordml}val", "0") in ("1", "true")
            parts.append("[X] " if on else "[ ] ")
        elif t == "r":
            rpr = node.find(W + "rPr")
            txt = "".join(x.text or "" for x in node.iter(W + "t"))
            if txt.strip():
                bolds.append(rpr is not None and rpr.find(W + "b") is not None
                             and rpr.find(W + "b").get(W + "val", "true") not in ("0", "false"))
    text = "".join(parts)
    return text, bool(bolds) and all(bolds)


def _docx_style(p) -> str:
    ppr = p.find(W + "pPr")
    st = ppr.find(W + "pStyle") if ppr is not None else None
    return (st.get(W + "val") or "") if st is not None else ""


def _docx_blocks(path: Path) -> list[Block]:
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(W + "body")
    out: list[Block] = []
    for el in list(body) if body is not None else []:
        tag = _local(el.tag)
        if tag == "p":
            text, bold = _docx_par_text(el)
            style = _docx_style(el).lower()
            numbered = el.find(f"{W}pPr/{W}numPr") is not None
            for line in text.split("\n"):
                if not line.strip():
                    continue
                m = re.match(r"heading\s*(\d)", style) or re.match(r"title", style)
                if m:
                    out.append(Block("heading", _clean(line), level=int(m.group(1)) if m.re.pattern.startswith("heading") else 0))
                elif numbered or style.startswith("list"):
                    out.append(Block("item", _clean(line)))
                else:
                    out.append(Block("para", _clean(line), bold=bold))
        elif tag == "tbl":
            rows = []
            for tr in el.iter(W + "tr"):
                cells = []
                for tc in tr.findall(W + "tc"):
                    cells.append(_clean(" ".join(_docx_par_text(p)[0] for p in tc.iter(W + "p"))))
                if any(cells):
                    rows.append(cells)
            if rows:
                out.append(Block("table", rows=rows))
        elif tag == "sectPr":
            continue
    return out


# --------------------------------------------------------------------------- Excel (.xlsx)
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _xlsx_blocks(path: Path) -> list[Block]:
    out: list[Block] = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(S + "si"):
                shared.append("".join(t.text or "" for t in si.iter(S + "t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {}
        if "xl/_rels/workbook.xml.rels" in names:
            for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")):
                rels[r.get("Id")] = r.get("Target")
        sheets = []
        for sh in wb.iter(S + "sheet"):
            target = rels.get(sh.get(R + "id"), "")
            target = target.lstrip("/")
            target = target if target.startswith("xl/") else "xl/" + target
            sheets.append((sh.get("name"), target))
        for k, (name, target) in enumerate(sheets):
            if target not in names:
                continue
            grid: dict[tuple[int, int], str] = {}
            for c in ET.fromstring(z.read(target)).iter(S + "c"):
                ref, t = c.get("r") or "", c.get("t")
                v = c.find(S + "v")
                if t == "s" and v is not None:
                    val = shared[int(v.text)] if v.text and v.text.isdigit() and int(v.text) < len(shared) else ""
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(S + "t"))
                elif t == "b" and v is not None:
                    val = "TRUE" if v.text == "1" else "FALSE"
                else:
                    val = v.text if v is not None and v.text is not None else ""
                    if re.fullmatch(r"-?\d+\.\d{6,}", val or ""):
                        val = f"{float(val):.6g}"
                if val.strip() and re.match(r"[A-Z]+\d+", ref):
                    grid[(int(re.search(r"\d+", ref).group(0)) - 1, _col_index(ref))] = _clean(val)
            if not grid:
                continue
            out.append(Block("heading", name or f"Sheet {k + 1}", level=1))
            r0, r1 = min(r for r, _ in grid), max(r for r, _ in grid)
            c0, c1 = min(c for _, c in grid), max(c for _, c in grid)
            rows = [[grid.get((r, c), "") for c in range(c0, c1 + 1)] for r in range(r0, r1 + 1)]
            out += _grid_blocks(rows)
    return out


def _grid_blocks(rows: list[list[str]]) -> list[Block]:
    """A sheet: blank rows separate parts; a part of two columns whose left cells are
    labels is a list of label/value lines, anything wider is a table."""
    parts, cur = [], []
    for r in rows:
        if any(x.strip() for x in r):
            cur.append(r)
        elif cur:
            parts.append(cur)
            cur = []
    if cur:
        parts.append(cur)
    out: list[Block] = []
    for part in parts:
        used = [i for i in range(max(len(r) for r in part)) if any(i < len(r) and r[i].strip() for r in part)]
        part = [[r[i] if i < len(r) else "" for i in used] for r in part]
        if len(used) == 1 or all(sum(1 for x in r if x.strip()) == 1 for r in part):
            out += [Block("para", next(x for x in r if x.strip())) for r in part]
        elif len(used) == 2 and all(re.search(r"[A-Za-z]", r[0]) and not re.search(r"\d", r[0]) for r in part if r[0].strip()) \
                and not all(re.search(r"[A-Za-z]", r[1]) and not re.search(r"\d", r[1]) for r in part if r[1].strip()):
            out += [Block("kv", r[1], label=r[0]) for r in part if r[0].strip()]
        else:
            out.append(Block("table", rows=part))
    return out


# --------------------------------------------------------------------------- PowerPoint (.pptx)
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"


def _pptx_blocks(path: Path) -> list[Block]:
    out: list[Block] = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        order = []
        if "ppt/presentation.xml" in names and "ppt/_rels/presentation.xml.rels" in names:
            rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("ppt/_rels/presentation.xml.rels"))}
            for s in ET.fromstring(z.read("ppt/presentation.xml")).iter(P + "sldId"):
                t = rels.get(s.get(R + "id"), "")
                order.append("ppt/" + t.lstrip("/").replace("ppt/", "") if t else "")
        if not order:
            order = sorted((n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                           key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
        for k, name in enumerate(order, start=1):
            if name not in names:
                continue
            root = ET.fromstring(z.read(name))
            if k > 1:
                out.append(Block("page"))
            start = len(out)
            title = None
            for sp in root.iter(P + "sp"):
                ph = sp.find(f"{P}nvSpPr/{P}nvPr/{P}ph")
                paras = ["".join(t.text or "" for t in p.iter(A + "t")) for p in sp.iter(A + "p")]
                paras = [_clean(x) for x in paras if x.strip()]
                if not paras:
                    continue
                if ph is not None and (ph.get("type") or "") in ("title", "ctrTitle") and title is None:
                    title = " ".join(paras)
                    out.append(Block("heading", f"Slide {k}: {title}", level=1))
                    continue
                for x in paras:
                    out.append(Block("item" if len(paras) > 1 else "para", x))
            if title is None:
                out.insert(start, Block("heading", f"Slide {k}", level=1))
            for tbl in root.iter(A + "tbl"):
                rows = [[_clean("".join(t.text or "" for t in tc.iter(A + "t"))) for tc in tr.iter(A + "tc")]
                        for tr in tbl.iter(A + "tr")]
                if rows:
                    out.append(Block("table", rows=rows))
    return out


# --------------------------------------------------------------------------- OpenDocument (.odt .ods .odp)
TX = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
TB = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
DR = "{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}"


def _odf_text(el) -> str:
    out = []
    for node in el.iter():
        t = _local(node.tag)
        if node is not el and t in ("p", "h"):
            continue
        if node.text and t not in ("table", "table-row"):
            out.append(node.text)
        if t == "s":
            out.append(" " * int(node.get(TX + "c", "1")))
        elif t == "tab":
            out.append("    ")
        elif t == "line-break":
            out.append("\n")
        if node is not el and node.tail:
            out.append(node.tail)
    return "".join(out)


def _odf_blocks(path: Path) -> list[Block]:
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("content.xml"))
    out: list[Block] = []

    def walk(el):
        for child in el:
            t = _local(child.tag)
            if t == "h":
                txt = _clean(" ".join(x.strip() for x in child.itertext()))
                if txt:
                    out.append(Block("heading", txt, level=int(child.get(TX + "outline-level", "1"))))
            elif t == "p":
                txt = _clean("".join(child.itertext()))
                if txt:
                    out.append(Block("para", txt))
            elif t == "list":
                for li in child.iter(TX + "list-item"):
                    txt = _clean(" ".join("".join(p.itertext()) for p in li.findall(TX + "p")))
                    if txt:
                        out.append(Block("item", txt))
            elif t == "table":
                rows = []
                for tr in child.iter(TB + "table-row"):
                    rep = int(tr.get(TB + "number-rows-repeated", "1"))
                    cells = []
                    for tc in tr:
                        if _local(tc.tag) not in ("table-cell", "covered-table-cell"):
                            continue
                        n = min(int(tc.get(TB + "number-columns-repeated", "1")), 50)
                        cells += [_clean(" ".join("".join(p.itertext()) for p in tc.iter(TX + "p")))] * n
                    while cells and not cells[-1]:
                        cells.pop()
                    if any(cells):
                        rows += [cells] * min(rep, 1)
                if rows:
                    name = child.get(TB + "name")
                    if path.suffix.lower() == ".ods" and name:
                        out.append(Block("heading", name, level=1))
                    width = max(len(r) for r in rows)
                    out.extend(_grid_blocks([r + [""] * (width - len(r)) for r in rows]) if path.suffix.lower() == ".ods"
                               else [Block("table", rows=[r + [""] * (width - len(r)) for r in rows])])
            elif t == "page":  # presentation slide
                if out:
                    out.append(Block("page"))
                out.append(Block("heading", child.get(DR + "name") or "Slide", level=1))
                walk(child)
            else:
                walk(child)

    body = next((e for e in root.iter() if _local(e.tag) == "body"), root)
    walk(body)
    return out


# --------------------------------------------------------------------------- HTML
class _HTML(HTMLParser):
    BLOCK = {"p", "div", "section", "article", "header", "footer", "main", "aside", "address", "blockquote",
             "pre", "form", "fieldset", "figcaption", "caption", "center"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[Block] = []
        self.buf: list[str] = []
        self.skip = 0
        self.heading = 0
        self.bold = 0
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.dt: str | None = None
        self.labels: dict[str, str] = {}
        self.pending_label: str | None = None
        self.title = ""
        self.in_title = False
        self.select_label: str | None = None

    def flush(self, kind="para"):
        text = _clean(" ".join("".join(self.buf).split()))
        self.buf = []
        if not text:
            return
        if self.heading:
            self.out.append(Block("heading", text, level=self.heading))
        elif kind == "item":
            self.out.append(Block("item", text))
        else:
            self.out.append(Block("para", text, bold=self.bold > 0))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "noscript", "template", "svg"):
            self.skip += 1
            return
        if tag == "title":
            self.in_title = True
        if self.cell is not None:
            if tag == "br":
                self.cell.append(" ")
            elif tag == "input":
                self.cell.append(self._input_text(a))
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.flush()
            self.heading = int(tag[1])
        elif tag in self.BLOCK or tag in ("li", "dt", "dd", "tr", "hr"):
            self.flush()
        if tag in ("b", "strong", "th"):
            self.bold += 1
        if tag == "br":
            self.flush()
        elif tag == "hr":
            self.out.append(Block("rule"))
        elif tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag == "label":
            self.flush()
        elif tag == "input":
            typ = (a.get("type") or "text").lower()
            if typ in ("hidden", "submit", "button", "image", "reset"):
                return
            label = self.labels.get(a.get("id") or "") or self.pending_label or _clean("".join(self.buf)) \
                or a.get("aria-label") or a.get("placeholder") or a.get("name") or ""
            self.buf = []
            self.pending_label = None
            if typ in ("checkbox", "radio"):
                self.out.append(Block("check", label or a.get("value", ""), checked="checked" in a))
            else:
                self.out.append(Block("kv", a.get("value", ""), label=label.rstrip(":")))
        elif tag == "textarea":
            self.flush()
        elif tag == "option" and "selected" in a and self.select_label is not None:
            self.pending_label = None
        elif tag == "select":
            self.select_label = self.pending_label or _clean("".join(self.buf))
            self.buf = []

    def _input_text(self, a):
        typ = (a.get("type") or "text").lower()
        if typ in ("checkbox", "radio"):
            return "[X] " if "checked" in a else "[ ] "
        return a.get("value", "")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template", "svg"):
            self.skip = max(0, self.skip - 1)
            return
        if tag == "title":
            self.in_title = False
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(_clean(" ".join("".join(self.cell).split())))
            self.cell = None
        elif tag == "tr" and self.row is not None and self.table is not None:
            if any(self.row):
                self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            rows = self.table
            self.table = None
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                if width == 2 and all(r[0].rstrip().endswith(":") for r in rows if r[0].strip()):
                    self.out += [Block("kv", r[1], label=r[0].rstrip(":")) for r in rows]
                else:
                    self.out.append(Block("table", rows=rows))
        if self.cell is not None:
            return
        if tag in ("b", "strong", "th"):
            self.bold = max(0, self.bold - 1)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.flush()
            self.heading = 0
        elif tag == "dt":
            self.dt = _clean("".join(self.buf))
            self.buf = []
        elif tag == "dd":
            val = _clean(" ".join("".join(self.buf).split()))
            self.buf = []
            if self.dt is not None:
                self.out.append(Block("kv", val, label=self.dt.rstrip(":")))
                self.dt = None
            elif val:
                self.out.append(Block("para", val))
        elif tag == "label":
            self.pending_label = _clean("".join(self.buf)).rstrip(":") or None
            self.buf = []
        elif tag == "li":
            self.flush("item")
        elif tag == "select":
            self.select_label = None
        elif tag in self.BLOCK or tag in ("textarea",):
            self.flush()

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_title:
            self.title += data
            return
        if self.cell is not None:
            self.cell.append(data)
        else:
            self.buf.append(data)

    def close(self):
        super().close()
        self.flush()


def _html_blocks(text: str) -> list[Block]:
    p = _HTML()
    p.feed(text)
    p.close()
    blocks = p.out
    if p.title.strip() and not any(b.kind == "heading" for b in blocks[:3]):
        blocks.insert(0, Block("heading", _clean(p.title), level=1))
    return blocks


# --------------------------------------------------------------------------- text, Markdown
def _text_blocks(text: str, markdown: bool = False) -> list[Block]:
    out: list[Block] = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    while i < len(lines):
        raw = lines[i].rstrip()
        line = raw.strip()
        if not line:
            i += 1
            continue
        # a table written with pipes (Markdown) or as aligned columns of a text file
        if line.startswith("|") or (markdown and line.count("|") >= 2):
            rows = []
            while i < len(lines) and lines[i].strip().count("|") >= 1:
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    rows.append([_clean(re.sub(r"[*_`]", "", c)) for c in cells])
                i += 1
            if rows:
                width = max(len(r) for r in rows)
                out.append(Block("table", rows=[r + [""] * (width - len(r)) for r in rows]))
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line) if markdown else None
        if m:
            out.append(Block("heading", _clean(m.group(2).strip("# ")), level=len(m.group(1))))
        elif markdown and i + 1 < len(lines) and re.fullmatch(r"(=+|-+)", lines[i + 1].strip() or "x") and len(lines[i + 1].strip()) >= 3:
            out.append(Block("heading", _clean(line), level=1 if lines[i + 1].strip()[0] == "=" else 2))
            i += 1
        elif re.fullmatch(r"[-*_=]{3,}", line):
            out.append(Block("rule"))
        elif re.match(r"^([-*+•]|\d+[.)])\s+", line):
            out.append(Block("item", _clean(re.sub(r"^([-*+•]|\d+[.)])\s+", "", line))))
        else:
            text_ = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda mm: mm.group(1) or mm.group(2), line) if markdown else line
            out.append(Block("para", _clean(text_), bold=markdown and line.startswith("**") and line.endswith("**")))
        i += 1
    return out


# --------------------------------------------------------------------------- e-mail (.eml)
def _eml_blocks(data: bytes) -> list[Block]:
    msg = email.message_from_bytes(data, policy=email.policy.default)
    out = [Block("heading", _clean(str(msg.get("Subject") or "E-mail")), level=1)]
    for h in ("From", "To", "Cc", "Date", "Subject", "Reply-To"):
        if msg.get(h):
            out.append(Block("kv", _clean(str(msg.get(h))), label=h))
    body = msg.get_body(preferencelist=("plain", "html"))
    if body is not None:
        content = body.get_content()
        if body.get_content_type() == "text/html":
            out += _html_blocks(content)
        else:
            out += _text_blocks(content)
    atts = [a.get_filename() for a in msg.iter_attachments() if a.get_filename()]
    if atts:
        out.append(Block("heading", "Attachments", level=2))
        out += [Block("item", _clean(a)) for a in atts]
    return out


# --------------------------------------------------------------------------- CSV, JSON, RTF, XML
def _csv_blocks(text: str, delimiter: str | None = None) -> list[Block]:
    sample = text[:4096]
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    rows = [[_clean(c) for c in r] for r in csv.reader(io.StringIO(text), delimiter=delimiter)]
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    return _grid_blocks([r + [""] * (width - len(r)) for r in rows])


def _json_blocks(data) -> list[Block]:
    out: list[Block] = []

    def label(path):
        return " ".join(re.sub(r"[_\-]+", " ", p).strip().capitalize() if i == len(path) - 1 else
                        re.sub(r"[_\-]+", " ", p).strip() for i, p in enumerate(path)) or "Value"

    def walk(obj, path, level):
        if isinstance(obj, dict):
            scalars = [(k, v) for k, v in obj.items() if not isinstance(v, (dict, list))]
            for k, v in scalars:
                out.append(Block("kv", "" if v is None else str(v), label=label(path[-1:] + [str(k)]) if level else label([str(k)])))
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    out.append(Block("heading", label([str(k)]), level=min(level + 1, 3)))
                    walk(v, path + [str(k)], level + 1)
        elif isinstance(obj, list):
            if obj and all(isinstance(x, dict) for x in obj):
                keys = []
                for x in obj:
                    for k, v in x.items():
                        if not isinstance(v, (dict, list)) and k not in keys:
                            keys.append(k)
                if keys:
                    out.append(Block("table", rows=[[label([k]) for k in keys]] +
                                     [["" if x.get(k) is None else str(x.get(k)) for k in keys] for x in obj]))
                for i, x in enumerate(obj, start=1):
                    nested = {k: v for k, v in x.items() if isinstance(v, (dict, list))}
                    if nested:
                        out.append(Block("heading", f"{label(path[-1:]) if path else 'Item'} {i}", level=min(level + 1, 3)))
                        walk(nested, path, level + 1)
            else:
                out.extend(Block("item", str(x)) for x in obj if not isinstance(x, (dict, list)))
                for x in obj:
                    if isinstance(x, (dict, list)):
                        walk(x, path, level + 1)
        else:
            out.append(Block("para", str(obj)))

    walk(data, [], 0)
    return out


def _rtf_text(rtf: str) -> str:
    """Plain text of an RTF file: control words removed, paragraphs kept."""
    out, stack, ignore = [], [], False
    i, n = 0, len(rtf)
    skip_groups = ("fonttbl", "colortbl", "stylesheet", "info", "pict", "header", "footer", "listtable",
                   "listoverridetable", "rsidtbl", "generator", "xmlnstbl", "themedata", "colorschememapping",
                   "latentstyles", "datastore", "fldinst")
    while i < n:
        ch = rtf[i]
        if ch == "{":
            stack.append(ignore)
            i += 1
        elif ch == "}":
            ignore = stack.pop() if stack else False
            i += 1
        elif ch == "\\":
            m = re.match(r"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\(.)", rtf[i:])
            if not m:
                i += 1
                continue
            word, arg, hexch, sym = m.groups()
            i += m.end()
            if ignore:
                continue
            if word:
                if word in skip_groups or (word == "*"):
                    ignore = True
                elif word == "row":
                    out.append("\x1e\n")
                elif word in ("par", "line", "sect", "page"):
                    out.append("\n")
                elif word == "cell":
                    out.append("\x1f")
                elif word == "tab":
                    out.append("    ")
                elif word == "u" and arg:
                    out.append(chr(int(arg) % 65536))
            elif hexch:
                out.append(bytes([int(hexch, 16)]).decode("cp1252", errors="replace"))
            elif sym == "*":
                ignore = True
            elif sym in ("\\", "{", "}"):
                out.append(sym)
            elif sym == "~":
                out.append(" ")
        else:
            if not ignore and ch not in "\r\n":
                out.append(ch)
            i += 1
    return "".join(out)


def _rtf_blocks(text: str) -> list[Block]:
    """RTF text with table cells ended (\x1f) and rows ended (\x1e): paragraphs stay
    paragraphs, rows become a table."""
    out: list[Block] = []
    rows: list[list[str]] = []

    def flush_rows():
        nonlocal rows
        if rows:
            width = max(len(r) for r in rows)
            out.append(Block("table", rows=[r + [""] * (width - len(r)) for r in rows]))
            rows = []

    chunks = text.split("\x1e")
    for k, chunk in enumerate(chunks):
        if "\x1f" not in chunk:
            flush_rows()
            out.extend(_text_blocks(chunk))
            continue
        cells = chunk.split("\x1f")
        tail = cells.pop()  # text after the last cell of the row (normally empty)
        first = cells[0].strip("\n").split("\n")
        if len(first) > 1:  # paragraphs printed before the table began
            flush_rows()
            out.extend(_text_blocks("\n".join(first[:-1])))
            cells[0] = first[-1]
        row = [_clean(" ".join(c.split())) for c in cells]
        if any(row):
            rows.append(row)
        if tail.strip():
            flush_rows()
            out.extend(_text_blocks(tail))
    flush_rows()
    return out


def _xml_blocks(data: bytes) -> list[Block]:
    root = ET.fromstring(data)
    out = [Block("heading", _local(root.tag), level=1)]

    def walk(el, path):
        kids = list(el)
        text = (el.text or "").strip()
        if not kids and text:
            out.append(Block("kv", text, label=" ".join(path[-2:])))
        for k, v in el.attrib.items():
            out.append(Block("kv", v, label=f"{_local(el.tag)} {_local(k)}"))
        for c in kids:
            walk(c, path + [_local(c.tag)])

    walk(root, [_local(root.tag)])
    return out[:3000]


# --------------------------------------------------------------------------- entry
def read_blocks(path: str | Path) -> list[Block]:
    path = Path(path)
    ext = path.suffix.lower()
    if ext in (".docx", ".docm"):
        return _docx_blocks(path)
    if ext in (".xlsx", ".xlsm"):
        return _xlsx_blocks(path)
    if ext == ".pptx":
        return _pptx_blocks(path)
    if ext in (".odt", ".ods", ".odp"):
        return _odf_blocks(path)
    data = path.read_bytes()
    if ext == ".eml":
        return _eml_blocks(data)
    text = _decode(data)
    if ext in (".html", ".htm", ".xhtml"):
        return _html_blocks(text)
    if ext in (".md", ".markdown"):
        return _text_blocks(text, markdown=True)
    if ext == ".csv":
        return _csv_blocks(text)
    if ext == ".tsv":
        return _csv_blocks(text, "\t")
    if ext == ".json":
        return _json_blocks(json.loads(text))
    if ext == ".rtf":
        return _rtf_blocks(_rtf_text(text))
    if ext == ".xml":
        return _xml_blocks(data)
    looks_md = bool(re.search(r"(?m)^#{1,6}\s+\S|\*\*[^*\n]+\*\*|^\|.*\|\s*$", text))
    return _text_blocks(text, markdown=looks_md)


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16"):
        try:
            text = data.decode(enc)
            if enc == "utf-16" and not data[:2] in (b"\xff\xfe", b"\xfe\xff"):
                raise UnicodeError
            return text
        except UnicodeError:
            continue
    return data.decode("cp1252", errors="replace")


# --------------------------------------------------------------------------- layout to PDF
def render_pdf(blocks: list[Block], dest: str | Path, title: str = "") -> Path:
    """Lay the blocks out on letter pages: headings larger and bold, label/value lines as
    'Label: value', tables as ruled grids with a bold header row, items as bullets."""
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    W_, H_ = letter
    L, Rm, T, B = 54.0, 54.0, 54.0, 54.0
    width = W_ - L - Rm
    c = canvas.Canvas(str(dest), pagesize=letter)
    c.setTitle(title or "converted document")
    y = T
    regular, bold_font, unicode_ok = _fonts()

    def font(bold):
        return bold_font if bold else regular

    def safe(s):
        if unicode_ok:
            return s
        return "".join(ch if ord(ch) < 256 or ch in "•€–—‘’“”…" else "?" for ch in s)

    def wrap(text, size, bold, w):
        words, lines, cur = safe(text).split(" "), [], ""
        for wd in words:
            t = (cur + " " + wd).strip()
            if stringWidth(t, font(bold), size) <= w or not cur:
                if stringWidth(wd, font(bold), size) > w and not cur:  # one long word: cut it
                    while stringWidth(wd, font(bold), size) > w and len(wd) > 1:
                        k = max(1, int(len(wd) * w / stringWidth(wd, font(bold), size)) - 1)
                        lines.append(wd[:k])
                        wd = wd[k:]
                    t = wd
                cur = t
            else:
                lines.append(cur)
                cur = wd
        if cur:
            lines.append(cur)
        return lines or [""]

    def need(h):
        nonlocal y
        if y + h > H_ - B:
            c.showPage()
            y = T

    def text_line(s, x, size, bold, color="#000000"):
        c.setFont(font(bold), size)
        c.setFillColor(HexColor(color))
        c.drawString(x, H_ - y - size, s)

    for b in blocks:
        if b.kind == "page":
            c.showPage()
            y = T
        elif b.kind == "heading":
            size = {0: 18, 1: 15, 2: 13, 3: 11.5}.get(b.level, 11)
            lines = wrap(b.text, size, True, width)
            need(size * 1.3 * len(lines) + 14)
            y += 10
            for ln in lines:
                text_line(ln, L, size, True, "#1f2d4d")
                y += size * 1.3
            y += 4
        elif b.kind == "item" and re.match(r"^[^:]{1,40}:\s+\S", b.text):
            label, value = b.text.split(":", 1)
            blocks_kv = Block("kv", value.strip(), label=label)
            size = 10
            lw = stringWidth(safe(label) + ":", font(True), size)
            vlines = wrap(blocks_kv.text, size, False, max(80, width - lw - 6))
            need(size * 1.35 * len(vlines) + 4)
            text_line(safe(label) + ":", L, size, True)
            for ln in vlines:
                c.setFont(font(False), size)
                c.setFillColor(HexColor("#000000"))
                c.drawString(L + lw + 6, H_ - y - size, ln)
                y += size * 1.35
            y += 3
        elif b.kind in ("para", "item"):
            size = 10
            x = L + (14 if b.kind == "item" else 0)
            lines = wrap(b.text, size, b.bold, width - (x - L))
            need(size * 1.35 * len(lines) + 4)
            for k, ln in enumerate(lines):
                if b.kind == "item" and k == 0:
                    text_line("•", L + 4, size, False)
                text_line(ln, x, size, b.bold)
                y += size * 1.35
            y += 3
        elif b.kind == "kv":
            size = 10
            label = safe(b.label.rstrip(": ")) + ":"
            lw = stringWidth(label, font(True), size)
            vlines = wrap(b.text, size, False, max(80, width - lw - 6))
            need(size * 1.35 * len(vlines) + 4)
            text_line(label, L, size, True)
            for k, ln in enumerate(vlines):
                c.setFont(font(False), size)
                c.setFillColor(HexColor("#000000"))
                c.drawString(L + lw + 6, H_ - y - size, ln)
                y += size * 1.35
            y += 3
        elif b.kind == "check":
            size = 10
            need(size * 1.4 + 4)
            text_line(("[X] " if b.checked else "[ ] ") + safe(b.text), L, size, False)
            y += size * 1.4 + 3
        elif b.kind == "rule":
            need(10)
            c.setStrokeColor(HexColor("#999999"))
            c.line(L, H_ - y - 4, W_ - Rm, H_ - y - 4)
            y += 10
        elif b.kind == "table" and b.rows:
            ncol = max(len(r) for r in b.rows)
            rows = [list(r) + [""] * (ncol - len(r)) for r in b.rows]
            size = 9 if ncol <= 6 else 8 if ncol <= 9 else 7
            natural = [max(stringWidth(safe(r[i]), font(k == 0), size) for k, r in enumerate(rows)) + 26 for i in range(ncol)]
            total = sum(natural)
            colw = [width * n / total for n in natural] if total > width else natural
            colw = [max(w, 28.0) for w in colw]
            scale = min(1.0, width / sum(colw))
            colw = [w * scale for w in colw]
            for k, r in enumerate(rows):
                cells = [wrap(r[i], size, k == 0, colw[i] - 20) for i in range(ncol)]
                h = max(len(x) for x in cells) * size * 1.25 + 6
                need(h + 2)
                x = L
                c.setStrokeColor(HexColor("#b8c2d0"))
                c.setLineWidth(0.5)
                for i in range(ncol):
                    c.rect(x, H_ - y - h, colw[i], h, stroke=1, fill=0)
                    for j, ln in enumerate(cells[i]):
                        c.setFont(font(k == 0), size)
                        c.setFillColor(HexColor("#000000"))
                        c.drawString(x + 6, H_ - y - 3 - size - j * size * 1.25, ln)
                    x += colw[i]
                y += h
            y += 8
    c.showPage()
    c.save()
    return Path(dest)


_FONT_CACHE: tuple | None = None


def _fonts() -> tuple[str, str, bool]:
    """A Unicode TrueType font when the machine has one (so text in any script survives
    the conversion), else the PDF standard fonts (Western European characters)."""
    global _FONT_CACHE
    if _FONT_CACHE is not None:
        return _FONT_CACHE
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    pairs = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"),
        ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
        ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ]
    for reg, bold in pairs:
        if Path(reg).exists() and Path(bold).exists():
            try:
                pdfmetrics.registerFont(TTFont("DI-Regular", reg))
                pdfmetrics.registerFont(TTFont("DI-Bold", bold))
                _FONT_CACHE = ("DI-Regular", "DI-Bold", True)
                return _FONT_CACHE
            except Exception:  # an unreadable font file: try the next
                continue
    _FONT_CACHE = ("Helvetica", "Helvetica-Bold", False)
    return _FONT_CACHE


def convert_to_pdf(src: str | Path, dest: str | Path) -> Path:
    """Read any supported file and write its structured PDF to ``dest``."""
    src = Path(src)
    blocks = read_blocks(src)
    if not blocks:
        blocks = [Block("para", f"(no text found in this {describe(src)})")]
    return render_pdf(blocks, dest, title=src.name)
