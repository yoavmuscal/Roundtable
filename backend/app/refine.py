"""Post-session SpeakerKit diarization matching and transcript refinement."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .contract import turn_id
from .models import Turn


@dataclass(frozen=True, slots=True)
class SpeakerSegment:
    start: float
    end: float
    cluster: str


@dataclass(frozen=True, slots=True)
class RefineResult:
    turns: list[Turn]
    changed_count: int
    total_count: int
    cluster_to_person: dict[str, str]

    def as_dict(self) -> dict[str, object]:
        return {
            "turns": [turn.as_dict() for turn in self.turns],
            "changedCount": self.changed_count,
            "totalCount": self.total_count,
            "clusterToPerson": self.cluster_to_person,
        }


class SpeakerKitAdapter:
    """Run SpeakerKit diarization on a finished WAV; Mac-only by configuration."""

    def __init__(self, command: list[str]) -> None:
        self.command = command

    async def diarize(self, wav_path: Path, speaker_count: int) -> list[SpeakerSegment]:
        # argmax-cli / whisperkit-cli write RTTM to a file; a {rttm} placeholder in the
        # command points there and the file is parsed after the process exits.
        rttm_path = wav_path.with_suffix(".rttm")
        command = [
            part.format(wav=str(wav_path), speakers=speaker_count, rttm=str(rttm_path))
            for part in self.command
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(f"SpeakerKit failed: {stderr.decode('utf-8', errors='replace')[-800:]}")
        output = stdout.decode("utf-8", errors="replace")
        if "{rttm}" in " ".join(self.command) and rttm_path.exists():
            output = rttm_path.read_text(encoding="utf-8") + "\n" + output
        return parse_speakerkit_output(output)


def parse_speakerkit_output(output: str) -> list[SpeakerSegment]:
    """Accept JSON, JSONL, or simple 'start end speaker' lines."""
    segments: list[SpeakerSegment] = []
    try:
        parsed = json.loads(output)
        raw_segments = parsed.get("segments", parsed if isinstance(parsed, list) else [])
        for item in raw_segments:
            segments.append(
                SpeakerSegment(
                    float(item["start"]),
                    float(item["end"]),
                    str(item.get("speaker", item.get("cluster", "unknown"))),
                )
            )
        return sorted(segments, key=lambda item: item.start)
    except (json.JSONDecodeError, TypeError, KeyError, ValueError):
        pass
    line_re = re.compile(r"^(?P<start>\d+(?:\.\d+)?)[\s,]+(?P<end>\d+(?:\.\d+)?)[\s,]+(?P<speaker>[\w-]+)\s*$")
    # RTTM: SPEAKER <file> 1 <start> <duration> <NA> <NA> <speaker> <NA> <NA>
    rttm_re = re.compile(r"^SPEAKER\s+\S+\s+\S+\s+(?P<start>\d+(?:\.\d+)?)\s+(?P<duration>\d+(?:\.\d+)?)\s+\S+\s+\S+\s+(?P<speaker>\S+)")
    for line in output.splitlines():
        rttm = rttm_re.match(line.strip())
        if rttm:
            start = float(rttm.group("start"))
            segments.append(SpeakerSegment(start, start + float(rttm.group("duration")), rttm.group("speaker")))
            continue
        try:
            item = json.loads(line)
            segments.append(
                SpeakerSegment(
                    float(item["start"]),
                    float(item["end"]),
                    str(item.get("speaker", item.get("cluster", "unknown"))),
                )
            )
            continue
        except (json.JSONDecodeError, TypeError, KeyError, ValueError):
            pass
        match = line_re.search(line)
        if match:
            segments.append(
                SpeakerSegment(
                    float(match.group("start")),
                    float(match.group("end")),
                    match.group("speaker"),
                )
            )
    return sorted(segments, key=lambda item: item.start)


def match_clusters_to_people(
    segments: list[SpeakerSegment],
    enrollment_intervals: dict[str, list[tuple[float, float]]] | None = None,
    live_turns: list[Turn] | None = None,
) -> dict[str, str]:
    from itertools import permutations

    clusters = sorted({segment.cluster for segment in segments})
    if not clusters:
        return {}
    enrollment_intervals = enrollment_intervals or {}
    live_turns = live_turns or []

    people_set: set[str] = set(enrollment_intervals.keys())
    for turn in live_turns:
        if turn.speaker_id is not None and turn.confidence >= 0.48:
            people_set.add(turn.speaker_id)
    people = sorted(people_set)
    if not people:
        return {}

    # Score each (cluster, person) pair using normalized enrollment share (weight 2.0)
    # plus high-confidence mouth-attributed turn share (weight 1.0) so even skipped
    # enrollments or unequal enrollment lengths resolve cleanly 1-to-1.
    enroll_totals = {
        person: max(0.01, sum(max(0.0, end - start) for start, end in intervals))
        for person, intervals in enrollment_intervals.items()
    }
    turn_totals: dict[str, float] = {}
    for turn in live_turns:
        if turn.speaker_id is not None and turn.confidence >= 0.48:
            turn_totals[turn.speaker_id] = turn_totals.get(turn.speaker_id, 0.0) + max(0.01, turn.end - turn.start)

    pair_score: dict[tuple[str, str], float] = {}
    for cluster in clusters:
        cluster_segments = [segment for segment in segments if segment.cluster == cluster]
        for person in people:
            score = 0.0
            intervals = enrollment_intervals.get(person, [])
            if intervals:
                ov = sum(
                    _overlap(segment.start, segment.end, start, end)
                    for segment in cluster_segments
                    for start, end in intervals
                )
                score += 2.0 * (ov / enroll_totals[person])
            if person in turn_totals:
                t_ov = sum(
                    _overlap(segment.start, segment.end, turn.start, turn.end)
                    for segment in cluster_segments
                    for turn in live_turns
                    if turn.speaker_id == person and turn.confidence >= 0.48
                )
                score += 1.0 * (t_ov / turn_totals[person])
            pair_score[(cluster, person)] = score

    # Find the highest-scoring 1-to-1 assignment (up to 4 speakers/clusters -> at most 24 perms).
    mapping: dict[str, str] = {}
    if len(clusters) <= len(people):
        best_total = 0.0
        for chosen_people in permutations(people, len(clusters)):
            total = sum(pair_score[(cl, p)] for cl, p in zip(clusters, chosen_people))
            if total > best_total:
                best_total = total
                mapping = {
                    cl: p
                    for cl, p in zip(clusters, chosen_people)
                    if pair_score[(cl, p)] > 0.0
                }
    else:
        best_total = 0.0
        for chosen_clusters in permutations(clusters, len(people)):
            total = sum(pair_score[(cl, p)] for cl, p in zip(chosen_clusters, people))
            if total > best_total:
                best_total = total
                mapping = {
                    cl: p
                    for cl, p in zip(chosen_clusters, people)
                    if pair_score[(cl, p)] > 0.0
                }
        for cl in clusters:
            if cl not in mapping:
                best = max(people, key=lambda p: pair_score[(cl, p)])
                if pair_score[(cl, best)] > 0.0:
                    mapping[cl] = best
    return mapping


def merge_adjacent_segments(segments: list[SpeakerSegment], max_gap_s: float = 0.5) -> list[SpeakerSegment]:
    """SpeakerKit splits one speaker's sentence at short pauses; rejoin same-cluster runs."""
    merged: list[SpeakerSegment] = []
    for segment in sorted(segments, key=lambda item: item.start):
        if merged and merged[-1].cluster == segment.cluster and segment.start - merged[-1].end <= max_gap_s:
            merged[-1] = SpeakerSegment(merged[-1].start, max(merged[-1].end, segment.end), segment.cluster)
        else:
            merged.append(segment)
    return merged


