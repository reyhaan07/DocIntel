"""Runs the five stages on one PDF and assembles the per-document JSON."""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

from .bind import TYPE_NAMES, Binder
from .generic import GENERIC_TYPE_NAMES, build_blocks, build_generic, extract_structure
from .ocr import engine_name as ocr_engine_name
from .ocr import unskew_bbox
from .read import ocr_available, read_pdf
from .relate import relate
from .template import Template, load_template
from .validate import CHECKS, review_queue, validate

SCHEMA_VERSION = "1.1"
MIN_TEMPLATE_SECTIONS = 3  # distinct template sections a document must show before the template applies
TYPE_LABELS = {**TYPE_NAMES, **GENERIC_TYPE_NAMES}


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _extraction_method(pages) -> str:
    if any(p.ocr_used for p in pages):
        return "ocr"
    if any(p.form_fields for p in pages):
        return "form_fields"
    if any(p.has_text for p in pages):
        return "layout"
    return "none"


def _title(binder) -> str | None:
    """The document's own title: the first heading on the first page."""
    first = sorted((r for r in binder.regions if r.page == 1 and r.heading and not r.continued), key=lambda r: r.top)
    return first[0].name if first else None


def _unskew(doc: dict, pages) -> None:
    """Scanned pages are read straightened; map every box back onto the original scan."""
    angles = {p.number: (p.deskew_angle, p.width, p.height) for p in pages if p.ocr_used and p.deskew_angle}
    if not angles:
        return

    def fix(d: dict, keys=("bbox", "label_bbox", "heading_bbox", "row_bbox")):
        if d.get("page") in angles:
            a, w, h = angles[d["page"]]
            for k in keys:
                if d.get(k):
                    d[k] = unskew_bbox(d[k], a, w, h)

    for sec in doc["sections"]:
        fix(sec, ("bbox",))
        if sec.get("heading_page") in angles and sec.get("heading_bbox"):
            a, w, h = angles[sec["heading_page"]]
            sec["heading_bbox"] = unskew_bbox(sec["heading_bbox"], a, w, h)
    for e in doc["entities"].values():
        fix(e, ("row_bbox",))
        for a in e["attributes"].values():
            fix(a)
    for r in doc["relationships"]:
        for ev in r["evidence"]:
            fix(ev)
    for item in doc["missing"] + doc["review_queue"] + doc.get("blocks", []):
        fix(item)


# --------------------------------------------------------------------------- packets
def find_packets(pages, template: Template) -> list[list[int]]:
    """Page groups that are separate filled forms (several patients scanned into one file).

    A new packet starts on a page where the form's first section (e.g. the patient's
    details) appears again; both sides of the split must look like complete forms."""
    all_pages = [p.number for p in pages]
    if len(pages) < 2:
        return [all_pages]
    binder = Binder(pages, template)
    regions = [r for r in binder.regions if not r.continued and not r.key.startswith("other:")]
    if len({r.key for r in regions}) < MIN_TEMPLATE_SECTIONS:
        return [all_pages]
    anchor = min(regions, key=lambda r: (r.page, r.top)).key
    starts = sorted({r.page for r in regions if r.key == anchor})
    if len(starts) < 2:
        return [all_pages]
    cuts = [all_pages[0]] + [p for p in starts[1:]]
    groups = [list(range(a, b)) for a, b in zip(cuts, cuts[1:] + [all_pages[-1] + 1])]

    def sections(group):
        return {r.key for r in regions if r.page in group}

    merged: list[list[int]] = []
    for g in groups:  # a fragment that is not a form of its own stays with the packet before it
        if merged and len(sections(g)) < MIN_TEMPLATE_SECTIONS:
            merged[-1] += g
        else:
            merged.append(g)
    if len(merged) > 1 and len(sections(merged[0])) < MIN_TEMPLATE_SECTIONS:
        merged[1] = merged[0] + merged[1]
        merged.pop(0)
    return merged


def _subset(pages, numbers: list[int]):
    """Copies of the given pages, renumbered from 1."""
    import copy

    out = []
    for new, pd in enumerate([p for p in pages if p.number in numbers], start=1):
        c = copy.copy(pd)
        c.number = new
        c.tokens = []
        for t in pd.tokens:
            t2 = copy.copy(t)
            t2.page = new
            c.tokens.append(t2)
        c.marks = []
        for m in pd.marks:
            m2 = copy.copy(m)
            m2.page = new
            c.marks.append(m2)
        out.append(c)
    return out


def write_pages(src: str | Path, numbers: list[int], dest: str | Path) -> Path:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(src))
    if reader.is_encrypted:
        reader.decrypt("")
    w = PdfWriter()
    for n in numbers:
        w.add_page(reader.pages[n - 1])
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as fh:
        w.write(fh)
    return dest


IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}


def is_pdf(path: str | Path) -> bool:
    with open(path, "rb") as fh:
        return fh.read(1024).lstrip().startswith(b"%PDF")


def image_to_pdf(src: str | Path, dest: str | Path) -> Path:
    """Photos and scans delivered as image files become image-only PDF pages (one per frame)."""
    from PIL import Image, ImageOps

    im = Image.open(src)
    frames = []
    i = 0
    while True:
        try:
            im.seek(i)
        except EOFError:
            break
        fr = ImageOps.exif_transpose(im.copy()).convert("RGB")
        frames.append(fr)
        i += 1
    if not frames:
        raise RuntimeError("the image file has no pages")
    dpi = im.info.get("dpi", (0, 0))[0] or 0
    if not dpi or dpi < 72:  # unknown resolution: assume the page is about letter width
        dpi = max(100, min(400, frames[0].width / 8.5))
    dest = Path(dest)
    frames[0].save(dest, "PDF", save_all=True, append_images=frames[1:], resolution=float(dpi))
    return dest


def _upright_copy(src: Path, rotations: dict[int, int], dest: Path) -> Path:
    """A copy of the PDF with sideways scanned pages turned upright for viewing."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(src))
    if reader.is_encrypted:
        reader.decrypt("")
    w = PdfWriter()
    for i, page in enumerate(reader.pages, start=1):
        if rotations.get(i):
            page.rotate(rotations[i])
        w.add_page(page)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as fh:
        w.write(fh)
    return dest


def process_file(path: str | Path, target, *, filename: str | None = None, template: Template | None = None,
                 ocr: bool | str = "auto") -> list[dict]:
    """Process one uploaded file (PDF or image), which may hold several separate packets.

    ``target(index, count, page_numbers)`` returns ``{"doc_id", "source_path",
    "standardized_path", "keep_source"}`` for each packet.  The packet's own PDF is
    written to ``source_path`` when it differs from the upload (a split, an image turned
    into a PDF, a sideways scan turned upright) or when ``keep_source`` asks for a copy."""
    import shutil
    import tempfile

    path = Path(path)
    template = template or load_template()
    filename = filename or path.name
    work = Path(tempfile.mkdtemp(prefix="docintel-"))
    try:
        if not is_pdf(path):
            path = image_to_pdf(path, work / "converted.pdf")
        pages = read_pdf(path, ocr=ocr)
        rotations = {p.number: p.rotation for p in pages if p.rotation}
        if rotations:
            path = _upright_copy(path, rotations, work / "upright.pdf")
        transformed = path.parent == work
        groups = find_packets(pages, template)
        docs = []
        for k, group in enumerate(groups, start=1):
            tgt = target(k, len(groups), group)
            if len(groups) == 1:
                src = path
                if tgt.get("source_path") and (transformed or tgt.get("keep_source")):
                    src = Path(tgt["source_path"])
                    src.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, src)
                doc = process_pdf(src, tgt["doc_id"], filename=filename, template=template, ocr=ocr,
                                  standardized_path=tgt.get("standardized_path"), pages=pages)
                docs.append(doc)
                continue
            src = write_pages(path, group, tgt["source_path"])
            name = f"{filename} - packet {k} of {len(groups)} (pages {group[0]}-{group[-1]})"
            doc = process_pdf(src, tgt["doc_id"], filename=name, template=template, ocr=ocr,
                              standardized_path=tgt.get("standardized_path"), pages=_subset(pages, group))
            doc["document"]["packet"] = {"index": k, "count": len(groups), "source_file": filename,
                                         "source_pages": group, "source_sha256": sha256_file(path)}
            docs.append(doc)
        return docs
    finally:
        shutil.rmtree(work, ignore_errors=True)


def process_pdf(path: str | Path, doc_id: str = "DOC_001", *, filename: str | None = None,
                template: Template | None = None, ocr: bool | str = "auto", standardized_path: str | Path | None = None,
                processed_at: str | None = None, pages=None) -> dict:
    t0 = time.perf_counter()
    path = Path(path)
    template = template or load_template()
    if pages is None:
        pages = read_pdf(path, ocr=ocr)
    binder = Binder(pages, template)
    # the template's meaning applies only to documents that are recognisably of its type;
    # every other document is described by its template-free structure alone
    matched = binder.matched_sections()
    template_used = len(matched) >= MIN_TEMPLATE_SECTIONS
    rels = []
    if template_used:
        binder.run()
        rels = relate(binder, template.review_threshold)
    structure = extract_structure(binder)
    generic_rels, blanks, coverage = build_generic(binder, structure, template_used, len(rels) + 1)
    rels += generic_rels
    validation = validate(binder, rels, template, structure=structure, coverage=coverage,
                          template_used=template_used)
    packets = find_packets(pages, template) if template_used else [[p.number for p in pages]]
    if len(packets) > 1:  # several forms read as one: never let that pass silently
        spans = ", ".join(f"pages {g[0]}-{g[-1]}" for g in packets)
        validation["errors"].append({"target": "document", "check": "single_packet", "severity": "error",
                                     "message": f"this file holds {len(packets)} separate forms ({spans}); "
                                                f"they must be processed separately"})

    needs_ocr = [p for p in pages if p.image_only and not p.ocr_used]
    ocr_items = []
    for p in needs_ocr:
        reason = "scanned page has no text layer; run OCR to read it"
        if not ocr_available():
            reason += " (no OCR engine is installed: pip install pytesseract and install the tesseract program)"
        ocr_items.append({"page": p.number, "reason": reason})
    review = review_queue(binder, rels, validation, ocr_items)
    missing = binder.missing if not needs_ocr else [m for m in binder.missing if m["kind"] != "not_provided"]
    missing = missing + blanks

    ents = binder.entities
    if needs_ocr and len(needs_ocr) == len(pages):
        status = "needs_ocr"
    elif validation["errors"]:
        status = "needs_review"
    elif review:
        status = "needs_ocr" if needs_ocr else "needs_review"
    else:
        status = "completed"

    traced = sum(len(e.attributes) for e in ents.values())
    groups: dict[str, list[str]] = {}
    for e in ents.values():
        groups.setdefault(e.group, []).append(e.id)

    doc = {
        "schema_version": SCHEMA_VERSION,
        "document": {
            "doc_id": doc_id,
            "filename": filename or path.name,
            "document_type": template.document_type if template_used else "unknown",
            "title": _title(binder),
            "template": template.template_id if template_used else None,
            "template_applied": template_used,
            "template_sections_found": sorted(matched),
            "page_count": len(pages),
            "pages": [{"page": p.number, "width": round(p.width, 2), "height": round(p.height, 2),
                       "has_text": p.has_text, "form_fields": p.form_fields, "image_only": p.image_only,
                       "ocr_used": p.ocr_used, "deskew_angle": p.deskew_angle, "rotation": p.rotation,
                       "text_layer": p.text_layer, "ocr_regions": p.ocr_regions} for p in pages],
            "extraction_method": _extraction_method(pages),
            "sha256": sha256_file(path),
            "processed_at": processed_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "status": status,
            "ocr_available": ocr_available(),
            "ocr_engine": ocr_engine_name() if any(p.ocr_used for p in pages) else None,
            "processing_ms": None,
        },
        "summary": {
            "entities": len(ents),
            "traced_values": traced,
            "relationships": len(rels),
            "uncertain_relationships": sum(1 for r in rels if r.support == "uncertain"),
            "review_items": len(review),
            "missing_items": len(missing),
            "validation_errors": len(validation["errors"]),
            "fields_filled": 0,
            "fields_withheld": 0,
            "text_coverage": round(coverage["tokens_explained"] / coverage["tokens_total"], 4) if coverage["tokens_total"] else None,
        },
        "sections": [r.to_json() for r in binder.regions + structure.pseudo_regions],
        "coverage": coverage,
        "entity_groups": [{"group": g, "type": ents[ids[0]].type, "type_name": TYPE_LABELS.get(ents[ids[0]].type, ents[ids[0]].type),
                           "ids": ids} for g, ids in groups.items()],
        "entities": {eid: dict(e.to_json(), type_name=TYPE_LABELS.get(e.type, e.type)) for eid, e in ents.items()},
        "relationships": [r.to_json() for r in rels],
        "review_queue": review,
        "missing": missing,
        "validation": {"checks": validation["checks"], "errors": validation["errors"], "warnings": validation["warnings"],
                       "check_catalog": [{"check_id": c, "name": n, "description": d} for c, n, d in CHECKS]},
        "unbound_values": binder.unbound,
        "blocks": build_blocks(binder, structure),
        "standardized": None,
    }
    for e in doc["entities"].values():
        e.pop("_key", None)
    _unskew(doc, pages)
    if standardized_path and template_used:
        from .standardize import fill_standardized

        std = fill_standardized(doc, standardized_path)
        doc["standardized"] = std
        doc["summary"]["fields_filled"] = std["fields_filled"]
        doc["summary"]["fields_withheld"] = std["fields_withheld"]
    doc["document"]["processing_ms"] = int((time.perf_counter() - t0) * 1000)
    return doc
