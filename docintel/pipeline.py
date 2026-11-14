"""Runs the five stages on one PDF and assembles the per-document JSON."""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

from .bind import TYPE_NAMES, bind
from .ocr import engine_name as ocr_engine_name
from .ocr import unskew_bbox
from .read import ocr_available, read_pdf
from .relate import relate
from .template import Template, load_template
from .validate import CHECKS, review_queue, validate

SCHEMA_VERSION = "1.0"


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
        fix(sec)
    for e in doc["entities"].values():
        fix(e, ("row_bbox",))
        for a in e["attributes"].values():
            fix(a)
    for r in doc["relationships"]:
        for ev in r["evidence"]:
            fix(ev)
    for item in doc["missing"] + doc["review_queue"]:
        fix(item)


def process_pdf(path: str | Path, doc_id: str = "DOC_001", *, filename: str | None = None,
                template: Template | None = None, ocr: bool | str = "auto", standardized_path: str | Path | None = None,
                processed_at: str | None = None) -> dict:
    t0 = time.perf_counter()
    path = Path(path)
    template = template or load_template()
    pages = read_pdf(path, ocr=ocr)
    binder = bind(pages, template)
    rels = relate(binder, template.review_threshold)
    validation = validate(binder, rels, template)

    needs_ocr = [p for p in pages if p.image_only and not p.ocr_used]
    ocr_items = []
    for p in needs_ocr:
        reason = "scanned page has no text layer; run OCR to read it"
        if not ocr_available():
            reason += " (no OCR engine is installed: pip install pytesseract and install the tesseract program)"
        ocr_items.append({"page": p.number, "reason": reason})
    review = review_queue(binder, rels, validation, ocr_items)
    missing = binder.missing if not needs_ocr else [m for m in binder.missing if m["kind"] != "not_provided"]

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
            "document_type": template.document_type,
            "template": template.template_id,
            "page_count": len(pages),
            "pages": [{"page": p.number, "width": round(p.width, 2), "height": round(p.height, 2),
                       "has_text": p.has_text, "form_fields": p.form_fields, "image_only": p.image_only,
                       "ocr_used": p.ocr_used, "deskew_angle": p.deskew_angle} for p in pages],
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
        },
        "sections": [r.to_json() for r in binder.regions],
        "entity_groups": [{"group": g, "type": ents[ids[0]].type, "type_name": TYPE_NAMES.get(ents[ids[0]].type, ents[ids[0]].type),
                           "ids": ids} for g, ids in groups.items()],
        "entities": {eid: dict(e.to_json(), type_name=TYPE_NAMES.get(e.type, e.type)) for eid, e in ents.items()},
        "relationships": [r.to_json() for r in rels],
        "review_queue": review,
        "missing": missing,
        "validation": {"checks": validation["checks"], "errors": validation["errors"], "warnings": validation["warnings"],
                       "check_catalog": [{"check_id": c, "name": n, "description": d} for c, n, d in CHECKS]},
        "unbound_values": binder.unbound,
        "standardized": None,
    }
    for e in doc["entities"].values():
        e.pop("_key", None)
    _unskew(doc, pages)
    if standardized_path:
        from .standardize import fill_standardized

        std = fill_standardized(doc, standardized_path)
        doc["standardized"] = std
        doc["summary"]["fields_filled"] = std["fields_filled"]
        doc["summary"]["fields_withheld"] = std["fields_withheld"]
    doc["document"]["processing_ms"] = int((time.perf_counter() - t0) * 1000)
    return doc