def refine_turns(
    live_turns: list[Turn],
    segments: list[SpeakerSegment],
    cluster_to_person: dict[str, str],
) -> RefineResult:
    refined: list[Turn] = []
    changed = 0
    sequence = 1
    segments = merge_adjacent_segments(segments)
    for turn in live_turns:
        runs = _speaker_runs_for_turn(turn, segments, cluster_to_person)
        if not runs:
            copied = Turn(turn_id(sequence), turn.speaker_id, turn.text, turn.start, turn.end, turn.confidence)
            refined.append(copied)
            sequence += 1
            continue
        if len(runs) == 1:
            speaker = runs[0][2]
            if speaker != turn.speaker_id:
                changed += 1
            refined.append(Turn(turn_id(sequence), speaker, turn.text, turn.start, turn.end, turn.confidence))
            sequence += 1
            continue
        changed += 1
        words = turn.text.split()
        duration = max(1e-9, turn.end - turn.start)
        for index, (start, end, speaker) in enumerate(runs):
            word_start = round(((start - turn.start) / duration) * len(words))
            word_end = round(((end - turn.start) / duration) * len(words))
            if index == len(runs) - 1:
                word_end = len(words)
            text = " ".join(words[word_start:word_end]).strip()
            if not text:
                continue
            refined.append(Turn(turn_id(sequence), speaker, text, start, end, turn.confidence))
            sequence += 1
    return RefineResult(refined, changed, len(live_turns), cluster_to_person)


def _speaker_runs_for_turn(
    turn: Turn,
    segments: list[SpeakerSegment],
    mapping: dict[str, str],
) -> list[tuple[float, float, str | None]]:
    clipped: list[tuple[float, float, str | None]] = []
    for segment in segments:
        start = max(turn.start, segment.start)
        end = min(turn.end, segment.end)
        if end <= start:
            continue
        clipped.append((start, end, mapping.get(segment.cluster)))
    clipped.sort(key=lambda item: item[0])
    if not clipped:
        return []
    runs: list[tuple[float, float, str | None]] = []
    cursor = turn.start
    current_speaker = clipped[0][2]
    for start, end, speaker in clipped:
        if start > cursor:
            runs.append((cursor, start, turn.speaker_id))
            current_speaker = turn.speaker_id
        if speaker != current_speaker:
            runs[-1] = (runs[-1][0], start, current_speaker)
            current_speaker = speaker
        runs.append((start, end, speaker))
        cursor = end
    if cursor < turn.end:
        runs.append((cursor, turn.end, turn.speaker_id))
    merged: list[tuple[float, float, str | None]] = []
    for start, end, speaker in runs:
        if merged and merged[-1][2] == speaker:
            merged[-1] = (merged[-1][0], end, speaker)
        else:
            merged.append((start, end, speaker))
    return merged


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))
