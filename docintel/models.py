"""Core data structures shared by the pipeline stages."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Token:
    """A positioned piece of page content (word, form-field value or checkbox).

    Coordinates are PDF points with a *top-left* origin: (x0, top, x1, bottom).
    """

    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    page: int
    source: str = "text"  # text | form_field | ocr | visual
    kind: str = "word"  # word | checkbox | placeholder | furniture (running header/footer)
    checked: bool | None = None
    field_name: str | None = None
    bold: bool = False
    size: float = 0.0
    conf: float = 1.0
    hint: str | None = None  # a form field's own description (tooltip), when it has one

    @property
    def bbox(self) -> list[float]:
        return [round(self.x0, 1), round(self.top, 1), round(self.x1, 1), round(self.bottom, 1)]

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def is_content(self) -> bool:
        if self.kind == "furniture":  # running header / footer
            return False
        return bool(self.text.strip()) or self.kind in ("checkbox", "placeholder")


@dataclass
class Mark:
    """Ink on the page that is not text: a drawn or image signature."""

    page: int
    x0: float
    top: float
    x1: float
    bottom: float
    kind: str = "drawn"  # drawn | image

    @property
    def bbox(self) -> list[float]:
        return [round(self.x0, 1), round(self.top, 1), round(self.x1, 1), round(self.bottom, 1)]

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass
class PageData:
    number: int
    width: float
    height: float
    tokens: list[Token] = field(default_factory=list)
    marks: list[Mark] = field(default_factory=list)
    has_text: bool = False
    image_only: bool = False
    ocr_used: bool = False
    form_fields: int = 0
    deskew_angle: float = 0.0
    rotation: int = 0  # clockwise quarter turn applied to read a sideways scan
    boxes: list = field(default_factory=list)  # drawn value boxes (x0, top, x1, bottom)
    text_layer: str = "none"  # none | good | unreadable (garbage replaced by OCR)
    ocr_regions: int = 0  # embedded scans on a digital page that were read by OCR


@dataclass
class Line:
    tokens: list[Token]

    @property
    def top(self) -> float:
        return min(t.top for t in self.tokens)

    @property
    def bottom(self) -> float:
        return max(t.bottom for t in self.tokens)

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def x0(self) -> float:
        return min(t.x0 for t in self.tokens)

    @property
    def x1(self) -> float:
        return max(t.x1 for t in self.tokens)

    @property
    def page(self) -> int:
        return self.tokens[0].page

    @property
    def text(self) -> str:
        return " ".join(t.text for t in self.tokens if t.text)


@dataclass
class Region:
    """A page rectangle owned by one recognised section heading."""

    region_id: str
    key: str  # template section key
    name: str  # canonical section name
    heading: str  # heading text exactly as printed
    page: int
    x0: float
    top: float
    x1: float
    bottom: float
    heading_bbox: list[float]
    continued: bool = False
    heading_page: int | None = None  # a continued region's heading is on an earlier page

    @property
    def hpage(self) -> int:
        return self.heading_page or self.page

    def contains(self, t: Token | Mark) -> bool:
        cx = (t.x0 + t.x1) / 2
        cy = (t.top + t.bottom) / 2
        return t.page == self.page and self.x0 <= cx <= self.x1 and self.top <= cy <= self.bottom

    def to_json(self) -> dict:
        return {
            "section_id": self.region_id,
            "key": self.key,
            "name": self.name,
            "heading": self.heading,
            "page": self.page,
            "bbox": [round(self.x0, 1), round(self.top, 1), round(self.x1, 1), round(self.bottom, 1)],
            "heading_bbox": self.heading_bbox,
            "heading_page": self.hpage,
            "continued": self.continued,
        }


@dataclass
class Evidence:
    page: int
    bbox: list[float]
    text: str
    role: str  # value | label | heading | subject | object | signature

    def to_json(self) -> dict:
        return {"page": self.page, "bbox": self.bbox, "text": self.text, "role": self.role}


@dataclass
class Attribute:
    value: Any
    field_label: str | None
    page: int | None
    bbox: list[float] | None
    extraction_method: str
    confidence: float
    raw: str | None = None
    label_bbox: list[float] | None = None
    status: str = "valid"  # valid | needs_review | invalid
    notes: list[str] = field(default_factory=list)
    section: str | None = None
    region_id: str | None = None
    row: int | None = None
    order: tuple = (0, 0.0, 0.0)

    def to_json(self) -> dict:
        d = {
            "value": self.value,
            "field_label": self.field_label,
            "page": self.page,
            "bbox": self.bbox,
            "label_bbox": self.label_bbox,
            "extraction_method": self.extraction_method,
            "confidence": round(self.confidence, 2),
            "status": self.status,
            "section": self.section,
        }
        if self.raw is not None and self.raw != self.value:
            d["raw"] = self.raw
        if self.row is not None:
            d["row"] = self.row
        if self.notes:
            d["notes"] = list(self.notes)
        return d


@dataclass
class Entity:
    id: str
    type: str
    label: str
    section: str | None
    section_key: str | None
    page: int | None
    group: str
    row: int | None = None
    derived: bool = False
    attributes: dict[str, Attribute] = field(default_factory=dict)
    links: dict[str, str] = field(default_factory=dict)
    region_id: str | None = None
    extra: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        attrs = sorted(self.attributes.items(), key=lambda kv: kv[1].order)
        d = {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "group": self.group,
            "section": self.section,
            "section_key": self.section_key,
            "section_id": self.region_id,
            "page": self.page,
            "row": self.row,
            "derived": self.derived,
            "attributes": {k: a.to_json() for k, a in attrs},
        }
        d.update(self.links)
        d.update(self.extra)
        return d


@dataclass
class Relationship:
    id: str
    subject: str
    predicate: str
    object: str
    support: str  # explicit | uncertain
    confidence: float
    basis: str
    section: str | None = None
    heading: str | None = None
    page: int | None = None
    row: int | None = None
    evidence: list[Evidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "relationship_id": self.id,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "support": self.support,
            "confidence": round(self.confidence, 2),
            "basis": self.basis,
            "section": self.section,
            "heading": self.heading,
            "page": self.page,
            "row": self.row,
            "evidence": [e.to_json() for e in self.evidence],
            "warnings": list(self.warnings),
            "status": "needs_review" if self.support == "uncertain" else "valid",
        }
