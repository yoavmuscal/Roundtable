"""Shared Roundtable WebSocket message contract.

Keep this file byte-for-byte aligned semantically with web/src/lib/contract.ts.
Any change must update both copies in the same commit.
"""

from __future__ import annotations

import time
from typing import Any

CONTRACT_VERSION = 1

PERSON_IDS = ("p1", "p2", "p3", "p4")
TURN_ID_FORMAT = "turn_{sequence:04d}"

BROWSER_MESSAGE_TYPES = frozenset(
    {
        "hello",       # {client, version}
        "ping",        # {sentAt, sequence}
        "calibrate",   # {corners[4], tableSize, centerClick}
        "faces",       # {time, people: FaceObservation[]}
        "control",     # {action, ...}
        "ask",         # {text}
        "seat_drag",   # {personId, position}
    }
)

BACKEND_MESSAGE_TYPES = frozenset(
    {
        "replay",
        "pong",
        "calibration_result",
        "people",
        "enroll_prompt",
        "people_frame",
        "level",
        "caption",
        "active_speaker",
        "tags",
        "map",
        "stats",
        "status",
        "answer",
        "phase",
        "refine_progress",
        "refined",
        "error",
    }
)

CONTROL_ACTIONS = frozenset(
    {
        "start",
        "stop",
        "enroll_next",
        "enroll_redo",
        "enroll_skip",
        "ask_begin",
        "ask_end",
        "recalibrate",
        "confirm_seats",
    }
)

PHASES = ("setup", "enroll", "live", "refine", "review")

SPEAKERS = (
    {"id": "p1", "color": "#8B7CF6", "shape": "circle"},
    {"id": "p2", "color": "#2DD4A7", "shape": "square"},
    {"id": "p3", "color": "#F5A524", "shape": "diamond"},
    {"id": "p4", "color": "#F472B6", "shape": "triangle"},
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


def make_message(message_type: str, **payload: Any) -> dict[str, Any]:
    """Create a backend message with version and backend timestamp."""
    if message_type not in BACKEND_MESSAGE_TYPES:
        raise MessageValidationError(f"unknown backend message type: {message_type}")
    return {
        "type": message_type,
        "version": CONTRACT_VERSION,
        "time": payload.pop("time", time.monotonic()),
        **payload,
    }


def validate_browser_message(message: dict[str, Any]) -> dict[str, Any]:
    message_type = message.get("type")
    if message_type not in BROWSER_MESSAGE_TYPES:
        raise MessageValidationError(f"unknown browser message type: {message_type!r}")
    version = message.get("version", CONTRACT_VERSION)
    if version != CONTRACT_VERSION:
        raise MessageValidationError(
            f"unsupported contract version {version!r}; expected {CONTRACT_VERSION}"
        )
    if message_type == "control" and message.get("action") not in CONTROL_ACTIONS:
        raise MessageValidationError(f"unknown control action: {message.get('action')!r}")
    return message
