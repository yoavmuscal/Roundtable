"""Backend constants and validation for the shared external contract.

The canonical mirrors are backend/contract.py and src/contract.ts. This module
only adds backend-side validation and constants used by the Python engine.
"""

from __future__ import annotations

from typing import Any

from backend.contract import CONTRACT_VERSION, DEFAULT_PEOPLE

PERSON_IDS = ("p1", "p2", "p3", "p4")
TURN_ID_FORMAT = "turn_{sequence:04d}"

BROWSER_MESSAGE_TYPES = frozenset({"hello", "ping", "calibrate", "faces", "control", "ask", "seat-drag"})
BACKEND_MESSAGE_TYPES = frozenset(
    {
        "replay",
        "pong",
        "calibration",
        "people",
        "enroll-prompt",
        "people-frame",
        "level",
        "caption",
        "active-speaker",
        "tags",
        "map",
        "stats",
        "status",
        "answer",
        "phase",
        "refine-progress",
        "refined",
        "error",
    }
)
CONTROL_ACTIONS = frozenset(
    {
        "start",
        "stop",
        "enroll-next",
        "enroll-redo",
        "enroll-skip",
        "ask-begin",
        "ask-end",
        "recalibrate",
        "confirm-seats",
    }
)
PHASES = ("setup", "enroll", "live", "review")
SPEAKERS = tuple(DEFAULT_PEOPLE) + (
    {"id": "p4", "name": "Speaker 4", "aliases": [], "color": "#F472B6", "shape": "triangle"},
)

DEFAULT_THRESHOLDS: dict[str, float] = {
    "fusion_top": 0.35,
    "fusion_margin": 0.12,
    "fusion_fallback": 0.25,
    "previous_speaker_window_s": 1.5,
    "mouth_scale": 0.08,
    "active_hysteresis_s": 0.3,
    "reach_cap_min_m": 0.35,
    "reach_cap_scale_m": 0.7,
    "tracker_match_distance": 0.15,
    "tracker_reidentify_similarity": 0.8,
    "tracker_away_after_s": 2.0,
    "tracker_newcomer_after_s": 3.0,
    "seat_follow_distance_m": 0.5,
    "seat_follow_after_s": 3.0,
}


class MessageValidationError(ValueError):
    """Raised when a WebSocket message violates the shared contract."""


def turn_id(sequence: int) -> str:
    if sequence < 1:
        raise ValueError("turn sequence is one-based")
    return TURN_ID_FORMAT.format(sequence=sequence)


def validate_browser_message(message: dict[str, Any]) -> dict[str, Any]:
    message_type = message.get("type")
    if message_type not in BROWSER_MESSAGE_TYPES:
        raise MessageValidationError(f"unknown browser message type: {message_type!r}")
    if message_type == "hello" and message.get("version") != CONTRACT_VERSION:
        raise MessageValidationError(
            f"unsupported contract version {message.get('version')!r}; expected {CONTRACT_VERSION}"
        )
    if message_type == "control" and message.get("action") not in CONTROL_ACTIONS:
        raise MessageValidationError(f"unknown control action: {message.get('action')!r}")
    return message
