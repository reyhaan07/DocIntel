"""Standardized form, template scan, ask, normalisation and CLI."""
import json

import pytest
from pypdf import PdfReader

from docintel.ask import AskError, ask
from docintel.cli import main
from docintel.normalize import format_phone, parse_date, same_person, split_person_name
from docintel.samples import reference_form_path
from docintel.scan import scan_template


def _form_values(path):
    out = {}
    for page in PdfReader(str(path)).pages:
        for ref in page.get("/Annots") or []:
            a = ref.get_object()
            if a.get("/FT") == "/Btn":
                out[str(a["/T"])] = str(a.get("/AS", "/Off")) != "/Off"
            elif a.get("/FT") == "/Tx":
                out[str(a["/T"])] = str(a.get("/V", ""))
    return out


def test_standardized_form_is_filled_by_structure(processed):
    path = processed["_out"] / "DOC_003_standardized.pdf"
    v = _form_values(path)
    assert v["pt_first_name"] == "Maria" and v["pt_last_name"] == "Rivera"
    assert v["pt_dob"] == "07/14/1985"
    assert v["med3_name"] == "Sertraline" and v["med3_dose"] == "50 mg" and v["med3_doctor"] == "Dr. Priya Nair"
    assert v["ins2_member_id"] == "LKM-88120" and v["ins2_holder"] == "Daniel Rivera"
    assert v["fam_mother_conditions"] == "Type 2 diabetes, hypertension"
    assert v["hx_diabetes"] is True and v["hx_cancer"] is False
    assert v["hx_other"] == "Migraines"
    # still awaiting review -> never printed
    assert v["med4_freq"] == ""
    assert v["cc_text_yes"] is False and v["cc_text_no"] is False
    assert v["cc_email_no"] is True
    std = processed["C"]["standardized"]
    assert {w["ref"] for w in std["withheld"]} == {"MED_004.frequency", "CONS_002.decision"}


def test_scan_template_maps_every_field():
    result = scan_template(reference_form_path())
    assert not result["unmapped"]
    f = result["fields"]
    assert f["pt_dob"]["path"] == "patient_information.date_of_birth"
    assert f["med3_dose"]["path"] == "current_medications[3].dosage"
    assert f["fam_mother_conditions"]["path"] == "family_history[mother].conditions"
    assert f["cc_text_no"]["path"] == "communication_consent.text_message.no"
    assert f["hx_depression_anxiety"]["path"] == "medical_history.options.depression_anxiety"
    assert f["fin_print_name"]["path"] == "financial_agreement.printed_name"
    assert f["ins2_holder"]["path"] == "secondary_insurance.policy_holder_name"


def test_ask_owner_and_find(processed):
    doc = processed["C"]
    found = ask(doc, "find", "hypertension")
    owners = {r["ref"]: r["owner"] for r in found}
    assert set(owners.values()) == {"Maria Rivera", "Mother"}
    fam_cond = next(r["ref"].split(".")[0] for r in found if r["owner"] == "Mother" and r["ref"].startswith("COND"))
    ans = ask(doc, "owner", fam_cond)
    assert ans["owner_name"] == "Mother" and ans["via"]


def test_ask_related_section_evidence(processed):
    doc = processed["C"]
    dr = next(e["id"] for e in doc["entities"].values() if e["label"] == "Dr. Priya Nair")
    path = ask(doc, "related", dr, "PAT_001")
    assert path["related"] and path["hops"] == 2
    sec = ask(doc, "section", "PAT_001.date_of_birth")
    assert sec["heading"] == "PATIENT DEMOGRAPHICS" and sec["printed_label"] == "DOB"
    signs = next(r for r in doc["relationships"] if r["predicate"] == "SIGNS" and r["support"] == "uncertain")
    ev = ask(doc, "evidence", signs["relationship_id"])
    assert ev["pages"] == [2] and ev["warnings"]
    with pytest.raises(AskError):
        ask(doc, "owner", "NOPE_001")
    with pytest.raises(AskError):
        ask(doc, "what")


def test_normalisation():
    assert parse_date("7/14/1985") == "1985-07-14"
    assert parse_date("03-22-1983") == "1983-03-22"
    assert parse_date("July 14, 1985") == "1985-07-14"
    assert parse_date("not a date") is None
    assert format_phone("217.555.0143") == "(217) 555-0143"
    assert format_phone("800-555-0199") == "(800) 555-0199"
    assert split_person_name("Rivera, Maria L.") == ("Maria", "Rivera")
    assert split_person_name("Maria L. Rivera") == ("Maria", "Rivera")
    assert same_person("Rivera, Maria L.", "Maria Rivera")
    assert not same_person("Ana Lopez", "Maria Rivera")
    assert not same_person("Karin Lindqvist", "Erik Lindqvist")


def test_cli_process_and_ask(tmp_path, samples_dir, capsys):
    src = tmp_path / "in"
    src.mkdir()
    (src / "c.pdf").write_bytes((samples_dir / "intake_C_other_clinic_rivera.pdf").read_bytes())
    out = tmp_path / "out"
    assert main(["process", str(src), "-o", str(out)]) == 0
    assert (out / "DOC_001.json").exists() and (out / "DOC_001_standardized.pdf").exists()
    index = json.loads((out / "index.json").read_text())
    assert index["documents"][0]["status"] == "needs_review"
    queue = json.loads((out / "review_queue.json").read_text())
    assert queue["count"] == 7 and queue["items"][0]["doc_id"] == "DOC_001"
    capsys.readouterr()
    assert main(["ask", str(out / "DOC_001.json"), "owner", "COND_006"]) == 0
    assert json.loads(capsys.readouterr().out)["owner_name"] == "Mother"
    assert main(["ask", str(out / "DOC_001.json"), "owner", "XYZ_001"]) == 2
