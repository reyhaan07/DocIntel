"""End-to-end behaviour of the five pipeline stages on the bundled samples."""
from conftest import ent_by, rels


# --------------------------------------------------------------------------- another clinic's layout
def test_other_layout_summary(processed):
    doc = processed["C"]
    assert doc["document"]["status"] == "needs_review"
    assert doc["document"]["extraction_method"] == "layout"
    s = doc["summary"]
    assert s["uncertain_relationships"] == 3
    assert s["review_items"] == 7
    assert s["missing_items"] == 2
    assert s["validation_errors"] == 0
    assert s["fields_filled"] == 81 and s["fields_withheld"] == 2


def test_headings_matched_by_meaning(processed):
    doc = processed["C"]
    names = {s["heading"]: s["name"] for s in doc["sections"]}
    assert names["PATIENT DEMOGRAPHICS"] == "Patient Information"
    assert names["MEDICATION LIST"] == "Current Medications"
    assert names["FINANCIAL POLICY"] == "Financial Responsibility Agreement"
    # side-by-side insurance headings get separate column regions
    prim = next(s for s in doc["sections"] if s["key"] == "primary_insurance")
    sec = next(s for s in doc["sections"] if s["key"] == "secondary_insurance")
    assert prim["bbox"][2] <= sec["bbox"][0] + 1


def test_patient_values_are_traced(processed):
    pat = processed["C"]["entities"]["PAT_001"]
    a = pat["attributes"]
    assert a["full_name"]["value"] == "Rivera, Maria L."
    assert a["full_name"]["field_label"] == "Patient Name"
    assert a["date_of_birth"]["value"] == "1985-07-14"
    assert a["date_of_birth"]["field_label"] == "DOB"
    assert a["phone"]["value"] == "(217) 555-0143"
    # derived from the printed name, with lower confidence
    assert a["first_name"]["value"] == "Maria" and a["last_name"]["value"] == "Rivera"
    assert a["first_name"]["extraction_method"] == "derived_split"
    assert a["first_name"]["confidence"] < a["full_name"]["confidence"]
    for attr in a.values():
        assert attr["page"] == 1 and len(attr["bbox"]) == 4


def test_medication_rows_bind_doctor_from_same_row(processed):
    doc = processed["C"]
    sert = ent_by(doc, "Medication", "Sertraline")
    assert sert["row"] == 3
    assert sert["attributes"]["dosage"]["value"] == "50 mg"
    assert sert["attributes"]["dosage"]["field_label"] == "Dose"
    assert sert["attributes"]["dosage"]["extraction_method"] == "layout_table"
    nair = ent_by(doc, "Doctor", "Dr. Priya Nair")
    assert sert["prescribing_doctor_id"] == nair["id"]
    r = rels(doc, "PRESCRIBED_BY", sert["id"])[0]
    assert r["object"] == nair["id"] and r["support"] == "explicit"
    assert "same table row" in r["basis"]
    roles = {e["role"] for e in r["evidence"]}
    assert {"subject", "object", "heading"} <= roles


def test_wrapped_row_is_uncertain_and_no_doctor_invented(processed):
    doc = processed["C"]
    vit = ent_by(doc, "Medication", "Vitamin D3")
    freq = vit["attributes"]["frequency"]
    assert freq["value"] == "Daily (with breakfast)"
    assert freq["status"] == "needs_review" and freq["confidence"] == 0.55
    assert not rels(doc, "PRESCRIBED_BY", vit["id"])
    takes = rels(doc, "TAKES_MEDICATION", obj=vit["id"])[0]
    assert takes["support"] == "uncertain"
    assert any("wraps" in w for w in takes["warnings"])
    assert any(m["entity"] == vit["id"] and m["kind"] == "incomplete_record" for m in doc["missing"])


def test_insurance_policies_never_merge(processed):
    doc = processed["C"]
    pols = [e for e in doc["entities"].values() if e["type"] == "InsurancePolicy"]
    by_type = {p["attributes"]["policy_type"]["value"]: p for p in pols}
    assert by_type["primary"]["attributes"]["member_id"]["value"] == "BRH-4471920"
    assert by_type["secondary"]["attributes"]["member_id"]["value"] == "LKM-88120"
    spouse = ent_by(doc, "Spouse", "Daniel Rivera")
    held = rels(doc, "HELD_BY", by_type["secondary"]["id"])[0]
    assert held["object"] == spouse["id"]
    assert rels(doc, "HELD_BY", by_type["primary"]["id"])[0]["object"] == "PAT_001"
    check = next(c for c in doc["validation"]["checks"] if c["check_id"] == "insurance_policy_separation")
    assert check["status"] == "passed"


