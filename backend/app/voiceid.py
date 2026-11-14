"""Live voice ID with Argmax SpeakerKit (open source).

After a caption turn finishes, the turn's audio is placed after each person's enrollment
sample in one short WAV and diarized with `argmax-cli diarize`. The cluster each
enrollment sample falls into names that cluster; the turn takes the person whose cluster
covers most of it. This identifies speakers by voice, so it works when a mouth is
covered or off camera. A call takes about 0.5 s once the model is warm.
"""

from __future__ import annotations

import asyncio
import wave
from dataclasses import dataclass
from pathlib import Path

from .refine import SpeakerSegment, parse_speakerkit_output

SAMPLE_RATE = 16_000
GAP_S = 0.4
MAX_ENROLL_S = 6.0
MAX_TURN_S = 10.0
MIN_CLIP_S = 1.0


@dataclass(frozen=True, slots=True)
class VoiceMatch:
    person_id: str | None
    coverage: float  # share of the turn audio inside the matched person's cluster


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


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
        if amount >= 0.4 * (end - start):
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

    async def identify(self, enrollment: dict[str, bytes], turn_pcm: bytes) -> VoiceMatch:
        clips = {person: pcm[-int(MAX_ENROLL_S * SAMPLE_RATE) * 2:] for person, pcm in enrollment.items() if len(pcm) >= MIN_CLIP_S * SAMPLE_RATE * 2}
        turn_pcm = turn_pcm[-int(MAX_TURN_S * SAMPLE_RATE) * 2:]
        if len(clips) < 2 or len(turn_pcm) < MIN_CLIP_S * SAMPLE_RATE * 2:
            return VoiceMatch(None, 0.0)
        async with self.lock:
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
                return VoiceMatch(None, 0.0)
            segments = parse_speakerkit_output(rttm_path.read_text(encoding="utf-8"))
        return match_turn(segments, regions, turn_region)
