"""``scan-template``: map the fields of a fillable reference form onto the template.

The reference form is read exactly like an intake document, except that empty
form fields become placeholders.  Each placeholder is then located the same way
a value would be - section heading, printed label, table column and row, or
check-box option - which gives it a canonical path such as
``patient_information.date_of_birth`` or ``current_medications[3].dosage``.
"""
from __future__ import annotations

import json
from pathlib import Path

from .bind import bind
from .read import read_pdf
from .template import Template, load_template


def scan_template(pdf_path: str | Path, template: Template | None = None) -> dict:
    template = template or load_template()
    pdf_path = Path(pdf_path)
    pages = read_pdf(pdf_path, placeholders=True)
    binder = bind(pages, template, scan=True)
    widgets = {}
    for p in pages:
        for t in p.tokens:
            if t.field_name:
                widgets.setdefault(t.field_name, {"page": t.page, "rect": t.bbox,
                                                  "kind": "checkbox" if t.kind == "checkbox" else "text"})
    fields = {}
    for s in binder.slots:
        fields.setdefault(s["field"], {k: s[k] for k in ("path", "label", "section", "page", "rect", "kind")})
    unmapped = sorted(set(widgets) - set(fields))
    return {
        "template": template.template_id,
        "form": pdf_path.name,
        "page_count": len(pages),
        "page_sizes": [[p.width, p.height] for p in pages],
        "sections": [r.to_json() for r in binder.regions],
        "fields": dict(sorted(fields.items(), key=lambda kv: (kv[1]["page"], kv[1]["rect"][1], kv[1]["rect"][0]))),
        "unmapped": [{"field": f, **widgets[f]} for f in unmapped],
    }


def write_field_map(pdf_path: str | Path, out_path: str | Path | None = None, template: Template | None = None) -> tuple[Path, dict]:
    result = scan_template(pdf_path, template)
    out_path = Path(out_path) if out_path else Path(pdf_path).with_suffix(".fieldmap.json")
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return out_path, result
