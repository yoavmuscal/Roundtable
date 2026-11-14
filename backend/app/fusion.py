"""Mouth-motion/speech fusion and active-speaker hysteresis.

Talker detection correlates each face's mouth score with the mic volume over
the same window (rise/fall together). Mean jaw motion alone is fooled by
nodding, chewing, or a covered mouth while someone else speaks.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import sqrt

from .contract import DEFAULT_THRESHOLDS


@dataclass(frozen=True, slots=True)
class MouthSample:
    time: float
    person_id: str
    score: float


@dataclass(frozen=True, slots=True)
class LevelSample:
    time: float
    rms: float


@dataclass(frozen=True, slots=True)
class VoiceHint:
    time: float
    person_id: str
    coverage: float


@dataclass(frozen=True, slots=True)
class Attribution:
    speaker_id: str | None
    confidence: float
    dashed: bool = False
    reason: str = "none"


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 1e-12 or var_y <= 1e-12:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return cov / sqrt(var_x * var_y)


class SpeakerFusion:
    def __init__(self, thresholds: dict[str, float] | None = None) -> None:
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        self.samples: list[MouthSample] = []
        self.levels: list[LevelSample] = []
        self.voice_hints: list[VoiceHint] = []
        self.previous_speaker: str | None = None
        self.previous_end: float | None = None

    def add_sample(self, time_s: float, person_id: str, score: float) -> None:
        self.samples.append(MouthSample(time_s, person_id, max(0.0, min(1.0, score))))
        # Keep enough history for caption windows and replay without unbounded growth.
        cutoff = time_s - 120.0
        self.samples = [sample for sample in self.samples if sample.time >= cutoff]
        self.levels = [sample for sample in self.levels if sample.time >= cutoff]

    def add_level(self, time_s: float, rms: float) -> None:
        self.levels.append(LevelSample(time_s, max(0.0, float(rms))))
        cutoff = time_s - 120.0
        self.levels = [sample for sample in self.levels if sample.time >= cutoff]

    def add_voice(self, time_s: float, person_id: str, coverage: float) -> None:
        """A SpeakerKit hit for audio around time_s. Ignored once that moment has ended."""
        self.voice_hints.append(VoiceHint(time_s, person_id, max(0.0, min(1.0, coverage))))
        cutoff = time_s - 120.0
        self.voice_hints = [hint for hint in self.voice_hints if hint.time >= cutoff]

    def relabel(self, a: str, b: str) -> None:
        """Swap two person ids in the stored mouth history (after a track is renamed)."""
        swap = {a: b, b: a}
        self.samples = [MouthSample(item.time, swap.get(item.person_id, item.person_id), item.score) for item in self.samples]
        self.voice_hints = [VoiceHint(item.time, swap.get(item.person_id, item.person_id), item.coverage) for item in self.voice_hints]

    def mean_mouth(self, start_s: float, end_s: float) -> dict[str, float]:
        totals: dict[str, list[float]] = {}
        for sample in self.samples:
            if start_s <= sample.time <= end_s:
                totals.setdefault(sample.person_id, []).append(sample.score)
        return {person: sum(values) / len(values) for person, values in totals.items() if values}

    def _rms_near(self, time_s: float, max_gap: float = 0.12) -> float | None:
        if not self.levels:
            return None
        best: LevelSample | None = None
        best_gap = max_gap
        for sample in self.levels:
            gap = abs(sample.time - time_s)
            if gap <= best_gap:
                best = sample
                best_gap = gap
        return None if best is None else best.rms

    def fused_scores(self, start_s: float, end_s: float) -> dict[str, float]:
        """Score each person by mouth motion that tracks mic volume.

        Without mic history, falls back to plain mean mouth (same as before).
        """
        mouth_by_person: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for sample in self.samples:
            if start_s <= sample.time <= end_s:
                mouth_by_person[sample.person_id].append((sample.time, sample.score))
        if not mouth_by_person:
            return {}

        if not self.levels:
            return {
                person: sum(score for _, score in points) / len(points)
                for person, points in mouth_by_person.items()
            }

        scores: dict[str, float] = {}
        for person, points in mouth_by_person.items():
            mouths: list[float] = []
            levels: list[float] = []
            for time_s, mouth in points:
                rms = self._rms_near(time_s)
                if rms is None:
                    continue
                mouths.append(mouth)
                levels.append(rms)
            if not mouths:
                continue
            mean_mouth = sum(mouths) / len(mouths)
            mean_rms = sum(levels) / len(levels)
            # Prefer mouths that are open while the room is loud (chewing in silence → low).
            weighted = (
                sum(m * r for m, r in zip(mouths, levels)) / sum(levels)
                if sum(levels) > 1e-9
                else mean_mouth
            )
            mouth_var = _variance(mouths)
            rms_var = _variance(levels)
            corr = _pearson(mouths, levels)
            quiet = mean_rms < self.thresholds.get("fusion_rms_floor", 0.015)
            if corr is not None:
                # Mouth rises/falls with the mic → talker. Uncorrelated jaw → not the talker.
                sync = max(0.0, corr)
                scores[person] = sync * (0.55 * weighted + 0.45 * mean_mouth)
            elif mouth_var <= 1e-12 and rms_var > 1e-12:
                # Flat jaw while the mic changes (steady nod/chew during someone else's speech).
                scores[person] = 0.0
            else:
                # Steady talker (flat loud mic + open mouth) or too few samples for correlation.
                scores[person] = 0.45 * mean_mouth + 0.55 * weighted
            # Quiet room: jaw motion alone must not look like a clear talker.
            if quiet:
                scores[person] *= 0.35
            scores[person] = max(0.0, min(1.0, scores[person]))
        return scores

    def _with_voice(self, scores: dict[str, float], start_s: float, end_s: float) -> dict[str, float]:
        """Blend a voice hit that landed inside this speech window. Later hits do not apply."""
        hints = [hint for hint in self.voice_hints if start_s <= hint.time <= end_s]
        if not hints:
            return scores
        hint = hints[-1]
        blended = dict(scores)
        mouth = blended.get(hint.person_id, 0.0)
        voice_score = 0.35 + 0.5 * hint.coverage
        blended[hint.person_id] = min(1.0, 0.5 * mouth + 0.5 * voice_score)
        return blended

    def attribute(self, start_s: float, end_s: float) -> Attribution:
        window_start = start_s - 0.2
        averages = self._with_voice(self.fused_scores(window_start, end_s), window_start, end_s)
        if not averages:
            return Attribution(None, 0.0, reason="no_samples")
        ranked = sorted(averages.items(), key=lambda item: item[1], reverse=True)
        top_person, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        if (
            top_score >= self.thresholds["fusion_top"]
            and top_score - second_score >= self.thresholds["fusion_margin"]
        ):
            result = Attribution(top_person, top_score, reason="clear")
        elif (
            self.previous_speaker is not None
            and self.previous_end is not None
            and end_s - self.previous_end < self.thresholds["previous_speaker_window_s"]
        ):
            result = Attribution(self.previous_speaker, 0.4, reason="previous")
        elif top_score >= self.thresholds["fusion_fallback"]:
            result = Attribution(top_person, top_score, dashed=True, reason="fallback")
        else:
            result = Attribution(None, 0.0, reason="ambiguous")
        if result.speaker_id is not None:
            self.previous_speaker = result.speaker_id
            self.previous_end = end_s
        return result


class ActiveSpeakerGate:
    """Require audible sound and 0.3 s of stability before turning on the glow."""

    def __init__(self, hysteresis_s: float | None = None, rms_floor: float = 0.015) -> None:
        self.hysteresis_s = hysteresis_s if hysteresis_s is not None else DEFAULT_THRESHOLDS["active_hysteresis_s"]
        self.rms_floor = rms_floor
        self.current: str | None = None
        self.candidate: str | None = None
        self.candidate_since: float | None = None
        self.silence_since: float | None = None

    def update(self, time_s: float, proposed_speaker: str | None, rms: float) -> str | None:
        audible = rms >= self.rms_floor
        if not audible:
            if self.silence_since is None:
                self.silence_since = time_s
            if time_s - self.silence_since >= self.hysteresis_s:
                self.current = None
                self.candidate = None
                self.candidate_since = None
            return self.current
        self.silence_since = None
        candidate = proposed_speaker
        if candidate == self.current:
            self.candidate = None
            self.candidate_since = None
            return self.current
        if candidate != self.candidate:
            self.candidate = candidate
            self.candidate_since = time_s
            return self.current
        if self.candidate_since is not None and time_s - self.candidate_since >= self.hysteresis_s:
            self.current = candidate
            self.candidate = None
            self.candidate_since = None
        return self.current
