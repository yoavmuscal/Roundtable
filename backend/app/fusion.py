"""Mouth-motion/speech fusion and active-speaker hysteresis."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .contract import DEFAULT_THRESHOLDS


@dataclass(frozen=True, slots=True)
class MouthSample:
    time: float
    person_id: str
    score: float


@dataclass(frozen=True, slots=True)
class Attribution:
    speaker_id: str | None
    confidence: float
    dashed: bool = False
    reason: str = "none"


class SpeakerFusion:
    def __init__(self, thresholds: dict[str, float] | None = None) -> None:
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        self.samples: list[MouthSample] = []
        self.previous_speaker: str | None = None
        self.previous_end: float | None = None

    def add_sample(self, time_s: float, person_id: str, score: float) -> None:
        self.samples.append(MouthSample(time_s, person_id, max(0.0, min(1.0, score))))
        # Keep enough history for caption windows and replay without unbounded growth.
        cutoff = time_s - 120.0
        self.samples = [sample for sample in self.samples if sample.time >= cutoff]

    def relabel(self, a: str, b: str) -> None:
        """Swap two person ids in the stored mouth history (after a track is renamed)."""
        swap = {a: b, b: a}
        self.samples = [MouthSample(item.time, swap.get(item.person_id, item.person_id), item.score) for item in self.samples]

    def mean_mouth(self, start_s: float, end_s: float) -> dict[str, float]:
        totals: dict[str, list[float]] = {}
        for sample in self.samples:
            if start_s <= sample.time <= end_s:
                totals.setdefault(sample.person_id, []).append(sample.score)
        return {person: sum(values) / len(values) for person, values in totals.items() if values}

    def attribute(self, start_s: float, end_s: float) -> Attribution:
        window_start = start_s - 0.2
        totals: dict[str, list[float]] = defaultdict(list)
        for sample in self.samples:
            if window_start <= sample.time <= end_s:
                totals[sample.person_id].append(sample.score)
        averages = {person: sum(values) / len(values) for person, values in totals.items() if values}
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
