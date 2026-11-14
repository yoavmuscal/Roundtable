"""Live voice ID with Argmax SpeakerKit (open source).

Concatenates equal-length, voiced enrollment clips for each speaker plus a live
speech clip into one short WAV and diarizes with `argmax-cli diarize`. Keeping
enrollment clips balanced in duration prevents VBx clustering from collapsing a
shorter voice into a longer enrollment cluster.
"""

from __future__ import annotations

import asyncio
import math
import wave
from dataclasses import dataclass
from pathlib import Path

from .refine import SpeakerSegment, parse_speakerkit_output

SAMPLE_RATE = 16_000
GAP_S = 0.4
TARGET_ENROLL_S = 5.5
MAX_TURN_S = 8.0
MIN_CLIP_S = 1.0


@dataclass(frozen=True, slots=True)
class VoiceMatch:
    person_id: str | None
    coverage: float  # share of the turn audio inside the matched person's cluster


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def trim_voiced_clip(pcm: bytes, target_s: float = TARGET_ENROLL_S) -> bytes:
    """Keep the loudest contiguous `target_s` window and strip leading/trailing silence."""
    frame_bytes = int(0.1 * SAMPLE_RATE) * 2  # 100 ms frames
    if len(pcm) <= frame_bytes * 2:
        return pcm
    energies: list[float] = []
    for offset in range(0, len(pcm) - frame_bytes + 1, frame_bytes):
        chunk = pcm[offset : offset + frame_bytes]
        count = len(chunk) // 2
        sq = 0
        for i in range(0, count * 2, 2):
            val = int.from_bytes(chunk[i : i + 2], "little", signed=True)
            sq += val * val
        energies.append(math.sqrt(sq / max(1, count)) / 32768.0)
    if not energies:
        return pcm
    peak = max(energies)
    floor = max(0.008, peak * 0.15)
    voiced_idx = [idx for idx, rms in enumerate(energies) if rms >= floor]
    if voiced_idx:
        first = max(0, voiced_idx[0] - 1)
        last = min(len(energies), voiced_idx[-1] + 2)
        pcm = pcm[first * frame_bytes : last * frame_bytes]
    target_bytes = int(target_s * SAMPLE_RATE) * 2
    if len(pcm) <= target_bytes:
        return pcm
    # Slide a target_s window to pick the most voiced stretch.
    win_frames = max(1, int(round(target_s / 0.1)))
    sub_energies: list[float] = []
    for offset in range(0, len(pcm) - frame_bytes + 1, frame_bytes):
        chunk = pcm[offset : offset + frame_bytes]
        count = len(chunk) // 2
        sq = 0
        for i in range(0, count * 2, 2):
            val = int.from_bytes(chunk[i : i + 2], "little", signed=True)
            sq += val * val
        sub_energies.append(sq)
    if len(sub_energies) <= win_frames:
        return pcm[:target_bytes]
    best_start = max(
        range(len(sub_energies) - win_frames + 1),
        key=lambda start: sum(sub_energies[start : start + win_frames]),
    )
    return pcm[best_start * frame_bytes : best_start * frame_bytes + target_bytes]


