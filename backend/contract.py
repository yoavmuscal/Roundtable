"""Roundtable shared message contract.

Keep this file structurally mirrored with src/contract.ts. Any contract change
must update both copies in the same commit.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

Phase = Literal["setup", "enroll", "live", "review"]
NetworkState = Literal["none", "detected"]
SpeakerShape = Literal["circle", "square", "diamond", "triangle"]
AnchorMode = Literal["chest", "head", "left", "right", "top"]
PersonState = Literal["seated", "standing", "away"]
CaptionKind = Literal["partial", "final"]
BackendMode = Literal["simulation", "live"]


class Point(TypedDict):
    x: float
    y: float


class Size(TypedDict):
    width: float
    height: float


class Box(TypedDict):
    x: float
    y: float
    width: float
    height: float


class Person(TypedDict):
    id: str
    name: str
    aliases: list[str]
    color: str
    shape: SpeakerShape


class CalibrationPayload(TypedDict):
    corners: list[Point]
    tableSize: Size
    center: Point


class CalibrationResult(TypedDict, total=False):
    ok: bool
    message: str
    centerError: float
    gridLines: list[list[Point]]


class Anchor(TypedDict):
    point: Point
    mode: AnchorMode


class PersonFrame(TypedDict):
    id: str
    faceBox: Box
    anchor: Anchor
    mapPosition: Point
    state: PersonState
    mouth: float


class Caption(TypedDict, total=False):
    id: str
    turnId: str
    personId: str | None
    text: str
    start: float
    end: float
    kind: CaptionKind
    confidence: float
    nameAlert: bool


class Turn(TypedDict):
    id: str
    personId: str
    text: str
    start: float
    end: float
    confidence: float
    tags: list[str]


class Question(TypedDict, total=False):
    id: str
    turnId: str
    text: str
    askerId: str
    createdAt: float
    answeredAt: float
    overdue: bool


class TalkShare(TypedDict):
    personId: str
    seconds: float
    share: float


class HexCell(TypedDict, total=False):
    q: int
    r: int
    ownerId: str
    opacity: float
    share: float
    contested: bool


class StatusPayload(TypedDict, total=False):
    model: str
    secondsPerTurn: float
    ramGb: float
    network: NetworkState
    backend: BackendMode
    connected: bool
    # Argmax streaming transcriber: off, loading (model warming ~20 s) or listening.
    transcriberState: Literal["off", "loading", "listening"]
    # Set when SpeakerKit puts two enrollment clips in one voice group.
    voiceWarning: str
    voiceCheck: Literal["idle", "checking", "ok", "warn"]


class RefinedPayload(TypedDict):
    correctedTurns: int
    totalTurns: int
    topics: list[str]
    summary: str
    actionItems: list[str]
    turns: list[Turn]


class AnswerPayload(TypedDict):
    question: str
    text: str
    citedTurnIds: list[str]


class ErrorPayload(TypedDict, total=False):
    message: str
    code: str


ClientMessage = dict[str, Any]
ServerMessage = dict[str, Any]

CONTRACT_VERSION = 1

DEFAULT_PEOPLE: list[Person] = [
    {"id": "p1", "name": "Yoav", "aliases": ["Yoav"], "color": "#8B7CF6", "shape": "circle"},
    {"id": "p2", "name": "Maya", "aliases": ["Maya"], "color": "#2DD4A7", "shape": "square"},
    {"id": "p3", "name": "Lee", "aliases": ["Lee"], "color": "#F5A524", "shape": "diamond"},
]

DEFAULT_TABLE_SIZE: Size = {"width": 1.8, "height": 0.9}
