"""Web API."""
import pytest
from starlette.testclient import TestClient

from docintel.server import create_app


@pytest.fixture()
def client(tmp_path, samples_dir):
    seed = tmp_path / "seed"
    seed.mkdir()
    for name in ("intake_A_fillable_okafor.pdf", "intake_C_other_clinic_rivera.pdf"):
        (seed / name).write_bytes((samples_dir / name).read_bytes())
    app = create_app(tmp_path / "data", seed=seed)
    with TestClient(app) as c:
        yield c


def test_index_and_listing(client):
    assert "docintel" in client.get("/").text
    docs = client.get("/api/documents").json()["documents"]
    assert [d["doc_id"] for d in docs] == ["DOC_001", "DOC_002"]
    assert [d["status"] for d in docs] == ["completed", "needs_review"]


def test_document_pages_and_downloads(client):
    doc = client.get("/api/documents/DOC_002").json()
    assert doc["document"]["filename"] == "intake_C_other_clinic_rivera.pdf"
    png = client.get("/api/documents/DOC_002/pages/source/1.png")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    assert client.get("/api/documents/DOC_002/pages/standardized/3.png").status_code == 200
    assert client.get("/api/documents/DOC_002/pages/source/9.png").status_code == 404
    assert client.get("/api/documents/DOC_002/source.pdf").content.startswith(b"%PDF")
    assert client.get("/api/documents/DOC_002/standardized.pdf").content.startswith(b"%PDF")
    j = client.get("/api/documents/DOC_002/download.json")
    assert j.json()["document"]["doc_id"] == "DOC_002"
    assert client.get("/api/documents/DOC_404").status_code == 404


def test_upload_ask_delete(client, samples_dir):
    data = (samples_dir / "intake_B_flattened_lindqvist.pdf").read_bytes()
    r = client.post("/api/documents", files=[("files", ("lindqvist.pdf", data, "application/pdf"))])
    res = r.json()["documents"][0]
    assert res["doc_id"] == "DOC_003" and res["status"] == "needs_review"
    bad = client.post("/api/documents", files=[("files", ("x.pdf", b"hello", "application/pdf"))]).json()
    assert bad["documents"][0]["error"] == "not a PDF or image file"

    a = client.get("/api/documents/DOC_002/ask", params={"q": "find", "a": "hypertension"}).json()
    assert {x["owner"] for x in a["answer"]} == {"Maria Rivera", "Mother"}
    rel = client.get("/api/documents/DOC_002/ask", params={"q": "related", "a": "DR_002 PAT_001"}).json()
    assert rel["answer"]["related"]
    err = client.get("/api/documents/DOC_002/ask", params={"q": "owner", "a": "NOPE_001"})
    assert err.status_code == 400

    queue = client.get("/api/review-queue").json()
    assert queue["count"] == 8  # 7 for the Riverside packet + 1 for the flattened one

    assert client.delete("/api/documents/DOC_003").status_code == 200
    assert [d["doc_id"] for d in client.get("/api/documents").json()["documents"]] == ["DOC_001", "DOC_002"]
    # IDs are never reused: the next upload continues the sequence
    r = client.post("/api/documents", files=[("files", ("again.pdf", data, "application/pdf"))])
    assert r.json()["documents"][0]["doc_id"] == "DOC_004"