def _balance_enrollment_clips(enrollment: dict[str, bytes]) -> dict[str, bytes]:
    """Trim each person's sample to its voiced core and match durations so VBx stays fair."""
    trimmed = {
        person: trim_voiced_clip(pcm, TARGET_ENROLL_S)
        for person, pcm in enrollment.items()
        if len(pcm) >= MIN_CLIP_S * SAMPLE_RATE * 2
    }
    trimmed = {
        person: pcm
        for person, pcm in trimmed.items()
        if len(pcm) >= MIN_CLIP_S * SAMPLE_RATE * 2
    }
    if len(trimmed) < 2:
        return trimmed
    shortest = min(len(pcm) for pcm in trimmed.values())
    # Cap every clip to at most 1.35x the shortest clip so one long sample never dominates VBx.
    cap = max(int(2.5 * SAMPLE_RATE) * 2, int(shortest * 1.35) // 2 * 2)
    return {person: trim_voiced_clip(pcm, cap / 2 / SAMPLE_RATE) for person, pcm in trimmed.items()}


def _cluster_of_region(segments: list[SpeakerSegment], start: float, end: float) -> str | None:
    cover: dict[str, float] = {}
    for segment in segments:
        cover[segment.cluster] = cover.get(segment.cluster, 0.0) + _overlap(segment.start, segment.end, start, end)
    if not cover:
        return None
    cluster, amount = max(cover.items(), key=lambda item: item[1])
    if amount < 0.35 * max(0.01, end - start):
        return None
    return cluster


def enrollment_collisions(segments: list[SpeakerSegment], regions: dict[str, tuple[float, float]]) -> list[list[str]]:
    """People whose enrollment clips landed in the same SpeakerKit cluster."""
    groups: dict[str, list[str]] = {}
    for person_id, (start, end) in regions.items():
        cluster = _cluster_of_region(segments, start, end)
        if cluster is None:
            continue
        groups.setdefault(cluster, []).append(person_id)
    return [people for people in groups.values() if len(people) >= 2]


def match_turn(
    segments: list[SpeakerSegment],
    regions: dict[str, tuple[float, float]],
    turn_region: tuple[float, float],
) -> VoiceMatch:
    """Name clusters from enrollment regions, then pick the turn's dominant cluster."""
    cluster_of: dict[str, str] = {}
    for person_id, (start, end) in regions.items():
        cover: dict[str, float] = {}
        for segment in segments:
            cover[segment.cluster] = cover.get(segment.cluster, 0.0) + _overlap(segment.start, segment.end, start, end)
        if not cover:
            continue
        cluster, amount = max(cover.items(), key=lambda item: item[1])
        if amount >= 0.35 * (end - start):
            cluster_of[person_id] = cluster
    clusters = list(cluster_of.values())
    if len(set(clusters)) != len(clusters) or len(clusters) < 2:
        return VoiceMatch(None, 0.0)  # two people sound alike to SpeakerKit: do not guess
    person_of = {cluster: person for person, cluster in cluster_of.items()}
    turn_start, turn_end = turn_region
    cover = {}
    for segment in segments:
        cover[segment.cluster] = cover.get(segment.cluster, 0.0) + _overlap(segment.start, segment.end, turn_start, turn_end)
    if not cover:
        return VoiceMatch(None, 0.0)
    cluster, amount = max(cover.items(), key=lambda item: item[1])
    voiced = sum(cover.values()) or 1.0
    return VoiceMatch(person_of.get(cluster), amount / voiced)


class VoiceIdentifier:
    def __init__(self, command: list[str], workdir: Path) -> None:
        self.command = command
        self.workdir = workdir
        self.lock = asyncio.Lock()

    async def alike_groups(self, enrollment: dict[str, bytes]) -> list[list[str]]:
        """SpeakerKit on the enrollment clips. Groups that share one voice cluster."""
        clips = _balance_enrollment_clips(enrollment)
        if len(clips) < 2:
            return []
        async with self.lock:
            segments, regions, _turn = await self._diarize(clips, b"")
        if not segments:
            return []
        return enrollment_collisions(segments, regions)

    async def identify(self, enrollment: dict[str, bytes], turn_pcm: bytes) -> VoiceMatch:
        clips = _balance_enrollment_clips(enrollment)
        turn_pcm = trim_voiced_clip(turn_pcm[-int(MAX_TURN_S * SAMPLE_RATE) * 2 :], MAX_TURN_S)
        if len(clips) < 2 or len(turn_pcm) < MIN_CLIP_S * SAMPLE_RATE * 2:
            return VoiceMatch(None, 0.0)
        async with self.lock:
            segments, regions, turn_region = await self._diarize(clips, turn_pcm)
        if turn_region is None or not segments:
            return VoiceMatch(None, 0.0)
        return match_turn(segments, regions, turn_region)

    async def _diarize(
        self,
        clips: dict[str, bytes],
        turn_pcm: bytes,
    ) -> tuple[list[SpeakerSegment], dict[str, tuple[float, float]], tuple[float, float] | None]:
        self.workdir.mkdir(parents=True, exist_ok=True)
        wav_path = self.workdir / "voiceid.wav"
        rttm_path = self.workdir / "voiceid.rttm"
        gap = b"\x00\x00" * int(GAP_S * SAMPLE_RATE)
        regions: dict[str, tuple[float, float]] = {}
        audio = bytearray()
        for person, pcm in clips.items():
            start = len(audio) / 2 / SAMPLE_RATE
            audio.extend(pcm)
            regions[person] = (start, len(audio) / 2 / SAMPLE_RATE)
            audio.extend(gap)
        turn_region = None
        if turn_pcm:
            turn_start = len(audio) / 2 / SAMPLE_RATE
            audio.extend(turn_pcm)
            turn_region = (turn_start, len(audio) / 2 / SAMPLE_RATE)
        with wave.open(str(wav_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(SAMPLE_RATE)
            handle.writeframes(bytes(audio))
        rttm_path.unlink(missing_ok=True)
        command = [part.format(wav=str(wav_path), speakers=len(clips), rttm=str(rttm_path)) for part in self.command]
        process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await process.communicate()
        if process.returncode != 0 or not rttm_path.exists():
            return [], regions, turn_region
        return parse_speakerkit_output(rttm_path.read_text(encoding="utf-8")), regions, turn_region