def test_family_conditions_have_one_owner(processed):
    doc = processed["C"]
    mother = ent_by(doc, "FamilyMember", "Mother")
    assert mother["attributes"]["living_status"]["value"] == "living"
    assert mother["attributes"]["age"]["value"] == "66"
    assert mother["attributes"]["conditions"]["value"] == ["Type 2 diabetes", "hypertension"]
    hyper = [e for e in doc["entities"].values() if e["type"] == "Condition" and e["label"].lower() == "hypertension"]
    owners = sorted(rels(doc, "HAS_CONDITION", obj=h["id"])[0]["subject"] for h in hyper)
    assert owners == sorted(["PAT_001", mother["id"]])


def test_consent_with_both_boxes_is_left_unresolved(processed):
    doc = processed["C"]
    cons = {e["consent_key"]: e for e in doc["entities"].values() if e["type"] == "Consent"}
    assert cons["voicemail"]["attributes"]["decision"]["value"] == "yes"
    assert cons["email"]["attributes"]["decision"]["value"] == "no"
    text = cons["text_message"]["attributes"]["decision"]
    assert text["value"] is None and text["status"] == "needs_review"
    r = rels(doc, "PROVIDES_CONSENT", obj=cons["text_message"]["id"])[0]
    assert r["support"] == "uncertain"


def test_signature_by_someone_else_is_uncertain(processed):
    doc = processed["C"]
    fin = ent_by(doc, "Agreement", "Financial Responsibility Agreement")
    assert fin["attributes"]["signature"]["extraction_method"] == "layout_signature"
    r = rels(doc, "SIGNS", obj=fin["id"])[0]
    assert r["support"] == "uncertain" and r["confidence"] == 0.75
    assert "Ana Lopez" in r["warnings"][0]
    cft = ent_by(doc, "Agreement", "Consent for Treatment")
    assert rels(doc, "SIGNS", obj=cft["id"])[0]["support"] == "explicit"
    assert any(m["path"] == "hipaa_acknowledgment.printed_name" for m in doc["missing"])


def test_seven_checks_and_review_queue_order(processed):
    doc = processed["C"]
    assert len(doc["validation"]["checks"]) == 7
    kinds = [r["kind"] for r in doc["review_queue"]]
    assert kinds == ["validation", "validation", "attribute", "attribute", "relationship", "relationship", "relationship"]
    assert [r["review_id"] for r in doc["review_queue"]] == [f"REV_{i:03d}" for i in range(1, 8)]


def test_every_relationship_has_allowed_signature_and_evidence(processed):
    for key in "ABC":
        doc = processed[key]
        check = next(c for c in doc["validation"]["checks"] if c["check_id"] == "predicate_signatures")
        assert check["status"] == "passed" and check["checked"] == len(doc["relationships"])
        for r in doc["relationships"]:
            assert r["evidence"], r["relationship_id"]
            assert r["basis"]


# --------------------------------------------------------------------------- fillable & flattened
def test_fillable_form_is_read_from_fields(processed):
    doc = processed["A"]
    assert doc["document"]["status"] == "completed"
    assert doc["document"]["extraction_method"] == "form_fields"
    assert doc["summary"]["review_items"] == 0 and doc["summary"]["validation_errors"] == 0
    pat = doc["entities"]["PAT_001"]
    assert pat["label"] == "Chidi Okafor"
    assert pat["attributes"]["first_name"]["extraction_method"] == "form_field"
    assert pat["attributes"]["first_name"]["confidence"] == 0.98
    fam = ent_by(doc, "FamilyMember", "Father")
    assert fam["attributes"]["living_status"]["value"] == "deceased"


def test_flattened_form_detects_ticked_boxes_and_ink(processed):
    doc = processed["B"]
    assert doc["document"]["extraction_method"] == "layout"
    cons = {e["consent_key"]: e["attributes"]["decision"]["value"]
            for e in doc["entities"].values() if e["type"] == "Consent"}
    assert cons == {"voicemail": "yes", "text_message": "no", "email": "yes", "release_of_information": "no"}
    conds = {e["label"] for e in doc["entities"].values() if e["type"] == "Condition" and e.get("owner_hint") == "patient"}
    assert conds == {"Asthma", "Thyroid disorder"}
    sigs = [e["attributes"]["signature"] for e in doc["entities"].values() if e["type"] == "Agreement"]
    assert len(sigs) == 3 and all(s["extraction_method"] == "layout_signature" for s in sigs)
    assert doc["summary"]["review_items"] == 1
    assert not any(e["type"] == "Spouse" for e in doc["entities"].values())


def test_scanned_pdf_without_ocr_is_flagged(processed):
    doc = processed["D"]
    assert doc["document"]["status"] == "needs_ocr"
    assert all(p["image_only"] for p in doc["document"]["pages"])
    assert [r["kind"] for r in doc["review_queue"]] == ["ocr", "ocr"]
    assert doc["summary"]["relationships"] == 0
