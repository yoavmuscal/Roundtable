"""ASS subtitle and ffmpeg export helpers for a refined Roundtable session."""

from __future__ import annotations

import json
import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

from .contract import SPEAKERS


@dataclass(frozen=True, slots=True)
class ExportTurn:
    id: str
    person_id: str
    text: str
    start: float
    end: float
    tags: tuple[str, ...] = ()


def ass_color(hex_color: str) -> str:
    """Convert #RRGGBB to ASS blue-green-red &HBBGGRR."""
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", hex_color)
    if not match:
        raise ValueError(f"invalid speaker color: {hex_color}")
    value = match.group(1)
    return f"&H{value[4:6]}{value[2:4]}{value[0:2]}".upper()


def format_ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def chunk_text(text: str, max_chars: int = 26, max_lines: int = 2) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    chunks = [lines[index:index + max_lines] for index in range(0, len(lines), max_lines)]
    return ["\\N".join(chunk) for chunk in chunks] or [""]


def median_anchor(anchor_track: list[dict[str, Any]], person_id: str, start: float, end: float) -> tuple[int, int]:
    points = []
    for row in anchor_track:
        time_s = float(row.get("time", 0.0))
        if start <= time_s <= end:
            anchor = row.get("anchors", {}).get(person_id)
            if anchor and anchor.get("point"):
                points.append(anchor["point"])
    if not points:
        return 960, 540
    return (
        round(median(float(point["x"]) for point in points) * 1920),
        round(median(float(point["y"]) for point in points) * 1080),
    )


def push_overlaps_apart(events: list[dict[str, Any]], min_gap_y: int = 72) -> None:
    active: list[dict[str, Any]] = []
    for event in events:
        active = [item for item in active if item["end"] > event["start"]]
        overlapping = [item for item in active if abs(item["y"] - event["y"]) < min_gap_y]
        if overlapping:
            highest = min(item["y"] for item in overlapping)
            event["y"] = max(80, highest - min_gap_y)
        active.append(event)


def build_ass(
    turns: list[ExportTurn],
    anchor_track: list[dict[str, Any]],
    speaker_colors: dict[str, str] | None = None,
) -> str:
    colors = speaker_colors or {person["id"]: person["color"] for person in SPEAKERS[:4]}
    header = """[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"""
    styles = []
    for person_id, color in colors.items():
        styles.append(
            f"Style: {person_id},Inter,42,{ass_color(color)},&H00FFFFFF,&HAA10141B,&H66000000,0,0,0,0,100,100,0,0,1,2.5,1.2,5,24,24,24,1"
        )
    events: list[dict[str, Any]] = []
    for turn in turns:
        chunks = chunk_text(turn.text)
        duration = max(0.2, turn.end - turn.start)
        x, y = median_anchor(anchor_track, turn.person_id, turn.start, turn.end)
        for index, chunk in enumerate(chunks):
            chunk_start = turn.start + duration * index / len(chunks)
            chunk_end = turn.start + duration * (index + 1) / len(chunks)
            text = escape_ass(chunk)
            if index == 0 and turn.tags:
                text = f"[{', '.join(turn.tags)}] {text}"
            events.append(
                {
                    "start": chunk_start,
                    "end": chunk_end,
                    "style": turn.person_id,
                    "x": x,
                    "y": y,
                    "text": text,
                }
            )
    events.sort(key=lambda item: item["start"])
    push_overlaps_apart(events)
    lines = ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for item in events:
        lines.append(
            "Dialogue: 0,{start},{end},{style},,0,0,0,,{{\\pos({x},{y})}}{text}".format(
                start=format_ass_time(item["start"]),
                end=format_ass_time(item["end"]),
                style=item["style"],
                x=item["x"],
                y=item["y"],
                text=item["text"],
            )
        )
    return header + "\n".join(styles) + "\n".join(lines) + "\n"


def escape_ass(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def load_anchor_track(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def export_session_ass(session_dir: Path, output_path: Path | None = None) -> Path:
    output_path = output_path or session_dir / "captions.ass"
    metadata_path = session_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    colors = {
        person["id"]: person["color"]
        for person in metadata.get("people", [])
        if isinstance(person, dict) and "id" in person and "color" in person
    }
    transcript_path = session_dir / "refined_transcript.jsonl"
    if not transcript_path.exists():
        transcript_path = session_dir / "live_transcript.jsonl"
    turns = []
    for line in transcript_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        turns.append(
            ExportTurn(
                id=row["id"],
                person_id=row.get("personId", row.get("speakerId", "p1")),
                text=row.get("text", ""),
                start=float(row.get("start", 0.0)),
                end=float(row.get("end", 0.0)),
                tags=tuple(row.get("tags", [])),
            )
        )
    output_path.write_text(
        build_ass(turns, load_anchor_track(session_dir / "anchors.jsonl"), colors),
        encoding="utf-8",
    )
    return output_path


def ffmpeg_export_command(
    video_path: Path,
    audio_path: Path,
    ass_path: Path,
    output_path: Path,
    audio_offset_s: float = 0.0,
) -> list[str]:
    """Build a timestamp-regenerating 30 fps ffmpeg export command."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    command = [ffmpeg, "-y", "-i", str(video_path)]
    if audio_offset_s > 0:
        command += ["-itsoffset", f"{audio_offset_s:.3f}"]
    command += [
        "-i", str(audio_path),
        "-vf", f"fps=30,setpts=N/30/TB,ass={ass_path}",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "aac",
        "-shortest",
        str(output_path),
    ]
    return command
