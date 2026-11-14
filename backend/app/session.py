"""Backend session engine shared by live mode and simulation mode."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .accessibility import NameAlert
from .bonsai import ANSWER_SCHEMA, SUMMARY_SCHEMA, BonsaiWorker
from .calibration import Calibration
from .contract import CONTRACT_VERSION, SPEAKERS, turn_id
from .fusion import ActiveSpeakerGate, SpeakerFusion
from .geometry import Point
from .heat import HeatMap
from .hexmap import HexGrid
from .models import FaceObservation, Turn
from .questions import OpenQuestionTracker, talk_shares
from .tracking import PersonTracker
from .transcribe import StreamingTranscriptParser, TranscriptTurnBuilder


class SessionRecorder:
    def __init__(self, session_dir: Path | None) -> None:
        self.session_dir = session_dir
        self.events_path: Path | None = None
        self.anchor_rows: list[dict[str, Any]] = []
        if session_dir is not None:
            session_dir.mkdir(parents=True, exist_ok=True)
            self.events_path = session_dir / "events.jsonl"
            self.events_path.write_text("", encoding="utf-8")

    def record(self, message: dict[str, Any]) -> None:
        if self.events_path is None:
            return
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message, separators=(",", ":")) + "\n")

    def record_anchor(self, time_s: float, people_frame: list[dict[str, Any]]) -> None:
        self.anchor_rows.append(
            {
                "time": round(time_s, 3),
                "anchors": {
                    str(person.get("id")): person.get("captionAnchor")
                    for person in people_frame
                },
            }
        )

    def write_anchors(self) -> None:
        if self.session_dir is not None:
            (self.session_dir / "anchors.jsonl").write_text(
                "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in self.anchor_rows),
                encoding="utf-8",
            )

    def write_metadata(self, metadata: dict[str, Any]) -> None:
        if self.session_dir is not None:
            (self.session_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    def write_turns(self, filename: str, turns: list[Turn]) -> None:
        if self.session_dir is not None:
            (self.session_dir / filename).write_text(
                "".join(json.dumps(turn.as_dict(), separators=(",", ":")) + "\n" for turn in turns),
                encoding="utf-8",
            )


@dataclass
class SessionEngine:
    session_dir: Path | None = None
    bonsai: BonsaiWorker | None = None
    calibration: Calibration | None = None
    people: list[dict[str, Any]] = field(default_factory=lambda: [dict(item) for item in SPEAKERS])
    thresholds: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.recorder = SessionRecorder(self.session_dir)
        self.started_wall = time.time()
        self.recording_offsets = {"audioS": 0.0, "videoS": 0.0}
        self.tracker = PersonTracker(thresholds=self.thresholds)
        self.fusion = SpeakerFusion(self.thresholds)
        self.active_gate = ActiveSpeakerGate()
        self.questions = OpenQuestionTracker()
        self.name_alerts = NameAlert()
        self.transcript = StreamingTranscriptParser()
        self.turn_builder = TranscriptTurnBuilder()
        self.turns: list[Turn] = []
        self.heat: HeatMap | None = None
        self.phase = "setup"
        self.last_rms = 0.0
        self.last_heat_deposit = -1.0
        self.active_speaker: str | None = None
        self.off_camera = False
        self.started_monotonic = time.monotonic()

    def set_calibration(self, calibration: Calibration) -> dict[str, Any]:
        self.calibration = calibration
        self.tracker.seat_mapper = lambda shoulder: calibration.project_seat(shoulder)
        self.heat = HeatMap(HexGrid(calibration.table_size.width_m, calibration.table_size.height_m))
        message = self._message(0.0, "calibration_result", **calibration.result())
        self.recorder.record(message)
        return message

    def enroll_person(self, name: str, aliases: list[str] | None = None) -> dict[str, Any]:
        person_index = min(self.tracker.expected_people, 3)
        person_id = f"p{person_index + 1}"
        self.tracker.expect_person()
        self.name_alerts.set_names(person_id, name, aliases)
        if person_index < len(self.people):
            self.people[person_index] = {**self.people[person_index], "name": name, "aliases": aliases or []}
        message = self._message(self.clock(), "people", people=self.people)
        self.recorder.record(message)
        return message

    def start(self) -> list[dict[str, Any]]:
        self.phase = "live"
        self.started_monotonic = time.monotonic()
        messages = [
            self._message(0.0, "phase", phase="live"),
            self._message(0.0, "people", people=self.people),
        ]
        if self.calibration:
            messages.append(self._message(0.0, "calibration_result", **self.calibration.result()))
        for message in messages:
            self.recorder.record(message)
        return messages

    def handle_level(self, time_s: float, rms: float, peak: float | None = None) -> dict[str, Any]:
        self.last_rms = rms
        message = self._message(time_s, "level", rms=rms, peak=peak if peak is not None else rms)
        self.recorder.record(message)
        return message

    def handle_faces(self, time_s: float, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        observations = [FaceObservation.from_dict(payload) for payload in payloads]
        frame = self.tracker.update(time_s, observations)
        self.recorder.record_anchor(time_s, frame)
        for track in self.tracker.tracks.values():
            self.fusion.add_sample(time_s, track.id, track.observation.mouth_score)
        proposed = self._strongest_visible_speaker(time_s)
        active = self.active_gate.update(time_s, proposed, self.last_rms)
        messages = [self._message(time_s, "people_frame", people=frame)]
        if active != self.active_speaker:
            self.active_speaker = active
            self.off_camera = self.last_rms >= self.active_gate.rms_floor and active is None
            messages.append(
                self._message(
                    time_s,
                    "active_speaker",
                    personId=active,
                    offCamera=self.off_camera,
                )
            )
        if active and self.heat and time_s - self.last_heat_deposit >= 0.2:
            track = self.tracker.tracks.get(active)
            if track and track.seat_position:
                self.heat.deposit(time_s, active, track.seat_position, 0.2, min(1.0, self.last_rms / 0.055))
                self.last_heat_deposit = time_s
                messages.append(
                    self._message(
                        time_s,
                        "map",
                        mode="all",
                        hexes=self.heat.frame(time_s, "all"),
                        camera={"position": {"x": self.calibration.table_size.width_m / 2, "y": self.calibration.table_size.height_m + 0.8} if self.calibration else None},
                    )
                )
        for message in messages:
            self.recorder.record(message)
        return messages

    def handle_transcript_snapshot(
        self,
        time_s: float,
        text: str,
        speaker_hint: str | None = None,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if (
            speaker_hint is not None
            and self.turn_builder.current_speaker is not None
            and speaker_hint != self.turn_builder.current_speaker
            and self.transcript.partial_words
        ):
            commit_time = self.transcript.last_update if self.transcript.last_update is not None else time_s
            commit = self.transcript.flush(time_s)
            if commit:
                completed_by_gap = self.turn_builder.add_words(
                    commit.words,
                    commit_time,
                    self.turn_builder.current_speaker,
                    self.turn_builder.confidence,
                )
                if completed_by_gap:
                    messages.extend(self._finalize_turn(completed_by_gap))
            completed = self.turn_builder.end_turn(time_s)
            if completed:
                messages.extend(self._finalize_turn(completed))
        commits = self.transcript.feed_snapshot(text, time_s)
        messages.extend(self._commits_to_messages(commits, time_s, speaker_hint))
        for message in messages:
            self.recorder.record(message)
        return messages

    def handle_transcript_chunk(self, chunk: bytes | str, time_s: float) -> list[dict[str, Any]]:
        commits = self.transcript.feed_chunk(chunk, time_s)
        messages = self._commits_to_messages(commits, time_s, None)
        for message in messages:
            self.recorder.record(message)
        return messages

    def _commits_to_messages(self, commits: list[Any], time_s: float, speaker_hint: str | None) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for commit in commits:
            start = self.turn_builder.current_start if self.turn_builder.current_start is not None else max(0.0, time_s - 0.2)
            attribution = self.fusion.attribute(start, time_s)
            speaker = speaker_hint or attribution.speaker_id
            completed = self.turn_builder.add_words(commit.words, time_s, speaker, attribution.confidence)
            if completed is not None:
                messages.extend(self._finalize_turn(completed))
            if self.turn_builder.current_words:
                current_id = turn_id(self.turn_builder.sequence + 1)
                messages.append(
                    self._message(
                        time_s,
                        "caption",
                        turnId=current_id,
                        speakerId=self.turn_builder.current_speaker,
                        text=" ".join(self.turn_builder.current_words),
                        start=self.turn_builder.current_start,
                        end=time_s,
                        partial=True,
                        confidence=self.turn_builder.confidence,
                    )
                )
        return messages

    def flush_transcript(self, time_s: float) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        commit_time = self.transcript.last_update if self.transcript.last_update is not None else time_s
        commit = self.transcript.flush_due(time_s)
        if commit:
            start = self.turn_builder.current_start if self.turn_builder.current_start is not None else commit_time
            attribution = self.fusion.attribute(start, commit_time)
            completed = self.turn_builder.add_words(commit.words, commit_time, attribution.speaker_id, attribution.confidence)
            if completed:
                messages.extend(self._finalize_turn(completed))
        completed = self.turn_builder.end_turn(time_s)
        if completed:
            messages.extend(self._finalize_turn(completed))
        for message in messages:
            self.recorder.record(message)
        return messages

    def stats(self, time_s: float) -> dict[str, Any]:
        return self._message(
            time_s,
            "stats",
            talkShares=talk_shares(self.turns),
            questions=self.questions.snapshot(time_s),
        )

    async def ask(self, text: str, timeout_s: float = 8.0) -> dict[str, Any]:
        if self.bonsai is None:
            cited = [turn.id for turn in self.turns[-2:]]
            return self._message(self.clock(), "answer", text="Bonsai is unavailable; showing the most recent relevant turns.", citedTurnIds=cited)
        result = await self.bonsai.submit(
            "ask",
            {"question": text, "turns": [turn.as_dict() for turn in self.turns]},
            ANSWER_SCHEMA,
            timeout_s,
        )
        return self._message(self.clock(), "answer", text=result["text"], citedTurnIds=result["citedTurnIds"])

    async def summarize(self, timeout_s: float = 30.0) -> dict[str, Any]:
        if self.bonsai is None:
            return {"summary": "Bonsai unavailable.", "topics": [], "actionItems": [], "perPerson": []}
        return await self.bonsai.submit(
            "summary",
            {"turns": [turn.as_dict() for turn in self.turns]},
            SUMMARY_SCHEMA,
            timeout_s,
        )

    def stop(self, at_time: float | None = None) -> list[dict[str, Any]]:
        stop_time = self.clock() if at_time is None else at_time
        self.phase = "refine"
        messages = self.flush_transcript(stop_time)
        messages.append(self._message(stop_time, "phase", phase="refine"))
        for message in messages:
            self.recorder.record(message)
        self.recorder.write_turns("live_transcript.jsonl", self.turns)
        self.recorder.write_anchors()
        self.recorder.write_metadata(
            {
                "name": self.session_dir.name if self.session_dir else "live-session",
                "startedAtUnix": self.started_wall,
                "durationS": stop_time,
                "people": self.people,
                "calibration": self.calibration.result() if self.calibration else None,
                "recordingOffsets": self.recording_offsets,
                "audioFile": "audio.wav",
                "videoFile": "video.webm",
                "anchorTrackFile": "anchors.jsonl",
            }
        )
        return messages

    def clock(self) -> float:
        return time.monotonic() - self.started_monotonic

    def _strongest_visible_speaker(self, time_s: float) -> str | None:
        best: tuple[float, str] | None = None
        for track in self.tracker.tracks.values():
            if track.state == "away":
                continue
            score = track.observation.mouth_score
            if best is None or score > best[0]:
                best = (score, track.id)
        return best[1] if best and best[0] >= 0.25 else None

    def _finalize_turn(self, turn: Turn) -> list[dict[str, Any]]:
        self.turns.append(turn)
        tags = self.questions.process_turn(turn)
        turn.tags.extend(tags)
        alert = self.name_alerts.check_turn(turn.id, turn.text)
        caption = self._message(
            turn.end,
            "caption",
            turnId=turn.id,
            speakerId=turn.speaker_id,
            text=turn.text,
            start=turn.start,
            end=turn.end,
            partial=False,
            confidence=turn.confidence,
            tags=turn.tags,
            nameAlert=alert,
        )
        messages = [caption, self.stats(turn.end)]
        if tags:
            messages.append(self._message(turn.end, "tags", turnId=turn.id, tags=tags, repliesTo=None, actionOwner=None))
        return messages

    @staticmethod
    def _message(time_s: float, message_type: str, **payload: Any) -> dict[str, Any]:
        return {"type": message_type, "version": CONTRACT_VERSION, "time": round(time_s, 3), **payload}
