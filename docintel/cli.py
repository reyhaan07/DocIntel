"""Command line interface.

    python -m docintel serve                               web app at http://localhost:8000
    python -m docintel process samples/input -o output     one JSON + standardized PDF per file
    python -m docintel ask output/DOC_003.json owner COND_006
    python -m docintel scan-template reference.pdf         map a reference form's fields
    python -m docintel evaluate samples/input              accuracy against ground truth (silent errors)
    python -m docintel truth output/DOC_003.json -o t.json export a checked result as ground truth
    python -m docintel samples                             regenerate the sample PDFs
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _ocr_mode(args):
    if getattr(args, "no_ocr", False):
        return False
    if getattr(args, "ocr", False):
        return True
    return "auto"


def _ocr_banner() -> None:
    from .ocr import engine_name

    name = engine_name()
    print(f"OCR for scanned pages: {name} (local)" if name else
          "OCR for scanned pages: not available - pip install pytesseract and install the tesseract program")


def _cmd_serve(args) -> int:
    import uvicorn

    from .server import create_app

    if not args.no_ocr:
        _ocr_banner()
    app = create_app(args.data, seed=None if args.no_seed else args.seed, ocr=_ocr_mode(args), verbose=True)
    print(f"docintel web app at http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _cmd_process(args) -> int:
    from .pipeline import process_pdf
    from .store import write_batch_files

    src = Path(args.input)
    files = sorted(src.glob("*.pdf")) if src.is_dir() else [src]
    if not files:
        print(f"no PDF files found in {src}", file=sys.stderr)
        return 1
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    if not args.no_ocr:
        _ocr_banner()
    docs = []
    print(f"{'doc':8} {'status':13} {'entities':>8} {'rels':>5} {'review':>6} {'missing':>7}  file")
    for i, f in enumerate(files, start=1):
        doc_id = f"DOC_{i:03d}"
        doc = process_pdf(f, doc_id, ocr=_ocr_mode(args), standardized_path=out / f"{doc_id}_standardized.pdf")
        (out / f"{doc_id}.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
        docs.append(doc)
        s = doc["summary"]
        print(f"{doc_id:8} {doc['document']['status']:13} {s['entities']:>8} {s['relationships']:>5} "
              f"{s['review_items']:>6} {s['missing_items']:>7}  {f.name}")
    write_batch_files(out, docs)
    print(f"\nwrote {len(docs)} JSON files, {len(docs)} standardized PDFs, index.json and review_queue.json to {out}/")
    return 0


def _cmd_ask(args) -> int:
    from .ask import AskError, ask

    doc = json.loads(Path(args.doc).read_text(encoding="utf-8"))
    try:
        answer = ask(doc, args.question, *args.args)
    except AskError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(answer, indent=2, ensure_ascii=False))
    return 0


def _cmd_scan(args) -> int:
    from .scan import write_field_map

    path, result = write_field_map(args.reference, args.output)
    by_section: dict[str, int] = {}
    for f in result["fields"].values():
        by_section[f["section"]] = by_section.get(f["section"], 0) + 1
    print(f"{result['form']}: {len(result['fields'])} fields mapped, {len(result['unmapped'])} unmapped")
    for sec, n in by_section.items():
        print(f"  {sec:28} {n:3} fields")
    for u in result["unmapped"]:
        print(f"  unmapped: {u['field']} (page {u['page']})")
    print(f"field map written to {path}")
    return 0


def _cmd_evaluate(args) -> int:
    from .evaluate import evaluate_folder

    rep = evaluate_folder(args.input, args.truth, ocr=_ocr_mode(args))
    if not rep["documents"]:
        print(f"no PDF in {args.input} has a ground-truth file in {args.truth}", file=sys.stderr)
        return 1
    print(f"{'document':40} {'values':>7} {'accuracy':>9} {'links':>7} {'silent':>7} {'flagged':>8}")
    for d in rep["documents"]:
        c = d["counts"]
        print(f"{d['document'][:40]:40} {c.get('values', 0):>7} {d['value_accuracy']:>9.2%} "
              f"{d['relationship_recall']:>7.0%} {d['silent_errors']:>7} {d['flagged_errors']:>8}")
        if args.verbose:
            for kind, items in d["details"].items():
                for x in items:
                    print(f"    {kind:10} {json.dumps(x, ensure_ascii=False)}")
    print(f"{'TOTAL':40} {rep['values']:>7} {rep['value_accuracy']:>9.2%} {rep['relationship_recall']:>7.0%} "
          f"{rep['silent_errors']:>7} {rep['flagged_errors']:>8}")
    print("\nsilent = wrong, invented or missed and NOT flagged for review;  flagged = caught by review")
    if args.json:
        Path(args.json).write_text(json.dumps(rep, indent=2), encoding="utf-8")
    return 1 if (args.strict and rep["silent_errors"]) else 0


def _cmd_truth(args) -> int:
    from .evaluate import to_truth

    doc = json.loads(Path(args.doc).read_text(encoding="utf-8"))
    truth = to_truth(doc)
    out = Path(args.output) if args.output else Path(Path(doc["document"]["filename"]).stem + ".json")
    out.write_text(json.dumps(truth, indent=1), encoding="utf-8")
    print(f"ground truth with {len(truth['values'])} values and {len(truth['relationships'])} relationships "
          f"written to {out} - check every line before using it")
    return 0


def _cmd_samples(args) -> int:
    from .samples import generate_all

    for f in generate_all(Path(args.out) / "input", Path(args.out) / "upload", reference=not args.no_reference):
        print(f)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="docintel", description="Relationship-aware intake extraction")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the web app")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--data", default="docintel_data", help="store directory (default: ./docintel_data)")
    s.add_argument("--seed", default="samples/input", help="folder processed on first start when the store is empty")
    s.add_argument("--no-seed", action="store_true", help="start with an empty store")
    s.add_argument("--no-ocr", action="store_true", help="do not OCR scanned pages (they are marked 'Needs OCR')")
    s.set_defaults(func=_cmd_serve)

    s = sub.add_parser("process", help="process a PDF or a folder of PDFs")
    s.add_argument("input")
    s.add_argument("-o", "--output", default="output")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--ocr", action="store_true", help="require OCR for scanned pages (fail if no engine is installed)")
    g.add_argument("--no-ocr", action="store_true", help="never OCR; scanned pages are marked 'Needs OCR'")
    s.set_defaults(func=_cmd_process)

    s = sub.add_parser("ask", help="ask a relationship question about a processed document")
    s.add_argument("doc", help="DOC_xxx.json")
    s.add_argument("question", help="find | entity | owner | section | related | evidence")
    s.add_argument("args", nargs="*")
    s.set_defaults(func=_cmd_ask)

    s = sub.add_parser("scan-template", help="map the fields of a fillable reference form")
    s.add_argument("reference")
    s.add_argument("-o", "--output", default=None)
    s.set_defaults(func=_cmd_scan)

    s = sub.add_parser("evaluate", help="measure accuracy against ground-truth files")
    s.add_argument("input", help="folder of PDFs")
    s.add_argument("--truth", default="samples/ground_truth", help="folder of <pdf name>.json ground-truth files")
    s.add_argument("--no-ocr", action="store_true")
    s.add_argument("--strict", action="store_true", help="exit with status 1 if there is any silent error")
    s.add_argument("--json", help="also write the full report to this file")
    s.add_argument("-v", "--verbose", action="store_true", help="list every error")
    s.set_defaults(func=_cmd_evaluate)

    s = sub.add_parser("truth", help="export a checked document as a ground-truth file")
    s.add_argument("doc", help="DOC_xxx.json (after review)")
    s.add_argument("-o", "--output")
    s.set_defaults(func=_cmd_truth)

    s = sub.add_parser("samples", help="regenerate the sample PDFs")
    s.add_argument("--out", default="samples")
    s.add_argument("--no-reference", action="store_true", help="do not rewrite the bundled reference form")
    s.set_defaults(func=_cmd_samples)

    args = p.parse_args(argv)
    return args.func(args)
