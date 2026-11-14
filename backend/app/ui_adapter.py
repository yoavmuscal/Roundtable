"""Translate the backend engine's internal events to the shared UI contract."""

from __future__ import annotations

from typing import Any


def browser_to_internal(message: dict[str, Any]) -> dict[str, Any]:
    message_type = message.get("type")
    if message_type == "calibrate":
        payload = message.get("payload", {})
        size = payload.get("tableSize", {})
        return {
            "type": "calibrate",
            "corners": payload.get("corners"),
            "tableSize": {"widthM": size.get("width"), "heightM": size.get("height")},
            "centerClick": payload.get("center"),
        }
    if message_type == "faces":
        return {
            "type": "faces",
            "time": message.get("at"),
            "people": [
                {
                    "faceBox": face.get("faceBox"),
                    "mouthScore": face.get("mouth", face.get("mouthScore", 0.0)),
                    "jawVariation": face.get("jawVariation", 0.0),
                    "shoulderPoint": face.get("shoulder", face.get("shoulderPoint")),
                    "chestPoint": face.get("chest", face.get("chestPoint")),
                    "headTopPoint": face.get("headTop", face.get("headTopPoint")),
                    "torsoVisible": face.get("torsoVisible", True),
                    "shirtHistogram": face.get("shirtHistogram", []),
                }
                for face in message.get("faces", message.get("people", []))
            ],
        }
    if message_type == "control":
        return {**message, "action": str(message.get("action", "")).replace("-", "_")}
    if message_type == "seat-drag":
        return {
            "type": "seat_drag",
            "personId": message.get("personId"),
            "position": message.get("mapPosition"),
        }
    return message


