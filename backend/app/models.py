"""Shared backend data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .geometry import Point


@dataclass(frozen=True, slots=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> Point:
        return Point(self.x + self.width / 2.0, self.y + self.height / 2.0)

    def as_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


@dataclass(frozen=True, slots=True)
class FaceObservation:
    face_box: Box
    mouth_score: float
    jaw_variation: float
    shoulder_point: Point
    chest_point: Point
    head_top_point: Point
    torso_visible: bool
    shirt_histogram: tuple[float, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FaceObservation":
        box = payload.get("faceBox", payload.get("face_box"))
        shoulder = payload.get("shoulderPoint", payload.get("shoulder_point"))
        chest = payload.get("chestPoint", payload.get("chest_point"))
        head = payload.get("headTopPoint", payload.get("head_top_point"))
        return cls(
            face_box=Box(float(box["x"]), float(box["y"]), float(box["width"]), float(box["height"])),
            mouth_score=float(payload.get("mouthScore", payload.get("mouth_score", 0.0))),
            jaw_variation=float(payload.get("jawVariation", payload.get("jaw_variation", 0.0))),
            shoulder_point=Point(float(shoulder["x"]), float(shoulder["y"])),
            chest_point=Point(float(chest["x"]), float(chest["y"])),
            head_top_point=Point(float(head["x"]), float(head["y"])),
            torso_visible=bool(payload.get("torsoVisible", payload.get("torso_visible", True))),
            shirt_histogram=tuple(float(value) for value in payload.get("shirtHistogram", payload.get("shirt_histogram", []))),
        )


@dataclass(slots=True)
class Turn:
    id: str
    speaker_id: str | None
    text: str
    start: float
    end: float
    confidence: float
    partial: bool = False
    tags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "speakerId": self.speaker_id,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence,
            "partial": self.partial,
            "tags": self.tags,
        }
