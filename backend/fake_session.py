from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass
from typing import Any

from .contract import DEFAULT_PEOPLE, DEFAULT_TABLE_SIZE, Caption, Person, PersonFrame, Question, Turn
from .heatmap import HeatMap

SESSION_NAME = "synthetic-roundtable-01"
SESSION_DURATION = 91.0


@dataclass(frozen=True)
class ScriptedTurn:
    person_id: str
    start: float
    end: float
    text: str
    tags: tuple[str, ...] = ()


SCRIPT: tuple[ScriptedTurn, ...] = (
    ScriptedTurn("p1", 2, 8, "Welcome everyone. Let's map the launch plan and keep every voice on the table."),
    ScriptedTurn("p2", 10, 15, "Who owns the accessibility checklist for Friday's demo?", ("question",)),
    ScriptedTurn("p3", 17, 21, "I can own the checklist, but I need the final caption colors today.", ("decision", "action")),
    ScriptedTurn("p2", 23, 29, "Yoav, can you test the name alert and large captions before dinner?", ("question", "action")),
    ScriptedTurn("p1", 31, 39, "Yes. I will run both accessibility checks in replay and on the iPhone camera."),
    ScriptedTurn("p3", 41, 45, "What time should we rehearse the submission pitch?", ("question",)),
    ScriptedTurn("p1", 45, 52, "Let's decide after the first full run, then leave thirty minutes for fixes.", ("decision",)),
    ScriptedTurn("p3", 54, 58, "I'll capture the corrected transcript and cite the turns in the answer card.", ("action",)),
    ScriptedTurn("p2", 65, 70, "I'm back. The room map kept my seat while I stepped away."),
    ScriptedTurn("p1", 72, 81, "For the demo, lead with the student who needs to know who is speaking and when their name is called.", ("decision",)),
    ScriptedTurn("p2", 82, 86, "That answers the checklist question and gives us a strong accessibility story."),
    ScriptedTurn("p3", 87, 91, "I'll send the action items as soon as the refine pass finishes.", ("action",)),
)


def _contains_name(text: str, people: list[Person]) -> bool:
    for person in people:
        for alias in [person["name"], *person.get("aliases", [])]:
            if not alias:
                continue
            if re.search(rf"(?<![\w]){re.escape(alias)}(?![\w])", text, re.IGNORECASE):
                return True
    return False


def _active_turn(at: float) -> ScriptedTurn | None:
    return next((turn for turn in SCRIPT if turn.start <= at <= turn.end), None)


def _person_position(person_id: str, at: float) -> tuple[float, float, str]:
    if person_id == "p1":
        return 0.42, -0.45, "seated"
    if person_id == "p2":
        state = "away" if 59 <= at < 64 else "seated"
        return 0.90, -0.45, state
    progress = min(1.0, max(0.0, (at - 45) / 5))
    return 1.26 + progress * 0.24, -0.45, "seated"


def _face_frame(person_id: str, at: float) -> PersonFrame:
    x, y, state = _person_position(person_id, at)
    image_x = {1: 0.27, 2: 0.50, 3: 0.72}[int(person_id[1])]
    if person_id == "p3":
        image_x += min(1.0, max(0.0, (at - 45) / 5)) * 0.06
    active = _active_turn(at)
    mouth = 0.0
    if active and active.person_id == person_id:
        mouth = min(1.0, 0.62 + math.sin(at * 15) * 0.28)
    face_box = {"x": image_x, "y": 0.30, "width": 0.105, "height": 0.19}
    head_mode = person_id == "p3"
    anchor = (
        {"point": {"x": image_x + 0.052, "y": 0.30 - 0.055}, "mode": "head"}
        if head_mode
        else {"point": {"x": image_x + 0.052, "y": 0.62}, "mode": "chest"}
    )
    return {
        "id": person_id,
        "faceBox": face_box,
        "anchor": anchor,  # type: ignore[typeddict-item]
        "mapPosition": {"x": x, "y": y},
        "state": state,  # type: ignore[typeddict-item]
        "mouth": round(max(0.0, mouth), 3),
    }


def _turns() -> list[Turn]:
    output: list[Turn] = []
    for index, item in enumerate(SCRIPT, start=1):
        output.append(
            {
                "id": f"turn_{index:04d}",
                "personId": item.person_id,
                "text": item.text,
                "start": item.start,
                "end": item.end,
                "confidence": 0.93 if index != 7 else 0.47,
                "tags": list(item.tags),
            }
        )
    return output


