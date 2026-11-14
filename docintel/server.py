"""Web app: a small JSON API plus a single-page UI (``static/``)."""
from __future__ import annotations

import json
from pathlib import Path

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .ask import QUESTIONS, AskError, ask, suggestions
from .read import ocr_available
from .store import Store

STATIC = Path(__file__).parent / "static"


def _supported(data: bytes, name: str = "") -> bool:
    """PDF, an image Pillow can open, or an office/web/e-mail/text file by its extension."""
    if data.lstrip()[:5].startswith(b"%PDF"):
        return True
    from .convert import can_convert

    if name and can_convert(name):
        return True
    import io

    from PIL import Image

    try:
        Image.open(io.BytesIO(data)).verify()
        return True
    except Exception:
        return False
MAX_UPLOAD = 25 * 1024 * 1024


def create_app(data_dir: str | Path = "docintel_data", seed: str | Path | None = None, ocr: bool | str = "auto",
               verbose: bool = False) -> Starlette:
    """``ocr``: "auto" reads scanned pages when an OCR engine is installed, False never does."""
    store = Store(data_dir, ocr=ocr)
    if seed and not store.ids() and Path(seed).is_dir():
        store.seed(seed, progress=print if verbose else None)

    def _doc(doc_id: str) -> dict:
        try:
            return store.get(doc_id)
        except KeyError:
            raise HTTPException(404, f"unknown document {doc_id}")

    def index(request: Request):
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    def list_documents(request: Request):
        return JSONResponse({"documents": store.list(), "ocr_available": ocr_available(), "questions": QUESTIONS})

    async def upload(request: Request):
        form = await request.form()
        files = form.getlist("files") or form.getlist("file")
        if not files:
            raise HTTPException(400, "no files in the upload")
        use_ocr = True if request.query_params.get("ocr") == "1" else ocr
        results = []
        for f in files:
            name = Path(getattr(f, "filename", "") or "upload.pdf").name
            data = await f.read()
            if len(data) > MAX_UPLOAD:
                results.append({"filename": name, "error": "file is larger than 25 MB"})
                continue
            if not _supported(data, name):
                results.append({"filename": name, "error": "not a supported file (PDF, image, Word, Excel, "
                                                           "PowerPoint, OpenDocument, HTML, e-mail, text, CSV, JSON, RTF)"})
                continue
            from starlette.concurrency import run_in_threadpool

            docs = await run_in_threadpool(store.add, data, name, ocr=use_ocr)
            for doc in docs:
                d = doc["document"]
                results.append({"doc_id": d["doc_id"], "filename": d["filename"], "status": d["status"],
                                "error": d.get("error"), "summary": doc["summary"],
                                "packet": d.get("packet")})
        return JSONResponse({"documents": results})

    def get_document(request: Request):
        return JSONResponse(_doc(request.path_params["doc_id"]))

    def delete_document(request: Request):
        try:
            store.delete(request.path_params["doc_id"])
        except KeyError:
            raise HTTPException(404, "unknown document")
        return JSONResponse({"deleted": request.path_params["doc_id"]})

    def reprocess(request: Request):
        doc_id = request.path_params["doc_id"]
        _doc(doc_id)
        use_ocr = True if request.query_params.get("ocr") == "1" else None
        if use_ocr and not ocr_available():
            raise HTTPException(400, "no OCR engine is installed (pip install pytesseract; install tesseract)")
        doc = store.reprocess(doc_id, ocr=use_ocr)
        return JSONResponse({"doc_id": doc_id, "status": doc["document"]["status"], "summary": doc["summary"]})

    def download_json(request: Request):
        doc_id = request.path_params["doc_id"]
        _doc(doc_id)
        return FileResponse(store.json_path(doc_id), media_type="application/json", filename=f"{doc_id}.json")

    def download_md(request: Request):
        from .generic import blocks_to_markdown

        doc = _doc(request.path_params["doc_id"])
        name = f"{doc['document']['doc_id']}.md"
        return Response(blocks_to_markdown(doc), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    def source_pdf(request: Request):
        doc = _doc(request.path_params["doc_id"])
        return FileResponse(store.source_path(doc["document"]["doc_id"]), media_type="application/pdf",
                            headers={"Content-Disposition": f'inline; filename="{doc["document"]["filename"]}"'})

    def standardized_pdf(request: Request):
        doc_id = request.path_params["doc_id"]
        _doc(doc_id)
        path = store.standardized_path(doc_id)
        if not path.exists():
            raise HTTPException(404, "no standardized form for this document")
        return FileResponse(path, media_type="application/pdf",
                            headers={"Content-Disposition": f'inline; filename="{doc_id}_standardized.pdf"'})

    def page_png(request: Request):
        doc_id = request.path_params["doc_id"]
        _doc(doc_id)
        try:
            data = store.page_image_bytes(doc_id, request.path_params["kind"], int(request.path_params["page"]))
        except (KeyError, IndexError, ValueError):
            raise HTTPException(404, "no such page")
        return Response(data, media_type="image/png", headers={"Cache-Control": "max-age=3600"})

    def ask_endpoint(request: Request):
        doc = _doc(request.path_params["doc_id"])
        q = request.query_params.get("q", "find")
        arg = request.query_params.get("a", "")
        try:
            args = [arg] if q in ("find", "entity", "owner", "section", "evidence") else arg.replace(",", " ").split()
            answer = ask(doc, q, *args)
        except AskError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"question": q, "argument": arg, "answer": answer})

    def ask_suggestions(request: Request):
        return JSONResponse({"suggestions": suggestions(_doc(request.path_params["doc_id"]))})

    async def review_action(request: Request):
        from starlette.concurrency import run_in_threadpool

        from .review import ReviewError

        doc_id, rev_id = request.path_params["doc_id"], request.path_params["review_id"]
        _doc(doc_id)
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            res = await run_in_threadpool(store.apply_review, doc_id, rev_id, body.get("action", ""),
                                          body.get("value"), body.get("note"))
        except ReviewError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        d = res["document"]
        return JSONResponse({"entry": res["entry"], "status": d["document"]["status"], "summary": d["summary"]})

    def save_truth(request: Request):
        doc_id = request.path_params["doc_id"]
        _doc(doc_id)
        try:
            path = store.save_ground_truth(doc_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        return JSONResponse({"path": str(path), "file": path.name})

    def review_queue(request: Request):
        path = store.root / "review_queue.json"
        data = json.loads(path.read_text()) if path.exists() else {"items": [], "count": 0}
        return JSONResponse(data)

    async def http_error(request: Request, exc: HTTPException):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
        return Response(str(exc.detail), status_code=exc.status_code)

    routes = [
        Route("/", index),
        Route("/api/documents", list_documents, methods=["GET"]),
        Route("/api/documents", upload, methods=["POST"]),
        Route("/api/review-queue", review_queue),
        Route("/api/documents/{doc_id}", get_document, methods=["GET"]),
        Route("/api/documents/{doc_id}", delete_document, methods=["DELETE"]),
        Route("/api/documents/{doc_id}/reprocess", reprocess, methods=["POST"]),
        Route("/api/documents/{doc_id}/download.json", download_json),
        Route("/api/documents/{doc_id}/download.md", download_md),
        Route("/api/documents/{doc_id}/source.pdf", source_pdf),
        Route("/api/documents/{doc_id}/standardized.pdf", standardized_pdf),
        Route("/api/documents/{doc_id}/pages/{kind}/{page:int}.png", page_png),
        Route("/api/documents/{doc_id}/ask", ask_endpoint),
        Route("/api/documents/{doc_id}/review/{review_id}", review_action, methods=["POST"]),
        Route("/api/documents/{doc_id}/ground-truth", save_truth, methods=["POST"]),
        Route("/api/documents/{doc_id}/suggestions", ask_suggestions),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ]
    app = Starlette(routes=routes, exception_handlers={HTTPException: http_error})
    app.state.store = store
    return app
