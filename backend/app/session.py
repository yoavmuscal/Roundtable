"""Backend session engine shared by live mode and simulation mode."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .accessibility import NameAlert
from .bonsai import ANSWER_SCHEMA, SUMMARY_SCHEMA, TAG_SCHEMA, BonsaiWorker
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
    # Three default seats; the UI adds or removes people (1-4) and sends its list back.
    people: list[dict[str, Any]] = field(default_factory=lambda: [dict(item) for item in SPEAKERS[:3]])
    thresholds: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.recorder = SessionRecorder(self.session_dir)
        self.started_wall = time.time()
        self.recording_offsets = {"audioS": 0.0, "videoS": 0.0}
        self.enrollment_intervals: dict[str, list[tuple[float, float]]] = {}
        self.enrollment_started_at: float | None = None
        self.enrollment_armed = False
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

    def use_horizontal_seating(self, seat_offset_m: float = 0.45) -> None:
        """Seat people along the far edge by where they appear left-to-right in the camera.

        Used until the table is calibrated for this camera: projecting through a default
        calibration put laptop-camera users behind the camera and made the map jump.
        """
        if self.calibration is None:
            return
        width = self.calibration.table_size.width_m

        def seat(shoulder: Point) -> Point:
            return Point(min(1.0, max(0.0, shoulder.x)) * width, -seat_offset_m)

        self.tracker.seat_mapper = seat

    def begin_enrollment(self, time_s: float) -> None:
        self.enrollment_started_at = time_s

    def arm_enrollment(self, time_s: float) -> None:
        """Start this person's sample only when they press Begin recording."""
        self.enrollment_started_at = time_s
        self.enrollment_armed = True

    def take_enrollment_sample(self, person_id: str, time_s: float) -> None:
        if not getattr(self, "enrollment_armed", False):
            self.enrollment_started_at = None
            return
        self.record_enrollment(person_id, time_s)
        self.enrollment_armed = False
        self.enrollment_started_at = None

    def record_enrollment(self, person_id: str, time_s: float) -> None:
        """Store the voice sample window for one person and bind their face.

        The face whose mouth moved most while this person read their sentence becomes
        this person, so names on screen follow enrollment instead of detection order.
        """
        if self.enrollment_started_at is not None and time_s > self.enrollment_started_at:
            start = self.enrollment_started_at
            self.enrollment_intervals.setdefault(person_id, []).append((start, time_s))
            bound = getattr(self, "bound_ids", set())
            candidates = {
                track_id: score
                for track_id, score in self.fusion.mean_mouth(start, time_s).items()
                if track_id in self.tracker.tracks and track_id not in (bound - {person_id})
            }
            if candidates:
                best, score = max(candidates.items(), key=lambda item: item[1])
                if score >= 0.15:
                    self.tracker.relabel(best, person_id)
                    self.fusion.relabel(best, person_id)
                    self.bound_ids = bound | {person_id}
        self.enrollment_started_at = time_s

    def enrollment_audio(self, monitor: Any) -> dict[str, bytes]:
        """Each person's enrollment speech from the microphone buffer (for voice ID)."""
        from .audio import pcm_between

        clips: dict[str, bytes] = {}
        for person_id, intervals in self.enrollment_intervals.items():
            start, end = intervals[-1]
            clips[person_id] = pcm_between(monitor, self.started_monotonic + start, self.started_monotonic + end)
        return clips

    def turn_audio(self, monitor: Any, turn_id_: str) -> bytes:
        from .audio import pcm_between

        turn = next((item for item in self.turns if item.id == turn_id_), None)
        if turn is None:
            return b""
        # Argmax shows words ~1 s after they start, so reach back a little.
        return pcm_between(monitor, self.started_monotonic + turn.start - 1.0, self.started_monotonic + turn.end + 0.3)

    def reassign_turn(self, turn_id_: str, person_id: str, confidence: float) -> list[dict[str, Any]]:
        """Voice ID disagreed with the face-based guess: move the finished caption."""
        turn = next((item for item in self.turns if item.id == turn_id_), None)
        if turn is None or turn.speaker_id == person_id:
            return []
        turn.speaker_id = person_id
        turn.confidence = max(turn.confidence, confidence)
        caption = self._message(
            turn.end,
            "caption",
            turnId=turn.id,
            speakerId=person_id,
            text=turn.text,
            start=turn.start,
            end=turn.end,
            partial=False,
            confidence=turn.confidence,
            tags=turn.tags,
            voiceId=True,
        )
        self.recorder.record(caption)
        return [caption, self.stats(self.clock())]

    def bind_remaining_left_to_right(self) -> None:
        """People not bound by enrollment take the remaining faces in left-to-right order."""
        bound = getattr(self, "bound_ids", set())
        people = [str(person["id"]) for person in self.people if str(person["id"]) not in bound]
        ordered = [self.tracker.tracks[tid] for tid in self.tracker.leftmost_first([tid for tid in self.tracker.tracks if tid not in bound])]
        for track, person_id in zip(ordered, people):
            current = track.id  # ids change as earlier swaps happen; follow the face itself
            self.tracker.relabel(current, person_id)
            self.fusion.relabel(current, person_id)

    def enroll_prompt(self, cursor: int) -> dict[str, Any]:
        cursor = max(0, min(cursor, len(self.people) - 1))
        person = self.people[cursor]
        return self._message(
            self.clock(),
            "enroll_prompt",
            personId=person["id"],
            prompt=(
                f"{person.get('name', person['id'])}, please read both sentences: "
                "\u201cRoundtable keeps this conversation private.\u201d "
                "\u201cEveryone at the table should be easy to follow.\u201d"
            ),
            index=cursor,
            total=len(self.people),
        )

    def complete_enrollment(self, time_s: float, record_interval: bool = True) -> None:
        person_id = f"p{min(self.tracker.expected_people + 1, 4)}"
        if record_interval and self.enrollment_started_at is not None and time_s > self.enrollment_started_at:
            self.enrollment_intervals.setdefault(person_id, []).append((self.enrollment_started_at, time_s))
        self.enrollment_started_at = time_s

    def set_enrolled_people(self, people: list[dict[str, Any]]) -> None:
        self.people = [dict(person) for person in people[:4]]
        self.tracker.expected_people = len(self.people)
        self.tracker.lock_to_expected = True
        self.tracker.allowed_ids = [str(person["id"]) for person in self.people]
        self.bound_ids = {person_id for person_id in getattr(self, "bound_ids", set()) if person_id in self.tracker.allowed_ids}
        # Drop tracks of people who were removed from the list.
        for track_id in [tid for tid in self.tracker.tracks if tid not in {str(person["id"]) for person in self.people}]:
            del self.tracker.tracks[track_id]
        for person in self.people:
            self.name_alerts.set_names(
                str(person["id"]),
                str(person.get("name", person["id"])),
                [str(alias) for alias in person.get("aliases", [])],
            )

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
        new_origin = time.monotonic()
        # Enrollment windows were timed on the pre-session clock; move them onto the
        # session clock (they become negative) so they line up with the WAV offset.
        shift = self.started_monotonic - new_origin
        self.enrollment_intervals = {
            person: [(start + shift, end + shift) for start, end in intervals]
            for person, intervals in self.enrollment_intervals.items()
        }
        if self.enrollment_started_at is not None:
            self.enrollment_started_at += shift
        self.started_monotonic = new_origin
        self.bind_remaining_left_to_right()
        # Enrollment speech is not part of the meeting: start the transcript fresh.
        self.turns = []
        self.turn_builder = TranscriptTurnBuilder()
        self.transcript = StreamingTranscriptParser()
        self.transcript.baseline_pending = True
        self.questions = OpenQuestionTracker()
        if self.calibration is not None:
            self.heat = HeatMap(HexGrid(self.calibration.table_size.width_m, self.calibration.table_size.height_m))
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
        self.fusion.add_level(time_s, rms)
        message = self._message(time_s, "level", rms=rms, peak=peak if peak is not None else rms)
        self.recorder.record(message)
        return message

    def handle_faces(self, time_s: float, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        observations = [FaceObservation.from_dict(payload) for payload in payloads]
        frame = self.tracker.update(time_s, observations)
        self.recorder.record_anchor(time_s, frame)
        for track in self.tracker.tracks.values():
            self.fusion.add_sample(time_s, track.id, track.observation.mouth_score)
        # While someone is being captioned, the glow and the map follow the caption's speaker,
        # so bubble, glow and hex map always agree; otherwise use the most active mouth.
        caption_speaker = getattr(self, "caption_speaker", None)
        caption_recent = time_s - getattr(self, "caption_speaker_at", -99.0) <= 1.5
        proposed = caption_speaker if caption_speaker and caption_recent else self._strongest_visible_speaker(time_s)
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
        before = self.transcript.partial_words
        commits = self.transcript.feed_chunk(chunk, time_s)
        messages = self._commits_to_messages(commits, time_s, None)
        partial = self.transcript.partial_words
        if partial and (partial != before or commits):
            messages.append(self._live_partial_caption(time_s))
        for message in messages:
            self.recorder.record(message)
        return messages

    def _commits_to_messages(self, commits: list[Any], time_s: float, speaker_hint: str | None) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for commit in commits:
            messages.extend(self._add_commit(commit, time_s, speaker_hint))
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

    def _live_partial_caption(self, time_s: float) -> dict[str, Any]:
        """Show still-changing words immediately so the bubble appears while someone talks."""
        speech_start = getattr(self.transcript, "_speech_start", None)
        start = speech_start if speech_start is not None else (self.turn_builder.current_start if self.turn_builder.current_start is not None else max(0.0, time_s - 1.2))
        attribution = self.fusion.attribute(max(0.0, start - 0.25), time_s)
        # Let a clear mouth/voice match override an earlier tentative guess on the open turn.
        if attribution.reason == "clear" and attribution.speaker_id is not None:
            raw_speaker = attribution.speaker_id
        else:
            raw_speaker = attribution.speaker_id or self.turn_builder.current_speaker
        speaker = self._named_speaker(raw_speaker, time_s)
        if speaker:
            self.caption_speaker, self.caption_speaker_at = speaker, time_s
        words = list(self.turn_builder.current_words) + list(self.transcript.partial_words)
        return self._message(
            time_s,
            "caption",
            turnId=turn_id(self.turn_builder.sequence + 1),
            speakerId=speaker,
            text=" ".join(words),
            start=self.turn_builder.current_start if self.turn_builder.current_start is not None else start,
            end=time_s,
            partial=True,
            confidence=attribution.confidence,
        )

    def flush_transcript(self, time_s: float) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        commit_time = self.transcript.last_update if self.transcript.last_update is not None else time_s
        commit = self.transcript.flush_due(time_s)
        if commit:
            start = self.turn_builder.current_start if self.turn_builder.current_start is not None else commit_time
            attribution = self.fusion.attribute(start, commit_time)
            speaker = self._named_speaker(attribution.speaker_id, commit_time)
            completed = self.turn_builder.add_words(commit.words, commit_time, speaker, attribution.confidence)
            if completed:
                messages.extend(self._finalize_turn(completed))
        completed = self.turn_builder.end_turn(time_s)
        if completed:
            messages.extend(self._finalize_turn(completed))
        for message in messages:
            self.recorder.record(message)
        return messages

    def _add_commit(self, commit: Any, fallback_time: float, speaker_hint: str | None) -> list[dict[str, Any]]:
        """Attribute committed words by who was moving their mouth while they were spoken."""
        spoken_end = commit.spoken_end if getattr(commit, "spoken_end", None) is not None else fallback_time
        spoken_start = commit.spoken_start if getattr(commit, "spoken_start", None) is not None else None
        if spoken_start is None:
            spoken_start = self.turn_builder.current_start if self.turn_builder.current_start is not None else max(0.0, spoken_end - 0.2)
        # Argmax confirms words seconds after they are said; looking at mouths at confirmation
        # time put every caption on whoever happened to be talking then.
        attribution = self.fusion.attribute(spoken_start, max(spoken_end, spoken_start + 0.3))
        speaker = self._named_speaker(speaker_hint or attribution.speaker_id, spoken_end)
        if speaker:
            self.caption_speaker, self.caption_speaker_at = speaker, max(spoken_end, getattr(self, "caption_speaker_at", -99.0))
        completed = self.turn_builder.add_words(commit.words, spoken_end, speaker, attribution.confidence)
        if self.turn_builder.current_start is not None and len(self.turn_builder.current_words) == len(commit.words):
            self.turn_builder.current_start = min(self.turn_builder.current_start, spoken_start)
        return self._finalize_turn(completed) if completed is not None else []

    def tick(self, time_s: float) -> list[dict[str, Any]]:
        """Live-mode heartbeat: flush partial words after silence and close quiet turns."""
        messages: list[dict[str, Any]] = []
        commit_time = self.transcript.last_update if self.transcript.last_update is not None else time_s
        commit = self.transcript.flush_due(time_s)
        if commit:
            messages.extend(self._add_commit(commit, commit_time, None))
        last_word = self.turn_builder.last_word_time
        if last_word is not None and time_s - last_word > self.turn_builder.gap_s and not self.transcript.partial_words:
            completed = self.turn_builder.end_turn(last_word)
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
        if not self.turns:
            # A small model invents a meeting when given none; answer honestly instead.
            return self._message(self.clock(), "answer", question=text, text="Nothing has been said yet, so there is nothing to answer from.", citedTurnIds=[])
        if self.bonsai is None:
            cited = [turn.id for turn in self.turns[-2:]]
            return self._message(self.clock(), "answer", question=text, text="Bonsai is unavailable; showing the most recent relevant turns.", citedTurnIds=cited)
        result = await self.bonsai.submit(
            "ask",
            {"question": text, "turns": [_brief(turn) for turn in self.turns[-80:]], "names": self._names()},
            ANSWER_SCHEMA,
            timeout_s,
        )
        known = {turn.id for turn in self.turns}
        cited = [turn_id for turn_id in result.get("citedTurnIds", []) if turn_id in known]
        return self._message(self.clock(), "answer", question=text, text=result["text"], citedTurnIds=cited)

    async def tag_turns(self, turns: list[Turn], timeout_s: float = 4.0) -> list[Turn]:
        if self.bonsai is None:
            return turns
        tagged: list[Turn] = []
        for turn in turns:
            try:
                result = await self.bonsai.submit(
                    "tag",
                    {"turnId": turn.id, "text": turn.text, "speakerId": turn.speaker_id},
                    TAG_SCHEMA,
                    timeout_s,
                )
                # Keep the code-detected question/answer tags and add Bonsai's.
                turn.tags = list(dict.fromkeys([*turn.tags, *(str(tag) for tag in result.get("tags", []))]))
            except Exception:
                # Refine remains useful when an individual tag job times out.
                pass
            tagged.append(turn)
        return tagged

    async def summarize(self, timeout_s: float = 30.0) -> dict[str, Any]:
        if not self.turns:
            return {"summary": "No speech was captured in this session.", "topics": [], "actionItems": [], "perPerson": []}
        if self.bonsai is None:
            return {"summary": "Bonsai unavailable.", "topics": [], "actionItems": [], "perPerson": []}
        return await self.bonsai.submit(
            "summary",
            {"turns": [_brief(turn) for turn in self.turns[-60:]], "names": self._names()},
            SUMMARY_SCHEMA,
            timeout_s,
        )

    def stop(self, at_time: float | None = None) -> list[dict[str, Any]]:
        stop_time = self.clock() if at_time is None else at_time
        self.phase = "refine"
        # flush_transcript() already records its own messages; only record the
        # phase transition appended here to avoid duplicate recording.
        messages = self.flush_transcript(stop_time)
        phase_message = self._message(stop_time, "phase", phase="refine")
        self.recorder.record(phase_message)
        messages.append(phase_message)
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

    def _names(self) -> dict[str, str]:
        return {str(person["id"]): str(person.get("name", person["id"])) for person in self.people}

    def clock(self) -> float:
        return time.monotonic() - self.started_monotonic

    def _strongest_visible_speaker(self, time_s: float) -> str | None:
        """Pick the face whose mouth is moving with the mic, not just the biggest jaw."""
        away = {track.id for track in self.tracker.tracks.values() if track.state == "away"}
        scores = {
            person: score
            for person, score in self.fusion.fused_scores(max(0.0, time_s - 0.5), time_s).items()
            if person not in away and person in self.tracker.tracks
        }
        if not scores:
            return None
        best_id, best_score = max(scores.items(), key=lambda item: item[1])
        return best_id if best_score >= 0.08 else None

    def steer_open_speaker(self, person_id: str, time_s: float, coverage: float) -> list[dict[str, Any]]:
        """Apply a diarization hit to the sentence still being spoken."""
        self.fusion.add_voice(max(0.0, time_s - 1.75), person_id, coverage)
        if self.phase != "live" or not self.turn_builder.current_words or coverage < 0.55:
            return []
        enrolled = {str(person["id"]) for person in self.people}
        if person_id not in enrolled:
            return []
        self.turn_builder.current_speaker = person_id
        self.caption_speaker, self.caption_speaker_at = person_id, time_s
        return [self._live_partial_caption(time_s)]

    def _named_speaker(self, speaker: str | None, time_s: float) -> str | None:
        """Enrolled sessions always name a person. Unknown is not a seat."""
        enrolled = [str(person["id"]) for person in self.people]
        if not enrolled:
            return speaker
        if speaker in enrolled:
            return speaker
        visible = self._strongest_visible_speaker(time_s)
        if visible in enrolled:
            return visible
        if self.active_speaker in enrolled:
            return self.active_speaker
        recent = [hint for hint in self.fusion.voice_hints if time_s - 5.0 <= hint.time <= time_s + 0.4]
        if recent and recent[-1].person_id in enrolled:
            return recent[-1].person_id
        mouth_recent = {
            pid: val
            for pid, val in self.fusion.mean_mouth(max(0.0, time_s - 2.0), time_s).items()
            if pid in enrolled
        }
        if mouth_recent:
            best_pid, best_val = max(mouth_recent.items(), key=lambda item: item[1])
            if best_val >= 0.03:
                return best_pid
        if self.fusion.previous_speaker in enrolled:
            return self.fusion.previous_speaker
        present = [
            track for track in self.tracker.tracks.values()
            if track.id in enrolled and track.state != "away"
        ]
        if present:
            return max(present, key=lambda track: track.observation.mouth_score).id
        return enrolled[0]

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


def _brief(turn: Turn) -> dict[str, Any]:
    """What Bonsai needs per turn; prefill on the 8 GB Mac runs ~170 tokens/s, so keep it short."""
    text = turn.text if len(turn.text) <= 280 else turn.text[:277] + "..."
    return {"id": turn.id, "speakerId": turn.speaker_id, "text": text}