def _questions(at: float) -> list[Question]:
    questions: list[Question] = []
    if at >= 41:
        questions.append(
            {
                "id": "question_0001",
                "turnId": "turn_0006",
                "text": "What time should we rehearse the submission pitch?",
                "askerId": "p3",
                "createdAt": 41,
                "overdue": at >= 86,
            }
        )
    if at >= 72:
        questions.append(
            {
                "id": "question_0002",
                "turnId": "turn_0010",
                "text": "Who is speaking and when their name is called?",
                "askerId": "p1",
                "createdAt": 72,
                "overdue": False,
            }
        )
    return questions


def build_events(people: list[Person]) -> list[tuple[float, dict[str, Any]]]:
    events: list[tuple[float, dict[str, Any]]] = [
        (0.0, {"type": "phase", "phase": "live"}),
        (0.0, {"type": "people", "people": people}),
        (
            0.0,
            {
                "type": "status",
                "status": {
                    "model": "Replay + mock Bonsai",
                    "secondsPerTurn": 0.8,
                    "ramGb": 5.8,
                    "network": "none",
                    "backend": "simulation",
                    "connected": True,
                },
            },
        ),
    ]
    heat = HeatMap(DEFAULT_TABLE_SIZE)
    last_map: tuple[float, dict[str, Any]] | None = None

    for index, scripted in enumerate(SCRIPT, start=1):
        turn_id = f"turn_{index:04d}"
        words = scripted.text.split()
        partial_text = " ".join(words[: max(1, int(len(words) * 0.48))])
        partial: Caption = {
            "id": f"caption_{index:04d}_partial",
            "turnId": turn_id,
            "personId": scripted.person_id,
            "text": partial_text,
            "start": scripted.start,
            "kind": "partial",
            "confidence": 0.68,
        }
        final: Caption = {
            "id": f"caption_{index:04d}_final",
            "turnId": turn_id,
            "personId": scripted.person_id,
            "text": scripted.text,
            "start": scripted.start,
            "end": scripted.end,
            "kind": "final",
            "confidence": 0.93 if index != 7 else 0.47,
            "nameAlert": _contains_name(scripted.text, people),
        }
        events.extend(
            [
                (scripted.start, {"type": "caption", "caption": partial}),
                ((scripted.start + scripted.end) / 2, {"type": "caption", "caption": partial}),
                (scripted.end, {"type": "caption", "caption": final}),
            ]
        )

    answer_event = {
        "type": "answer",
        "answer": {
            "question": "What did Maya ask Yoav to test?",
            "text": "Maya asked Yoav to test the name alert and large-caption mode before dinner.",
            "citedTurnIds": ["turn_0004"],
        },
    }
    events.append((84.0, answer_event))

    tick = 0.0
    while tick <= SESSION_DURATION + 1e-9:
        frames = [_face_frame(person["id"], tick) for person in people]
        events.append((tick, {"type": "people-frame", "at": round(tick, 2), "people": frames}))

        active = _active_turn(tick)
        off_camera_voice = 61 <= tick < 64
        rms = 0.025
        if active:
            rms = 0.27 + math.sin(tick * 10) * 0.07
        elif off_camera_voice:
            rms = 0.19
        for sub_tick in (0.0, 0.05):
            events.append(
                (
                    tick + sub_tick,
                    {"type": "level", "at": round(tick + sub_tick, 2), "rms": round(max(0.01, rms), 3)},
                )
            )

        if abs(tick * 10 - round(tick * 10)) < 1e-9 and round(tick * 10) % 3 == 0:
            events.append(
                (
                    tick,
                    {
                        "type": "active-speaker",
                        "personId": active.person_id if active else None,
                        "at": round(tick, 2),
                        "confidence": 0.9 if active else 0.0,
                    },
                )
            )

        if active and round(tick * 10) % 2 == 0:
            position = next(frame["mapPosition"] for frame in frames if frame["id"] == active.person_id)
            heat.deposit(active.person_id, position, 0.2, max(0.0, rms))
            last_map = (tick, {"type": "map", "at": round(tick, 2), "hexes": heat.snapshot()})
            events.append(last_map)

        if abs(tick - round(tick)) < 1e-9:
            elapsed = {person["id"]: 0.0 for person in people}
            for item in SCRIPT:
                overlap = max(0.0, min(tick, item.end) - item.start)
                elapsed[item.person_id] = elapsed.get(item.person_id, 0.0) + overlap
            total = sum(elapsed.values())
            open_questions = _questions(tick)
            events.append(
                (
                    tick,
                    {
                        "type": "stats",
                        "at": round(tick, 2),
                        "talkShares": [
                            {
                                "personId": person_id,
                                "seconds": round(seconds, 1),
                                "share": round(seconds / total, 3) if total else 0.0,
                            }
                            for person_id, seconds in elapsed.items()
                        ],
                        "openQuestions": open_questions,
                        "overdueQuestions": [item for item in open_questions if item.get("overdue")],
                    },
                )
            )
        tick += 0.1

    return sorted(events, key=lambda item: (item[0], item[1]["type"]))


