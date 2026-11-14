"""Generate the 90-second synthetic Roundtable session used by replay and tests."""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .accessibility import NameAlert
from .calibration import Calibration, TableSize
from .contract import CONTRACT_VERSION, SPEAKERS, turn_id
from .fusion import ActiveSpeakerGate, SpeakerFusion
from .geometry import Point
from .heat import HeatMap
from .hexmap import HexGrid
from .models import Box, FaceObservation, Turn
from .questions import OpenQuestionTracker, talk_shares
from .tracking import PersonTracker


@dataclass(frozen=True, slots=True)
class FakeTurnSpec:
    start: float
    duration: float
    speaker_index: int
    text: str

    @property
    def end(self) -> float:
        return self.start + self.duration


FAKE_CORNERS = (
    Point(0.22, 0.70),
    Point(0.78, 0.70),
    Point(0.97, 0.98),
    Point(0.03, 0.98),
)
FAKE_TABLE = TableSize(1.8, 0.9)
FAKE_PEOPLE = (
    {"id": "p1", "name": "Yoav", "color": "#8B7CF6", "shape": "circle"},
    {"id": "p2", "name": "Maya", "color": "#2DD4A7", "shape": "square"},
    {"id": "p3", "name": "Lee", "color": "#F5A524", "shape": "diamond"},
)


def scripted_turns() -> list[FakeTurnSpec]:
    specs = [
        (5.0, 0, "Welcome everyone. Let us map what happens in this seminar."),
        (5.0, 1, "I can start with the setup and the accessibility goals."),
        (4.0, 2, "I will watch whether the captions stay attached to the right person."),
        (6.0, 0, "What should we show first in the demo?"),
        (5.0, 1, "Show the live bubbles and the room map first, then the review."),
        (4.0, 2, "Does the map follow someone if they move?"),
        (6.0, 0, "Yes. The tracker keeps identity with position and shirt color."),
        (5.5, 1, "The talk rings should stay close to forty-five, thirty-one, and twenty-five percent."),
        (4.5, 2, "I am moving one seat right now so the marker should follow me."),
        (6.0, 0, "That motion gives us a clear check without any hardware."),
        (5.0, 1, "I will step away briefly and the map should dim my marker."),
        (4.0, 2, "When you return, the shirt histogram should recover your identity."),
        (6.0, 0, "Yoav, can the name alert flash when your name is called?"),
        (4.455, 1, "Yes. It should also highlight that row in caption history."),
        (3.625, 2, "The typed answer card should cite the turns it used."),
        (7.225, 0, "Who can stay after the session to check the final acceptance list?"),
    ]
    output: list[FakeTurnSpec] = []
    start = 0.0
    for index, (duration, speaker, text) in enumerate(specs):
        output.append(FakeTurnSpec(start, duration, speaker, text))
        start += duration + (0.45 if index < len(specs) - 1 else 0.0)
    return output


def person_position(index: int, time_s: float) -> tuple[float, float, bool]:
    x_positions = (0.30, 0.50, 0.70)
    x = x_positions[index]
    if index == 2:
        if 45.0 <= time_s <= 50.0:
            x += 0.10 * (time_s - 45.0) / 5.0
        elif time_s > 50.0:
            x += 0.10
    y = 0.40 + 0.004 * math.sin(time_s * 1.3 + index)
    torso_visible = index != 2
    return x, y, torso_visible


def observation(index: int, time_s: float, active: bool) -> FaceObservation:
    x, y, torso_visible = person_position(index, time_s)
    jitter = 0.0015 * math.sin(time_s * 7.0 + index * 2.0)
    x += jitter
    shoulder_y = y + 0.12
    mouth = 0.68 + 0.12 * math.sin(time_s * 9.0) if active else 0.035
    histogram = [0.0] * 32
    histogram[(0, 8, 16)[index]] = 1.0
    return FaceObservation(
        face_box=Box(x - 0.04, y - 0.04, 0.08, 0.08),
        mouth_score=max(0.0, min(1.0, mouth)),
        jaw_variation=mouth * 0.08,
        shoulder_point=Point(x, shoulder_y),
        chest_point=Point(x, shoulder_y + 0.12),
        head_top_point=Point(x, y - 0.07),
        torso_visible=torso_visible,
        shirt_histogram=tuple(histogram),
    )


def observation_dict(observation_: FaceObservation) -> dict[str, object]:
    return {
        "faceBox": observation_.face_box.as_dict(),
        "mouthScore": observation_.mouth_score,
        "jawVariation": observation_.jaw_variation,
        "shoulderPoint": observation_.shoulder_point.as_dict(),
        "chestPoint": observation_.chest_point.as_dict(),
        "headTopPoint": observation_.head_top_point.as_dict(),
        "torsoVisible": observation_.torso_visible,
        "shirtHistogram": list(observation_.shirt_histogram),
    }


def event(time_s: float, message_type: str, **payload: object) -> dict[str, object]:
    return {"type": message_type, "version": CONTRACT_VERSION, "time": round(time_s, 3), **payload}


