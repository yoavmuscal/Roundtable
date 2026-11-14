"""Replay browser and transcriber inputs through the real backend pipeline."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from .bonsai import BonsaiWorker
from .calibration import calibration_from_payload
from .session import SessionEngine

Emit = Callable[[dict[str, Any]], Awaitable[None]]


def load_simulation_inputs(session_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    faces_path = session_dir / "inputs" / "faces.jsonl"
    transcript_path = session_dir / "inputs" / "transcript_snapshots.jsonl"
    events_path = session_dir / "events.jsonl"
    for path, source in ((faces_path, "faces"), (transcript_path, "snapshot")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                row["_source"] = source
                rows.append(row)
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("type") == "level":
                row["_source"] = "level"
                rows.append(row)
    rows.sort(key=lambda row: (float(row.get("time", 0.0)), 0 if row["_source"] == "level" else 1 if row["_source"] == "faces" else 2))
    return rows


def create_simulation_engine(
    session_dir: Path,
    output_dir: Path | None = None,
    bonsai: BonsaiWorker | None = None,
) -> SessionEngine:
    metadata = json.loads((session_dir / "metadata.json").read_text(encoding="utf-8"))
    engine = SessionEngine(session_dir=output_dir, bonsai=bonsai)
    engine.people = list(metadata["people"])
    engine.set_calibration(calibration_from_payload(metadata["calibration"]))
    engine.tracker.expected_people = len(engine.people)
    for person in engine.people:
        engine.name_alerts.set_names(person["id"], person.get("name", ""), person.get("aliases", []))
    return engine


async def run_simulation(
    session_dir: Path,
    emit: Emit | None = None,
    speed: float = 0.0,
    output_dir: Path | None = None,
    engine: SessionEngine | None = None,
) -> SessionEngine:
    # The server passes its own engine so Stop, typed Q&A and refine see the
    # same turns the simulation produced.
    engine = engine or create_simulation_engine(session_dir, output_dir)
    rows = load_simulation_inputs(session_dir)
    previous_time = 0.0
    for message in engine.start():
        if emit:
            await emit(message)
    for row in rows:
        current_time = float(row.get("time", 0.0))
        if speed > 0.0:
            await asyncio.sleep(max(0.0, current_time - previous_time) / speed)
        previous_time = current_time
        if row["_source"] == "faces":
            messages = engine.handle_faces(current_time, row.get("people", []))
        elif row["_source"] == "level":
            messages = [engine.handle_level(current_time, float(row.get("rms", 0.0)), float(row.get("peak", 0.0)))]
        else:
            messages = engine.handle_transcript_snapshot(
                current_time,
                str(row.get("text", "")),
                speaker_hint=row.get("speakerId") if row.get("speakerId") else None,
            )
        if emit:
            for message in messages:
                await emit(message)
    final_time = max((float(row.get("time", 0.0)) for row in rows), default=0.0)
    for message in engine.stop(final_time):
        if emit:
            await emit(message)
    engine.phase = "review"
    review = SessionEngine._message(final_time + 0.1, "phase", phase="review")
    engine.recorder.record(review)
    if emit:
        await emit(review)
    engine.recorder.write_metadata(
        {
            "name": f"{session_dir.name}-simulated",
            "turns": [turn.as_dict() for turn in engine.turns],
            "eventCount": len(engine.turns),
        }
    )
    return engine
