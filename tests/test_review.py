"""Human review closes the loop: decisions update the result, the form and the audit log."""
import json

import pytest
from pypdf import PdfReader
from starlette.testclient import TestClient

from docintel.server import create_app


@pytest.fixture()
def client(tmp_path, samples_dir):
    seed = tmp_path / "seed"
    seed.mkdir()
    name = "intake_C_other_clinic_rivera.pdf"
    (seed / name).write_bytes((samples_dir / name).read_bytes())
    app = create_app(tmp_path / "data", seed=seed)
    with TestClient(app) as c:
        c.root = tmp_path / "data"
        yield c


def _item(doc, kind, target_prefix):
    return next(r for r in doc["review_queue"] if r["kind"] == kind and r["target"].startswith(target_prefix)
                and not r.get("resolution"))


def _form(client):
    data = client.get("/api/documents/DOC_001/standardized.pdf").content
    out = {}
    import io
    for page in PdfReader(io.BytesIO(data)).pages:
        for ref in page.get("/Annots") or []:
            a = ref.get_object()
            if a.get("/FT") == "/Btn":
                out[str(a["/T"])] = str(a.get("/AS", "/Off")) != "/Off"
            elif a.get("/FT") == "/Tx":
                out[str(a["/T"])] = str(a.get("/V", ""))
    return out


def test_confirm_and_correct_values_refill_the_form(client):
    doc = client.get("/api/documents/DOC_001").json()
    assert _form(client)["med4_freq"] == "" and doc["summary"]["fields_withheld"] == 2
    freq = _item(doc, "attribute", "MED_004.frequency")
    r = client.post(f"/api/documents/DOC_001/review/{freq['review_id']}", json={"action": "confirm"}).json()
    assert r["summary"]["review_items"] == 6
    decision = _item(doc, "attribute", "CONS_002.decision")
    bad = client.post(f"/api/documents/DOC_001/review/{decision['review_id']}", json={"action": "correct", "value": "maybe"})
    assert bad.status_code == 400
    client.post(f"/api/documents/DOC_001/review/{decision['review_id']}", json={"action": "correct", "value": "no"})
    doc = client.get("/api/documents/DOC_001").json()
    attr = doc["entities"]["CONS_002"]["attributes"]["decision"]
    assert attr["value"] == "no" and attr["status"] == "valid" and attr["reviewed"]["from"] is None
    form = _form(client)
    assert form["med4_freq"] == "Daily (with breakfast)"
    assert form["cc_text_no"] is True and form["cc_text_yes"] is False
    assert doc["summary"]["fields_withheld"] == 0
    assert [e["action"] for e in doc["review_log"]] == ["confirm", "correct"]


def test_reject_link_and_finish_review(client):
    doc = client.get("/api/documents/DOC_001").json()
    assert client.post("/api/documents/DOC_001/ground-truth").status_code == 409  # items still open
    signs = next(r for r in doc["review_queue"] if r["kind"] == "relationship" and r["predicate"] == "SIGNS")
    assert client.post(f"/api/documents/DOC_001/review/{signs['review_id']}", json={"action": "approve"}).status_code == 400
    client.post(f"/api/documents/DOC_001/review/{signs['review_id']}", json={"action": "reject"})
    doc = client.get("/api/documents/DOC_001").json()
    assert not any(r["relationship_id"] == signs["target"] for r in doc["relationships"])
    assert doc["rejected_relationships"][0]["relationship_id"] == signs["target"]
    for item in doc["review_queue"]:
        if item.get("resolution"):
            continue
        action = {"attribute": "confirm", "relationship": "confirm", "validation": "confirm"}[item["kind"]]
        assert client.post(f"/api/documents/DOC_001/review/{item['review_id']}", json={"action": action}).status_code == 200
    doc = client.get("/api/documents/DOC_001").json()
    assert doc["document"]["status"] == "completed" and doc["document"]["reviewed"] is True
    assert doc["summary"]["review_items"] == 0 and doc["summary"]["uncertain_relationships"] == 0
    assert client.get("/api/documents").json()["documents"][0]["status"] == "completed"
    again = client.post(f"/api/documents/DOC_001/review/{signs['review_id']}", json={"action": "confirm"})
    assert again.status_code == 400  # already resolved
    r = client.post("/api/documents/DOC_001/ground-truth").json()
    truth = json.loads((client.root / "ground_truth" / r["file"]).read_text())
    assert truth["values"]["Consent[text message].decision"] is None or "Consent[text message].decision" in truth["values"]
    assert not any(rel[1] == "SIGNS" and "Financial" in rel[2] for rel in truth["relationships"])
