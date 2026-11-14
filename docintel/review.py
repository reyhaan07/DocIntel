"""Human review: confirm, correct or reject what the system flagged.

Every decision is applied to the document JSON, written to an audit log
(``review_log``) and reflected in the summary, the status and the standardized
form.  A fully reviewed document can be exported as ground truth, which is how
the accuracy suite grows over time.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .normalize import parse_date, split_list

ACTIONS = {
    "attribute": ("confirm", "correct"),
    "relationship": ("confirm", "reject"),
    "validation": ("confirm",),
    "ocr": ("dismiss",),
}


class ReviewError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _coerce(new, old):
    """Give a corrected value the shape of the value it replaces."""
    if isinstance(new, str):
        new = new.strip()
    if isinstance(old, list):
        return split_list(new) if isinstance(new, str) else list(new)
    if isinstance(old, str) and len(old) == 10 and old[4] == "-" and old[7] == "-" and isinstance(new, str):
        return parse_date(new) or new
    if new == "":
        return None
    return new


def apply(doc: dict, review_id: str, action: str, value=None, note: str | None = None, reviewer: str = "reviewer") -> dict:
    item = next((r for r in doc["review_queue"] if r["review_id"] == review_id), None)
    if item is None:
        raise ReviewError(f"unknown review item {review_id}")
    if item.get("resolution"):
        raise ReviewError(f"{review_id} was already resolved")
    allowed = ACTIONS.get(item["kind"], ())
    if action not in allowed:
        raise ReviewError(f"'{action}' is not possible for a {item['kind']} item (use: {', '.join(allowed)})")
    at = _now()
    entry = {"review_id": review_id, "kind": item["kind"], "target": item["target"], "action": action, "at": at,
             "reviewer": reviewer}
    if item["kind"] == "attribute":
        ent = doc["entities"].get(item["entity"])
        attr = ent["attributes"].get(item["attribute"]) if ent else None
        if attr is None:
            raise ReviewError(f"{item['target']} no longer exists")
        if action == "correct":
            if value is None:
                raise ReviewError("a corrected value is required")
            new = _coerce(value, attr.get("value"))
            if item["attribute"] == "decision" and new not in ("yes", "no"):
                raise ReviewError("a consent decision must be 'yes' or 'no'")
            entry.update({"from": attr.get("value"), "to": new})
            attr["value"] = new
            attr["confidence"] = 1.0
        attr["status"] = "valid"
        attr["reviewed"] = {"action": "corrected" if action == "correct" else "confirmed", "at": at, "by": reviewer}
        if action == "correct":
            attr["reviewed"]["from"] = entry["from"]
    elif item["kind"] == "relationship":
        rel = next((r for r in doc["relationships"] if r["relationship_id"] == item["target"]), None)
        if rel is None:
            raise ReviewError(f"{item['target']} no longer exists")
        if action == "confirm":
            rel["support"] = "explicit"
            rel["status"] = "valid"
            rel["reviewed"] = {"action": "confirmed", "at": at, "by": reviewer, "warnings": rel.get("warnings", [])}
            rel["warnings"] = []
        else:
            doc["relationships"] = [r for r in doc["relationships"] if r is not rel]
            doc.setdefault("rejected_relationships", []).append(dict(rel, rejected={"at": at, "by": reviewer}))
            subj = doc["entities"].get(rel["subject"])
            if subj:  # a link stored on the entity (e.g. prescribing_doctor_id) goes with the relationship
                for k, v in list(subj.items()):
                    if k.endswith("_id") and v == rel["object"]:
                        subj.pop(k)
    if note:
        entry["note"] = note
    item["resolution"] = {"action": action, "at": at, "by": reviewer, **({"value": entry["to"]} if "to" in entry else {})}
    doc.setdefault("review_log", []).append(entry)
    recompute(doc)
    return entry


def recompute(doc: dict) -> None:
    """Refresh counts and status after review decisions."""
    open_items = [r for r in doc["review_queue"] if not r.get("resolution")]
    s = doc["summary"]
    s["review_items"] = len(open_items)
    s["uncertain_relationships"] = sum(1 for r in doc["relationships"] if r["support"] == "uncertain")
    s["relationships"] = len(doc["relationships"])
    s["reviewed_items"] = len(doc["review_queue"]) - len(open_items)
    d = doc["document"]
    if any(r["kind"] == "ocr" for r in open_items):
        d["status"] = "needs_ocr"
    elif open_items or s.get("validation_errors"):
        d["status"] = "needs_review"
    else:
        d["status"] = "completed"
    d["reviewed"] = bool(doc.get("review_log")) and not open_items
