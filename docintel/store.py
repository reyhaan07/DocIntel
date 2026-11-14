"""Document store for the web app and batch output.

Layout of a store directory::

    index.json              batch index: one row per document
    review_queue.json       every review item of every document
    documents/DOC_001/
        source.pdf          the uploaded file, unchanged
        DOC_001.json        the structured, traced output
        standardized.pdf    the filled reference form
        pages/              rendered page images (cache)
"""
from __future__ import annotations

import json
import re
import shutil
import threading
from pathlib import Path

from .pipeline import process_pdf

_ID = re.compile(r"^DOC_(\d{3,})$")


def index_row(doc: dict) -> dict:
    d, s = doc["document"], doc["summary"]
    return {
        "doc_id": d["doc_id"], "filename": d["filename"], "status": d["status"], "processed_at": d["processed_at"],
        "page_count": d["page_count"], "extraction_method": d["extraction_method"], "sha256": d["sha256"],
        "entities": s["entities"], "relationships": s["relationships"],
        "uncertain_relationships": s["uncertain_relationships"], "review_items": s["review_items"],
        "missing_items": s["missing_items"], "validation_errors": s["validation_errors"],
    }


def queue_rows(doc: dict) -> list[dict]:
    d = doc["document"]
    return [dict(item, doc_id=d["doc_id"], filename=d["filename"]) for item in doc["review_queue"]]


def write_batch_files(out_dir: Path, docs: list[dict]) -> None:
    rows = [index_row(d) for d in docs]
    totals = {k: sum(r[k] for r in rows) for k in ("entities", "relationships", "review_items", "missing_items")}
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    (out_dir / "index.json").write_text(json.dumps({"documents": rows, "totals": totals, "by_status": by_status},
                                                   indent=2), encoding="utf-8")
    queue = [q for d in docs for q in queue_rows(d)]
    (out_dir / "review_queue.json").write_text(json.dumps({"items": queue, "count": len(queue)}, indent=2),
                                               encoding="utf-8")


class Store:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.docs_dir = self.root / "documents"
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    # ------------------------------------------------------------------ paths
    def doc_dir(self, doc_id: str) -> Path:
        if not _ID.match(doc_id):
            raise KeyError(doc_id)
        return self.docs_dir / doc_id

    def json_path(self, doc_id: str) -> Path:
        return self.doc_dir(doc_id) / f"{doc_id}.json"

    def source_path(self, doc_id: str) -> Path:
        return self.doc_dir(doc_id) / "source.pdf"

    def standardized_path(self, doc_id: str) -> Path:
        return self.doc_dir(doc_id) / "standardized.pdf"

    # ------------------------------------------------------------------ queries
    def ids(self) -> list[str]:
        return sorted((p.name for p in self.docs_dir.iterdir() if _ID.match(p.name) and (p / f"{p.name}.json").exists()),
                      key=lambda s: int(s[4:]))

    def get(self, doc_id: str) -> dict:
        path = self.json_path(doc_id)
        if not path.exists():
            raise KeyError(doc_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        return [index_row(self.get(i)) for i in self.ids()]

    def next_id(self) -> str:
        """IDs are never reused, even after the newest document is deleted."""
        counter = self.root / "last_id.txt"
        nums = [int(p.name[4:]) for p in self.docs_dir.iterdir() if _ID.match(p.name)]
        last = int(counter.read_text() or 0) if counter.exists() else 0
        n = max([last, *nums]) + 1
        counter.write_text(str(n))
        return f"DOC_{n:03d}"

    # ------------------------------------------------------------------ mutations
    def add(self, data: bytes, filename: str, *, ocr: bool = False) -> dict:
        with self.lock:
            doc_id = self.next_id()
            ddir = self.doc_dir(doc_id)
            ddir.mkdir(parents=True)
            self.source_path(doc_id).write_bytes(data)
        try:
            return self._process(doc_id, filename, ocr=ocr)
        except Exception as exc:  # keep a record of the failure instead of losing the upload
            doc = {"schema_version": "1.0", "document": {
                "doc_id": doc_id, "filename": filename, "status": "failed", "error": str(exc), "page_count": 0,
                "pages": [], "extraction_method": "none", "sha256": "", "processed_at": "", "document_type": "",
                "template": "patient_intake_v1"},
                "summary": {k: 0 for k in ("entities", "traced_values", "relationships", "uncertain_relationships",
                                           "review_items", "missing_items", "validation_errors", "fields_filled",
                                           "fields_withheld")},
                "sections": [], "entity_groups": [], "entities": {}, "relationships": [], "review_queue": [],
                "missing": [], "validation": {"checks": [], "errors": [], "warnings": [], "check_catalog": []},
                "unbound_values": [], "standardized": None}
            self.json_path(doc_id).write_text(json.dumps(doc, indent=2), encoding="utf-8")
            self.write_index()
            return doc

    def _process(self, doc_id: str, filename: str, *, ocr: bool = False) -> dict:
        with self.lock:
            ddir = self.doc_dir(doc_id)
            shutil.rmtree(ddir / "pages", ignore_errors=True)
            doc = process_pdf(self.source_path(doc_id), doc_id, filename=filename, ocr=ocr,
                              standardized_path=self.standardized_path(doc_id))
            self.json_path(doc_id).write_text(json.dumps(doc, indent=2), encoding="utf-8")
            self.write_index()
            return doc

    def reprocess(self, doc_id: str, *, ocr: bool = False) -> dict:
        doc = self.get(doc_id)
        return self._process(doc_id, doc["document"]["filename"], ocr=ocr)

    def delete(self, doc_id: str) -> None:
        with self.lock:
            ddir = self.doc_dir(doc_id)
            if not ddir.exists():
                raise KeyError(doc_id)
            shutil.rmtree(ddir)
            self.write_index()

    def write_index(self) -> None:
        with self.lock:
            write_batch_files(self.root, [self.get(i) for i in self.ids()])

    # ------------------------------------------------------------------ pages
    def page_image(self, doc_id: str, kind: str, page: int, scale: float = 2.0) -> Path:
        from .render import render_page_png

        if kind not in ("source", "standardized"):
            raise KeyError(kind)
        pdf = self.source_path(doc_id) if kind == "source" else self.standardized_path(doc_id)
        if not pdf.exists():
            raise KeyError(kind)
        out = self.doc_dir(doc_id) / "pages" / f"{kind}-{page}.png"
        if not out.exists():
            render_page_png(pdf, page, out, scale=scale)
        return out

    def page_image_bytes(self, doc_id: str, kind: str, page: int) -> bytes:
        # read under the lock: re-processing clears the cache and must not race a response
        with self.lock:
            return self.page_image(doc_id, kind, page).read_bytes()

    def seed(self, folder: str | Path) -> list[dict]:
        out = []
        for pdf in sorted(Path(folder).glob("*.pdf")):
            out.append(self.add(pdf.read_bytes(), pdf.name))
        return out