def generate_session(output_dir: Path, include_video: bool = True) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "inputs").mkdir(exist_ok=True)
    calibration = Calibration(FAKE_CORNERS, FAKE_TABLE)
    tracker = PersonTracker(
        expected_people=3,
        seat_mapper=lambda shoulder: calibration.project_seat(shoulder),
    )
    fusion = SpeakerFusion()
    active_gate = ActiveSpeakerGate(rms_floor=0.02)
    heat = HeatMap(HexGrid(FAKE_TABLE.width_m, FAKE_TABLE.height_m))
    questions = OpenQuestionTracker()
    name_alerts = NameAlert({"p1": ["Yoav"]})
    turns = scripted_turns()
    live_turns: list[Turn] = []
    events: list[dict[str, object]] = [
        event(0.0, "phase", phase="live"),
        event(0.0, "people", people=FAKE_PEOPLE),
        event(0.0, "calibration_result", **calibration.result()),
    ]
    face_inputs: list[dict[str, object]] = []
    transcript_inputs: list[dict[str, object]] = []
    anchor_rows: list[dict[str, object]] = []
    randomizer = random.Random(17)
    last_active: str | None = None
    correct = 0

    frame_times = [index / 10.0 for index in range(901)]
    for time_s in frame_times:
        active_turn = next((turn for turn in turns if turn.start <= time_s < turn.end), None)
        active_index = active_turn.speaker_index if active_turn else None
        observations = [
            observation(index, time_s, active_index == index)
            for index in range(3)
            if not (index == 1 and 59.0 <= time_s <= 64.0)
        ]
        if time_s > 0.0:
            randomizer.shuffle(observations)
        face_message = event(
            time_s,
            "faces",
            people=[observation_dict(item) for item in observations],
        )
        face_inputs.append(face_message)
        people_frame = tracker.update(time_s, observations)
        events.append(event(time_s, "people_frame", people=people_frame))
        anchor_rows.append(
            {
                "time": round(time_s, 3),
                "anchors": {
                    person["id"]: person["captionAnchor"]
                    for person in people_frame
                },
            }
        )
        for index, item in enumerate((observation(i, time_s, active_index == i) for i in range(3))):
            fusion.add_sample(time_s, f"p{index + 1}", item.mouth_score)
        rms = 0.055 if active_turn else 0.006
        if abs(time_s * 20 - round(time_s * 20)) < 1e-6:
            events.append(event(time_s, "level", rms=rms, peak=rms * 1.3))
        proposed = f"p{active_index + 1}" if active_index is not None else None
        active = active_gate.update(time_s, proposed, rms)
        if active != last_active:
            events.append(event(time_s, "active_speaker", personId=active, confidence=0.9 if active else 0.0))
            last_active = active
        if active_turn and abs(time_s * 5 - round(time_s * 5)) < 1e-6:
            x, _, _ = person_position(active_index, time_s)
            seat = calibration.project_seat(Point(x, 0.52))
            heat.deposit(time_s, f"p{active_index + 1}", seat, 0.2, rms / 0.055)
            events.append(
                event(
                    time_s,
                    "map",
                    mode="all",
                    hexes=heat.frame(time_s, "all"),
                    camera={"position": {"x": 0.9, "y": 1.7}, "fovDegrees": 72},
                )
            )
        if abs(time_s - round(time_s)) < 1e-6:
            events.append(
                event(
                    time_s,
                    "stats",
                    talkShares=talk_shares(live_turns),
                    questions=questions.snapshot(time_s),
                )
            )

    for index, spec in enumerate(turns, start=1):
        speaker_id = f"p{spec.speaker_index + 1}"
        attribution = fusion.attribute(spec.start, spec.end)
        if attribution.speaker_id == speaker_id:
            correct += 1
        turn = Turn(
            id=turn_id(index),
            speaker_id=attribution.speaker_id,
            text=spec.text,
            start=spec.start,
            end=spec.end,
            confidence=attribution.confidence,
        )
        live_turns.append(turn)
        tags = questions.process_turn(turn)
        turn.tags.extend(tags)
        words = spec.text.split()
        cumulative: list[str] = []
        for word_index, word in enumerate(words):
            cumulative.append(word)
            word_time = spec.start + (word_index + 1) * spec.duration / len(words)
            transcript_inputs.append(
                event(word_time, "snapshot", text=" ".join(cumulative), speakerId=speaker_id)
            )
            events.append(
                event(
                    word_time,
                    "caption",
                    turnId=turn.id,
                    speakerId=speaker_id,
                    text=" ".join(cumulative),
                    start=spec.start,
                    end=word_time,
                    partial=True,
                    confidence=attribution.confidence,
                )
            )
        alert = name_alerts.check_turn(turn.id, turn.text)
        events.append(
            event(
                spec.end,
                "caption",
                turnId=turn.id,
                speakerId=turn.speaker_id,
                expectedSpeakerId=speaker_id,
                text=turn.text,
                start=turn.start,
                end=turn.end,
                partial=False,
                confidence=turn.confidence,
                tags=turn.tags,
                nameAlert=alert,
            )
        )
        if tags:
            events.append(event(spec.end, "tags", turnId=turn.id, tags=tags, repliesTo=None, actionOwner=None))

    events.append(
        event(
            84.0,
            "answer",
            text="The demo should show live bubbles and the room map first, followed by the refined review.",
            citedTurnIds=["turn_0004", "turn_0005"],
        )
    )
    events.append(event(90.0, "phase", phase="refine"))
    events.append(event(90.1, "refine_progress", stage="diarize", progress=0.35))
    events.append(event(90.4, "refine_progress", stage="summary", progress=0.8))
    refined_turns = [Turn(turn.id, turn.speaker_id, turn.text, turn.start, turn.end, turn.confidence, tags=turn.tags) for turn in live_turns]
    events.append(
        event(
            90.8,
            "refined",
            changedCount=0,
            totalCount=len(live_turns),
            turns=[turn.as_dict() for turn in refined_turns],
            topics=["accessibility", "live demo", "identity tracking"],
            summary={
                "summary": "The group validated live speaker bubbles, room-map motion, identity recovery, the name alert, and typed cited answers.",
                "perPerson": [
                    {"personId": "p1", "summary": "Led the demo flow and asked the final follow-up question."},
                    {"personId": "p2", "summary": "Covered accessibility behavior and the away/reidentification check."},
                    {"personId": "p3", "summary": "Tested movement, map following, and review citations."},
                ],
                "actionItems": ["Check the final acceptance list after the session."],
            },
        )
    )
    events.append(event(91.0, "phase", phase="review"))
    events.sort(key=lambda item: float(item["time"]))

    _write_jsonl(output_dir / "events.jsonl", events)
    _write_jsonl(output_dir / "inputs" / "faces.jsonl", face_inputs)
    _write_jsonl(output_dir / "inputs" / "transcript_snapshots.jsonl", transcript_inputs)
    _write_jsonl(output_dir / "anchors.jsonl", anchor_rows)
    _write_placeholder_wav(output_dir / "audio.wav")
    _write_jsonl(output_dir / "live_transcript.jsonl", [turn.as_dict() for turn in live_turns])
    _write_jsonl(output_dir / "refined_transcript.jsonl", [turn.as_dict() for turn in refined_turns])
    metadata = {
        "name": "fake-accessibility-session",
        "durationS": 91.0,
        "people": FAKE_PEOPLE,
        "calibration": calibration.result(),
        "recordingOffsets": {"audioS": 0.0, "videoS": 0.0},
        "expectedTalkShares": {"p1": 0.45, "p2": 0.31, "p3": 0.25},
        "actualTalkShares": talk_shares(live_turns),
        "attributionAccuracy": correct / len(turns),
        "eventCount": len(events),
        "videoFile": "silhouette.gif" if include_video else None,
        "audioFile": "audio.wav",
        "anchorTrackFile": "anchors.jsonl",
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    if include_video:
        _write_silhouette_gif(output_dir / "silhouette.gif", frame_times)
    return metadata


def _write_placeholder_wav(path: Path, duration_s: float = 91.0, sample_rate: int = 16_000) -> None:
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        chunk = b"\x00\x00" * sample_rate
        for _ in range(int(duration_s)):
            wav.writeframes(chunk)


def _write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def _write_silhouette_gif(path: Path, frame_times: list[float]) -> None:
    from PIL import Image, ImageDraw

    width, height = 752, 424
    frames = []
    table_points = [(int(point.x * width), int(point.y * height)) for point in FAKE_CORNERS]
    for time_s in frame_times[::2]:  # 5 fps keeps the fixture small.
        image = Image.new("RGB", (width, height), "#0B0E13")
        draw = ImageDraw.Draw(image)
        draw.polygon(table_points, outline="#3A4150", fill="#151A22")
        for index, person in enumerate(FAKE_PEOPLE):
            if index == 1 and 59.0 <= time_s <= 64.0:
                continue
            x, y, torso_visible = person_position(index, time_s)
            px, py = int(x * width), int(y * height)
            color = str(person["color"])
            draw.ellipse((px - 18, py - 18, px + 18, py + 18), fill=color)
            if torso_visible:
                draw.rounded_rectangle((px - 25, py + 20, px + 25, py + 76), radius=14, fill=color)
            draw.text((px - 10, py - 7), f"p{index + 1}", fill="#10141B")
        frames.append(image)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=200, loop=0, optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("sessions/fake"))
    parser.add_argument("--no-video", action="store_true")
    args = parser.parse_args()
    metadata = generate_session(args.output, include_video=not args.no_video)
    print(
        f"generated {metadata['eventCount']} events; "
        f"attribution={metadata['attributionAccuracy']:.0%}; "
        f"talk_shares={json.dumps(metadata['actualTalkShares'], sort_keys=True)}"
    )


if __name__ == "__main__":
    main()
