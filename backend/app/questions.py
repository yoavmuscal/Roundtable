"""Code-owned open-question and talk-share logic (not delegated to Bonsai)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Turn

QUESTION_START = re.compile(
    r"^\s*(who|what|when|where|why|how|which|whose|can|could|should|would|do|does|did|is|are|was|were|will|"
    r"have|has|may|might|shall|any|anyone|anybody|thoughts|tell me|explain|describe|wonder)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class OpenQuestion:
    turn_id: str
    speaker_id: str | None
    text: str
    asked_at: float

    def as_dict(self, now_s: float, overdue_after_s: float = 60.0) -> dict[str, object]:
        age = max(0.0, now_s - self.asked_at)
        return {
            "turnId": self.turn_id,
            "speakerId": self.speaker_id,
            "text": self.text,
            "askedAt": self.asked_at,
            "ageS": age,
            "overdue": age >= overdue_after_s,
        }


def is_question(text: str) -> bool:
    stripped = text.strip()
    return stripped.endswith("?") or bool(QUESTION_START.search(stripped))


class OpenQuestionTracker:
    def __init__(self, overdue_after_s: float = 60.0) -> None:
        self.overdue_after_s = overdue_after_s
        self.open: list[OpenQuestion] = []
        self.answered: list[tuple[str, str]] = []

    def process_turn(self, turn: Turn) -> list[str]:
        tags: list[str] = []
        if is_question(turn.text):
            self.open.append(OpenQuestion(turn.id, turn.speaker_id, turn.text, turn.end))
            tags.append("question")
            return tags
        # A later non-question from another participant replies to the oldest open question.
        for index, question in enumerate(self.open):
            if question.speaker_id != turn.speaker_id:
                answered = self.open.pop(index)
                self.answered.append((answered.turn_id, turn.id))
                tags.append("answer")
                break
        return tags

    def snapshot(self, now_s: float) -> dict[str, object]:
        questions = [question.as_dict(now_s, self.overdue_after_s) for question in self.open]
        return {
            "open": questions,
            "openCount": len(questions),
            "overdueCount": sum(1 for question in questions if question["overdue"]),
            "replies": [
                {"questionTurnId": question_id, "replyTurnId": reply_id}
                for question_id, reply_id in self.answered
            ],
        }


def talk_shares(turns: list[Turn]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for turn in turns:
        if turn.speaker_id is None or turn.partial:
            continue
        totals[turn.speaker_id] = totals.get(turn.speaker_id, 0.0) + max(0.0, turn.end - turn.start)
    total = sum(totals.values())
    if total <= 0.0:
        return {}
    return {person: value / total for person, value in sorted(totals.items())}