def internal_to_ui(message: dict[str, Any]) -> dict[str, Any] | None:
    message_type = message.get("type")
    at = float(message.get("time", 0.0))
    if message_type == "replay":
        return {
            "type": "replay",
            "session": message.get("session", "session"),
            "videoUrl": message.get("videoUrl"),
            "speed": message.get("speed", 1.0),
        }
    if message_type == "pong":
        return {"type": "pong", "nonce": str(message.get("nonce", message.get("sentAt", ""))), "backendTime": at}
    if message_type == "calibration_result":
        result = {
            "ok": bool(message.get("ok", False)),
            "message": message.get("message") or ("Calibration looks good." if message.get("ok") else "Calibration needs another look."),
            "centerError": message.get("centerError"),
            "gridLines": message.get("gridLines", message.get("grid")),
        }
        return {"type": "calibration", "result": result}
    if message_type == "people":
        return {"type": "people", "people": [_person(person) for person in message.get("people", [])]}
    if message_type == "enroll_prompt":
        return {
            "type": "enroll-prompt",
            "personId": message.get("personId"),
            "prompt": message.get("prompt", message.get("instruction", "Say your name clearly.")),
            "index": message.get("index", 0),
            "total": message.get("total", 3),
        }
    if message_type == "people_frame":
        return {
            "type": "people-frame",
            "at": at,
            "people": [
                {
                    "id": person.get("id"),
                    "faceBox": person.get("faceBox"),
                    "anchor": person.get("anchor", person.get("captionAnchor")),
                    "mapPosition": person.get("mapPosition"),
                    "state": person.get("state", "seated"),
                    "mouth": person.get("mouth", 0.0),
                }
                for person in message.get("people", [])
            ],
        }
    if message_type == "level":
        return {"type": "level", "at": at, "rms": message.get("rms", 0.0)}
    if message_type == "caption":
        partial = bool(message.get("partial", False))
        turn_id = str(message.get("turnId", f"turn-{at:.3f}"))
        return {
            "type": "caption",
            "caption": {
                "id": f"{turn_id}:{'partial' if partial else 'final'}",
                "turnId": turn_id,
                "personId": message.get("speakerId", message.get("personId")),
                "text": message.get("text", ""),
                "start": message.get("start", at),
                "end": message.get("end", at),
                "kind": "partial" if partial else "final",
                "confidence": message.get("confidence", 0.0),
                "nameAlert": bool(message.get("nameAlert")),
            },
        }
    if message_type == "active_speaker":
        person_id = message.get("personId")
        return {
            "type": "active-speaker",
            "personId": person_id,
            "at": at,
            "confidence": message.get("confidence", 0.9 if person_id else 0.0),
        }
    if message_type == "tags":
        return {
            "type": "tags",
            "turnId": message.get("turnId"),
            "tags": message.get("tags", []),
            "repliesTo": message.get("repliesTo"),
            "actionOwnerId": message.get("actionOwner", message.get("actionOwnerId")),
        }
    if message_type == "map":
        return {
            "type": "map",
            "at": at,
            "hexes": [
                {
                    "q": item.get("q", item.get("axial", {}).get("q")),
                    "r": item.get("r", item.get("axial", {}).get("r")),
                    "ownerId": item.get("ownerId", item.get("owner")),
                    "opacity": item.get("opacity", 0.0),
                    "share": item.get("share", 0.0),
                    "contested": item.get("contested", False),
                }
                for item in message.get("hexes", [])
            ],
        }
    if message_type == "stats":
        shares = message.get("talkShares", {})
        if isinstance(shares, dict):
            talk_shares = [
                {"personId": person_id, "seconds": round(share * at, 2), "share": share}
                for person_id, share in shares.items()
            ]
        else:
            talk_shares = shares
        questions = message.get("questions", {})
        open_questions = [_question(item) for item in questions.get("open", message.get("openQuestions", []))]
        return {
            "type": "stats",
            "at": at,
            "talkShares": talk_shares,
            "openQuestions": open_questions,
            "overdueQuestions": [item for item in open_questions if item.get("overdue")],
        }
    if message_type == "status":
        payload = dict(message)
        payload.pop("type", None)
        payload.pop("version", None)
        at_value = payload.pop("time", 0.0)
        payload.setdefault("backend", "simulation")
        payload.setdefault("connected", True)
        payload.setdefault("secondsPerTurn", payload.pop("seconds_per_turn", 0.0))
        payload.setdefault("ramGb", payload.pop("ram_gb", 0.0))
        payload.setdefault("network", "none")
        payload.pop("health", None)
        return {"type": "status", "status": payload}
    if message_type == "answer":
        return {
            "type": "answer",
            "answer": {
                "question": message.get("question", ""),
                "text": message.get("text", ""),
                "citedTurnIds": message.get("citedTurnIds", []),
            },
        }
    if message_type == "phase":
        # Refine runs on the Review screen (progress ring) so Stop visibly ends Live at once.
        phase = message.get("phase", "setup")
        return {"type": "phase", "phase": "review" if phase == "refine" else phase}
    if message_type == "refine_progress":
        return {
            "type": "refine-progress",
            "progress": message.get("progress", 0.0),
            "message": message.get("stage", message.get("message", "Refining")),
        }
    if message_type == "refined":
        summary = message.get("summary", {})
        if isinstance(summary, str):
            summary = {"summary": summary, "actionItems": []}
        turns = [_turn(turn) for turn in message.get("turns", [])]
        return {
            "type": "refined",
            "refined": {
                "correctedTurns": message.get("changedCount", message.get("correctedTurns", 0)),
                "totalTurns": message.get("totalCount", message.get("totalTurns", len(turns))),
                "topics": message.get("topics", []),
                "summary": summary.get("summary", ""),
                "actionItems": summary.get("actionItems", []),
                "turns": turns,
            },
        }
    if message_type == "error":
        payload: dict[str, Any] = {"type": "error", "message": message.get("message", "Backend error")}
        if message.get("code") is not None:
            payload["code"] = message["code"]
        return payload
    return message


def _person(person: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": person.get("id"),
        "name": person.get("name", person.get("id", "Speaker")),
        "aliases": person.get("aliases", []),
        "color": person.get("color", "#8B7CF6"),
        "shape": person.get("shape", "circle"),
    }


def _question(question: dict[str, Any]) -> dict[str, Any]:
    turn_id = question.get("turnId", question.get("id", ""))
    return {
        "id": question.get("id", turn_id),
        "turnId": turn_id,
        "text": question.get("text", ""),
        "askerId": question.get("askerId", question.get("speakerId", "")),
        "createdAt": question.get("createdAt", question.get("askedAt", 0.0)),
        "answeredAt": question.get("answeredAt"),
        "overdue": question.get("overdue", False),
    }


def _turn(turn: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": turn.get("id"),
        "personId": turn.get("personId", turn.get("speakerId")),
        "text": turn.get("text", ""),
        "start": turn.get("start", 0.0),
        "end": turn.get("end", 0.0),
        "confidence": turn.get("confidence", 0.0),
        "tags": turn.get("tags", []),
    }