def refined_payload(people: list[Person]) -> dict[str, Any]:
    turns = _turns()
    # Simulate SpeakerKit improving three low/medium-confidence live attributions.
    corrected = 3
    return {
        "type": "refined",
        "refined": {
            "correctedTurns": corrected,
            "totalTurns": len(turns),
            "topics": ["accessibility", "demo plan", "action items"],
            "summary": (
                "The group agreed to lead the demo with the accessibility story: identifying the speaker, "
                "showing name alerts, and keeping caption history available. Lee owns the checklist, Yoav "
                "validates the name alert and large-caption mode, and the team rehearses after the first full run."
            ),
            "actionItems": [
                "Lee: finalize the accessibility checklist and caption colors.",
                "Yoav: test the name alert and large-caption mode before dinner.",
                "Team: rehearse the submission pitch after the first full run.",
                "Lee: send action items after the refine pass.",
            ],
            "turns": turns,
        },
    }


class FakeReplaySession:
    def __init__(self, websocket: Any, speed: float = 2.0) -> None:
        self.websocket = websocket
        self.speed = speed
        self.stop_event = asyncio.Event()
        self.refined_sent = False
        self.people = [person.copy() for person in DEFAULT_PEOPLE]

    async def send(self, message: dict[str, Any]) -> None:
        await self.websocket.send_text(json.dumps(message))

    async def run(self, people_json: str | None = None) -> None:
        if people_json:
            try:
                parsed = json.loads(people_json)
                if isinstance(parsed, list) and parsed:
                    self.people = parsed
            except json.JSONDecodeError:
                pass
        await self.send({"type": "replay", "session": SESSION_NAME, "videoUrl": None, "speed": self.speed})
        last_time = 0.0
        for at, message in build_events(self.people):
            if self.stop_event.is_set():
                break
            delay = max(0.0, (at - last_time) / self.speed)
            if delay:
                await asyncio.sleep(delay)
            last_time = at
            if self.stop_event.is_set():
                break
            await self.send(message)
        await self.send_refined()

    async def send_refined(self) -> None:
        if self.refined_sent:
            return
        self.refined_sent = True
        self.stop_event.set()
        for progress, message in (
            (0.22, "Running SpeakerKit diarization on the full WAV…"),
            (0.54, "Matching voice clusters to enrolled people…"),
            (0.78, "Asking Bonsai for topics, tags, and action items…"),
            (1.0, "Review is ready."),
        ):
            await self.send({"type": "refine-progress", "progress": progress, "message": message})
            await asyncio.sleep(0.18)
        await self.send(refined_payload(self.people))

    def answer(self, question: str) -> dict[str, Any]:
        normalized = question.lower()
        if "checklist" in normalized or "maya" in normalized or "yoav" in normalized:
            text = "Maya asked Yoav to test the name alert and large-caption mode before dinner."
            citations = ["turn_0004"]
        elif "action" in normalized:
            text = "The action items are the accessibility checklist, accessibility checks, pitch rehearsal, and sending the final action list."
            citations = ["turn_0003", "turn_0004", "turn_0007", "turn_0012"]
        elif "demo" in normalized or "pitch" in normalized:
            text = "The demo should lead with the Deaf and hard-of-hearing student story, then show name alerts, speaker-pinned captions, and offline privacy."
            citations = ["turn_0006", "turn_0010"]
        else:
            text = "The meeting focused on an offline accessibility-first live caption map, the demo story, and each person's next action."
            citations = ["turn_0001", "turn_0010", "turn_0012"]
        return {"type": "answer", "answer": {"question": question, "text": text, "citedTurnIds": citations}}
