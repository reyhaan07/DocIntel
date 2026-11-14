"""Page rendering (pdfium).  pdfium is not thread-safe, so every call goes through one lock."""
from __future__ import annotations

import threading
from pathlib import Path

PDFIUM_LOCK = threading.RLock()


def render_page_png(pdf_path: str | Path, page_number: int, out_path: str | Path, scale: float = 2.0) -> Path:
    import pypdfium2 as pdfium

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(str(pdf_path))
        try:
            if page_number < 1 or page_number > len(doc):
                raise IndexError(f"page {page_number} out of range")
            try:
                doc.init_forms()  # must happen before any page is loaded
            except Exception:  # pragma: no cover - unsupported build
                pass
            page = doc[page_number - 1]
            img = page.render(scale=scale, may_draw_forms=True).to_pil()
        finally:
            doc.close()
    img.save(out_path, format="PNG", optimize=True)
    return out_path


def render_page_gray(pdf_path: str | Path, page_number: int, scale: float = 3.0):
    """Grayscale PIL image of a page *without* form widgets (used for visual checkbox detection)."""
    import pypdfium2 as pdfium

    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(str(pdf_path))
        try:
            img = doc[page_number - 1].render(scale=scale, draw_annots=False).to_pil().convert("L")
        finally:
            doc.close()
    return img


def page_sizes(pdf_path: str | Path) -> list[tuple[float, float]]:
    import pypdfium2 as pdfium

    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(str(pdf_path))
        try:
            return [tuple(doc[i].get_size()) for i in range(len(doc))]
        finally:
            doc.close()
