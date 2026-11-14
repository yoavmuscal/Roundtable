"""Backend session engine shared by live mode and simulation mode."""

from __future__ import annotations

import difflib
import json
import re
import time
from dataclasses import dataclass, field
from itertools import permutations
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

INTRO_PATTERNS = (
    re.compile(r"(?:^|\b)(?:hi|hey|hello)?[,\s]*(?:i'm|i\s+am|im|my\s+name\s+is|my\s+name's|this\s+is)\s+([a-zA-Z'-]+)(?:\s+([a-zA-Z'-]+))?", re.IGNORECASE),
    re.compile(r"(?:^|\b)([a-zA-Z'-]+)\s+(?:here|speaking)(?:\b|$)", re.IGNORECASE),
)
NON_NAME_WORDS = frozenset({
    "talking", "speaking", "going", "saying", "trying", "asking", "ready", "good",
    "fine", "great", "here", "not", "just", "sure", "okay", "ok", "doing", "looking",
    "testing", "working", "listening", "waiting", "back", "done", "almost", "really",
    "very", "so", "a", "an", "the", "that", "this", "it", "one", "in", "on", "at",
    "still", "only", "also", "happy", "glad", "sorry", "thinking", "wondering",
})


def _clean_alpha(value: str) -> str:
    return re.sub(r"[^a-z]", "", value.lower())


def match_self_intro(text: str, people: list[dict[str, Any]]) -> str | None:
    """Detect when a speaker introduces themselves (e.g. 'I'm Yoav', 'My name is Cello').

    Uses fuzzy matching so Whisper splits like 'I'm your av' still match 'Yoav'.
    """
    if not text or not people:
        return None
    candidates: list[str] = []
    for pattern in INTRO_PATTERNS:
        for match in pattern.finditer(text):
            groups = [g for g in match.groups() if g]
            if not groups:
                continue
            first = _clean_alpha(groups[0])
            if first and first not in NON_NAME_WORDS and first != "your":
                candidates.append(first)
            if len(groups) >= 2:
                second = _clean_alpha(groups[1])
                # Allow 2-word phonetic splits like "your av" -> "yourav" for "Yoav",
                # as long as the second token isn't an everyday verb/filler.
                if first and second and second not in NON_NAME_WORDS and len(second) <= 5:
                    candidates.append(first + second)
    if not candidates:
        return None

    best_person: str | None = None
    best_score = 0.0
    second_score = 0.0
    for cand in candidates:
        scores_by_person: dict[str, float] = {}
        for person in people:
            pid = str(person["id"])
            raw_names = [str(person.get("name", "")), *(str(a) for a in person.get("aliases", []))]
            person_best = 0.0
            for raw in raw_names:
                alias = _clean_alpha(raw)
                if not alias:
                    continue
                if cand == alias:
                    person_best = 1.0
                    break
                if len(alias) >= 3 and len(cand) >= 3:
                    ratio = difflib.SequenceMatcher(None, cand, alias).ratio()
                    person_best = max(person_best, ratio)
            scores_by_person[pid] = person_best
        ranked = sorted(scores_by_person.items(), key=lambda item: item[1], reverse=True)
        if not ranked:
            continue
        top_pid, top_val = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
        if top_val >= 0.72 and top_val - runner_up >= 0.18 and top_val > best_score:
            best_person = top_pid
            best_score = top_val
            second_score = runner_up
    return best_person if best_score >= 0.72 and best_score - second_score >= 0.18 else None


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
        self.enrolled_face_x: dict[str, float] = {}
        self.self_intro_locked: set[str] = set()
        self._face_samples: list[tuple[float, str, float, float]] = []
        self._last_track_count = 0
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

    def _swap_tracks(self, a: str, b: str) -> None:
        if a == b:
            return
        self.tracker.relabel(a, b)
        self.fusion.relabel(a, b)
        swap = {a: b, b: a}
        self._face_samples = [
            (t, swap.get(tid, tid), x, m)
            for t, tid, x, m in self._face_samples
        ]

    def record_enrollment(self, person_id: str, time_s: float) -> None:
        """Store the voice sample window and screen seat position for one person.

        Records where on screen the speaking face was during this sample across ALL
        visible tracks (so an earlier track drift cannot block seat assignment).
        """
        if self.enrollment_started_at is not None and time_s > self.enrollment_started_at:
            start = self.enrollment_started_at
            self.enrollment_intervals.setdefault(person_id, []).append((start, time_s))
            by_track: dict[str, list[tuple[float, float]]] = {}
            for sample_t, tid, x, mouth in self._face_samples:
                if start <= sample_t <= time_s:
                    by_track.setdefault(tid, []).append((x, mouth))
            best_tid: str | None = None
            best_mouth = 0.0
            best_x = 0.5
            for tid, pts in by_track.items():
                mean_m = sum(m for _, m in pts) / len(pts)
                if mean_m > best_mouth:
                    best_mouth = mean_m
                    w_sum = sum(max(0.02, m) for _, m in pts)
                    best_x = sum(x * max(0.02, m) for x, m in pts) / w_sum
                    best_tid = tid
            if best_tid is not None and best_mouth >= 0.08:
                self.enrolled_face_x[person_id] = best_x
                self.bound_ids = getattr(self, "bound_ids", set()) | {person_id}
                self.align_enrolled_faces()
            else:
                # Fallback when tests feed mouth samples without full face frames.
                candidates = {
                    tid: score
                    for tid, score in self.fusion.mean_mouth(start, time_s).items()
                    if tid in self.tracker.tracks
                }
                if candidates:
                    best, score = max(candidates.items(), key=lambda item: item[1])
                    if score >= 0.12:
                        track = self.tracker.tracks[best]
                        self.enrolled_face_x[person_id] = track.smoothed.face_box.center.x
                        self.bound_ids = getattr(self, "bound_ids", set()) | {person_id}
                        self.align_enrolled_faces()
        self.enrollment_started_at = time_s

    def align_enrolled_faces(self) -> None:
        """Assign enrolled people 1-to-1 to active face tracks by their enrolled x positions."""
        tracks = list(self.tracker.tracks.values())
        if not tracks:
            return
        enrolled_ids = [str(person["id"]) for person in self.people]
        anchored = [pid for pid in enrolled_ids if pid in self.enrolled_face_x]
        if anchored and len(tracks) >= 1:
            track_ids = [t.id for t in tracks]
            track_x = {t.id: t.smoothed.face_box.center.x for t in tracks}
            target_assignment: dict[str, str] = {}  # person_id -> current track_id
            if len(anchored) <= len(track_ids):
                best_cost = float("inf")
                for chosen_tids in permutations(track_ids, len(anchored)):
                    cost = sum(abs(track_x[tid] - self.enrolled_face_x[pid]) for pid, tid in zip(anchored, chosen_tids))
                    if cost < best_cost:
                        best_cost = cost
                        target_assignment = dict(zip(anchored, chosen_tids))
            else:
                best_cost = float("inf")
                for chosen_pids in permutations(anchored, len(track_ids)):
                    cost = sum(abs(track_x[tid] - self.enrolled_face_x[pid]) for pid, tid in zip(chosen_pids, track_ids))
                    if cost < best_cost:
                        best_cost = cost
                        target_assignment = dict(zip(chosen_pids, track_ids))
            # Track actual object identity across sequential swaps.
            obj_for_person = {pid: self.tracker.tracks[tid] for pid, tid in target_assignment.items() if tid in self.tracker.tracks}
            for pid, track_obj in obj_for_person.items():
                if track_obj.id != pid:
                    self._swap_tracks(track_obj.id, pid)

        bound = set(self.enrolled_face_x.keys()) | getattr(self, "bound_ids", set())
        remaining_people = [pid for pid in enrolled_ids if pid not in bound]
        remaining_tracks = [self.tracker.tracks[tid] for tid in self.tracker.leftmost_first([tid for tid in self.tracker.tracks if tid not in bound])]
        for track_obj, pid in zip(remaining_tracks, remaining_people):
            if track_obj.id != pid:
                self._swap_tracks(track_obj.id, pid)

    def lock_speaker_identity(self, person_id: str, start_s: float, end_s: float) -> list[dict[str, Any]]:
        """A speaker just said their own name ('I'm Yoav'): bind their moving face and voice."""
        enrolled_ids = {str(person["id"]) for person in self.people}
        if person_id not in enrolled_ids:
            return []
        mouths = {
            tid: score
            for tid, score in self.fusion.mean_mouth(max(0.0, start_s - 0.35), end_s + 0.15).items()
            if tid in self.tracker.tracks and self.tracker.tracks[tid].state != "away"
        }
        best_tid: str | None = None
        if mouths:
            cand_tid, cand_score = max(mouths.items(), key=lambda item: item[1])
            if cand_score >= 0.05 or len(mouths) == 1:
                best_tid = cand_tid
        elif len(self.tracker.tracks) == 1:
            best_tid = next(iter(self.tracker.tracks))

        reassigned_msgs: list[dict[str, Any]] = []
        if best_tid is not None and best_tid != person_id:
            other_id = best_tid
            self._swap_tracks(best_tid, person_id)
            if person_id in self.tracker.tracks:
                self.enrolled_face_x[person_id] = self.tracker.tracks[person_id].smoothed.face_box.center.x
            if other_id in self.tracker.tracks and other_id in enrolled_ids:
                self.enrolled_face_x[other_id] = self.tracker.tracks[other_id].smoothed.face_box.center.x
            if self.turn_builder.current_speaker in {person_id, other_id}:
                swap_map = {person_id: other_id, other_id: person_id}
                self.turn_builder.current_speaker = swap_map[self.turn_builder.current_speaker]
        elif person_id in self.tracker.tracks:
            self.enrolled_face_x[person_id] = self.tracker.tracks[person_id].smoothed.face_box.center.x

        self.self_intro_locked.add(person_id)
        self.bound_ids = getattr(self, "bound_ids", set()) | {person_id}
        if end_s - start_s >= 0.6:
            self.enrollment_intervals.setdefault(person_id, []).append((start_s, end_s))
        return reassigned_msgs

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
        """Align enrolled faces by their enrolled positions, then remaining faces left-to-right."""
        self.align_enrolled_faces()

    def enroll_prompt(self, cursor: int) -> dict[str, Any]:
        cursor = max(0, min(cursor, len(self.people) - 1))
        person = self.people[cursor]
        name = person.get("name", person["id"])
        return self._message(
            self.clock(),
            "enroll_prompt",
            personId=person["id"],
            prompt=(
                f"{name}, please read both sentences: "
                f"\u201cHi, I'm {name}, and Roundtable keeps this conversation private.\u201d "
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
        self._face_samples = []
        self._last_track_count = len(self.tracker.tracks)
        self.started_monotonic = new_origin
        self.align_enrolled_faces()
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
        # When a new face enters view (e.g. second speaker sits down right as Live starts),
        # re-align tracks to the enrolled x positions so seats never stay inverted.
        if len(self.tracker.tracks) != self._last_track_count:
            self._last_track_count = len(self.tracker.tracks)
            if self.enrolled_face_x:
                self.align_enrolled_faces()
                frame = [track.as_frame() for track in sorted(self.tracker.tracks.values(), key=lambda item: item.id)]
        self.recorder.record_anchor(time_s, frame)
        cutoff = time_s - 120.0
        for track in self.tracker.tracks.values():
            self.fusion.add_sample(time_s, track.id, track.observation.mouth_score)
            self._face_samples.append(
                (time_s, track.id, track.smoothed.face_box.center.x, track.observation.mouth_score)
            )
        if len(self._face_samples) > 2500:
            self._face_samples = [item for item in self._face_samples if item[0] >= cutoff]
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
        partial_text = " ".join(self.transcript.partial_words)
        intro_speaker = match_self_intro(partial_text, self.people) if self.phase == "live" else None
        if intro_speaker:
            self.lock_speaker_identity(intro_speaker, start, time_s)
        attribution = self.fusion.attribute(max(0.0, start - 0.25), time_s)
        cur_speaker = self.turn_builder.current_speaker
        if intro_speaker:
            speaker = intro_speaker
        elif cur_speaker is not None and self.turn_builder.current_words:
            # Only split away from the current turn's speaker when the new speaker's mouth is clear.
            if attribution.reason == "clear" and attribution.speaker_id is not None:
                speaker = self._named_speaker(attribution.speaker_id, time_s)
            else:
                speaker = cur_speaker
        else:
            speaker = self._named_speaker(attribution.speaker_id, time_s)

        if speaker:
            self.caption_speaker, self.caption_speaker_at = speaker, time_s

        # Never paste Speaker A's committed `current_words` into Speaker B's bubble!
        if self.turn_builder.current_words and cur_speaker is not None and speaker != cur_speaker:
            words = list(self.transcript.partial_words)
            tid = turn_id(self.turn_builder.sequence + 2)
            t_start = start
        else:
            words = list(self.turn_builder.current_words) + list(self.transcript.partial_words)
            tid = turn_id(self.turn_builder.sequence + 1)
            t_start = self.turn_builder.current_start if self.turn_builder.current_start is not None else start

        return self._message(
            time_s,
            "caption",
            turnId=tid,
            speakerId=speaker,
            text=" ".join(words),
            start=t_start,
            end=time_s,
            partial=True,
            confidence=0.98 if intro_speaker else attribution.confidence,
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
        """Attribute committed words by self-intro or who moved their mouth while spoken."""
        spoken_end = commit.spoken_end if getattr(commit, "spoken_end", None) is not None else fallback_time
        spoken_start = commit.spoken_start if getattr(commit, "spoken_start", None) is not None else None
        if spoken_start is None:
            spoken_start = self.turn_builder.current_start if self.turn_builder.current_start is not None else max(0.0, spoken_end - 0.2)

        intro_speaker = match_self_intro(" ".join(commit.words), self.people) if self.phase == "live" else None
        if intro_speaker:
            self.lock_speaker_identity(intro_speaker, spoken_start, max(spoken_end, spoken_start + 0.8))
            speaker: str | None = intro_speaker
            conf = 0.98
        else:
            # Argmax confirms words seconds after they are said; look at mouths when spoken.
            attribution = self.fusion.attribute(spoken_start, max(spoken_end, spoken_start + 0.3))
            speaker = self._named_speaker(speaker_hint or attribution.speaker_id, spoken_end)
            conf = attribution.confidence

        if speaker:
            self.caption_speaker, self.caption_speaker_at = speaker, max(spoken_end, getattr(self, "caption_speaker_at", -99.0))
        completed = self.turn_builder.add_words(commit.words, spoken_end, speaker, conf)
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
