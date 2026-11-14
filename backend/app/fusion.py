"""Mouth-motion/speech fusion and active-speaker hysteresis.

Talker detection combines each face's mouth activity during voiced mic frames
(above each person's silent-room baseline, so steady nodding/chewing is
discounted) with live SpeakerKit voice hints from the same speech window.
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

    def max_rms(self, start_s: float, end_s: float) -> float:
        vals = [sample.rms for sample in self.levels if start_s <= sample.time <= end_s]
        return max(vals) if vals else 0.0

    def _rms_envelope(self, time_s: float) -> float | None:
        """Trailing 0.65 s RMS envelope matching browser jawOpen's 0.6 s window."""
        if not self.levels:
            return None
        vals = [sample.rms for sample in self.levels if time_s - 0.65 <= sample.time <= time_s + 0.08]
        if not vals:
            return None
        # Blend peak and mean so syllable/clause dips stay voiced while jawOpen decays.
        return 0.6 * max(vals) + 0.4 * (sum(vals) / len(vals))

    def fused_scores(self, start_s: float, end_s: float) -> dict[str, float]:
        """Score each person by mouth motion during voiced audio minus silent baseline."""
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

        rms_floor = self.thresholds.get("fusion_rms_floor", 0.015)
        scores: dict[str, float] = {}
        for person, points in mouth_by_person.items():
            mouths: list[float] = []
            envs: list[float] = []
            quiet_mouths: list[float] = []
            voiced_mouths: list[float] = []
            for time_s, mouth in points:
                env = self._rms_envelope(time_s)
                if env is None:
                    continue
                mouths.append(mouth)
                envs.append(env)
                if env >= rms_floor:
                    voiced_mouths.append(mouth)
                else:
                    quiet_mouths.append(mouth)
            if not mouths:
                scores[person] = sum(score for _, score in points) / len(points)
                continue

            mean_mouth = sum(mouths) / len(mouths)
            peak_env = max(envs)
            mean_env = sum(envs) / len(envs)
            total_env = sum(envs)
            weighted = sum(m * e for m, e in zip(mouths, envs)) / total_env if total_env > 1e-9 else mean_mouth

            # Room was silent for the whole window: nobody is speaking on the mic.
            if peak_env < rms_floor:
                scores[person] = mean_mouth * 0.08
                continue

            voiced_mean = sum(voiced_mouths) / len(voiced_mouths) if voiced_mouths else weighted
            idle_baseline = sum(quiet_mouths) / len(quiet_mouths) if quiet_mouths else 0.0
            # Discount any jaw motion this person already had while the mic was silent
            # (e.g. steady nodding or chewing before/after someone else's sentence).
            active_above_idle = max(0.0, voiced_mean - 0.85 * idle_baseline)

            corr = _pearson(mouths, envs)
            if quiet_mouths and voiced_mouths:
                # Window spans both silence and speech: someone whose jaw stayed high in silence loses.
                sync = max(0.0, corr) if corr is not None else (active_above_idle / max(0.05, voiced_mean))
                score = (0.25 + 0.75 * sync) * active_above_idle
            else:
                # Continuous speech window: trust voiced mouth activity directly.
                score = 0.65 * voiced_mean + 0.35 * weighted
                if corr is not None and corr < -0.35:
                    score *= 0.4

            scores[person] = max(0.0, min(1.0, score))
        return scores

    def _with_voice(self, scores: dict[str, float], start_s: float, end_s: float) -> dict[str, float]:
        """Blend SpeakerKit hits inside this speech window. Later hits do not apply."""
        hints = [hint for hint in self.voice_hints if start_s - 0.6 <= hint.time <= end_s + 0.2]
        if not hints:
            return scores
        # Aggregate voice hits in the window by coverage weight.
        totals: dict[str, float] = defaultdict(float)
        best_cov: dict[str, float] = defaultdict(float)
        for hint in hints:
            totals[hint.person_id] += hint.coverage
            best_cov[hint.person_id] = max(best_cov[hint.person_id], hint.coverage)
        voice_winner = max(totals.items(), key=lambda item: item[1])[0]
        cov = best_cov[voice_winner]

        blended = dict(scores)
        top_mouth = max(blended.values(), default=0.0)
        mouth = blended.get(voice_winner, 0.0)
        voice_score = min(1.0, 0.48 + 0.48 * cov)
        if top_mouth < 0.18:
            # Covered or subtle mouth: let SpeakerKit carry the attribution.
            blended[voice_winner] = max(mouth, voice_score)
        else:
            # Combine mouth and voice so agreeing signals win decisively and conflicting noise doesn't flip a clear mouth.
            blended[voice_winner] = min(1.0, 0.55 * mouth + 0.45 * voice_score)
        return blended

    def attribute(self, start_s: float, end_s: float) -> Attribution:
        window_start = max(0.0, start_s - 0.35)
        window_end = max(end_s, start_s + 0.3)
        averages = self._with_voice(self.fused_scores(window_start, window_end), window_start, window_end)
        if not averages:
            return Attribution(None, 0.0, reason="no_samples")
        ranked = sorted(averages.items(), key=lambda item: item[1], reverse=True)
        top_person, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = top_score - second_score

        if (
            top_score >= self.thresholds["fusion_top"]
            and margin >= self.thresholds["fusion_margin"]
        ):
            result = Attribution(top_person, top_score, reason="clear")
        elif top_score >= 0.16 and margin >= 0.10 and (second_score < 0.06 or top_score >= 2.2 * second_score):
            # One mouth is clearly moving while the other face is still (common in casual laptop speech).
            result = Attribution(top_person, max(top_score, 0.52), reason="clear")
        elif (
            self.previous_speaker is not None
            and self.previous_end is not None
            and end_s - self.previous_end < self.thresholds["previous_speaker_window_s"]
            and margin < 0.08
            and not (top_person != self.previous_speaker and top_score >= 0.06 and averages.get(self.previous_speaker, 0.0) < 0.02)
        ):
            result = Attribution(self.previous_speaker, 0.4, reason="previous")
        elif top_score >= self.thresholds["fusion_fallback"] and margin >= 0.03:
            result = Attribution(top_person, top_score, dashed=True, reason="fallback")
        elif top_score >= 0.08 and margin >= 0.04:
            result = Attribution(top_person, top_score, dashed=True, reason="fallback")
        elif top_score >= 0.05 and margin >= 0.03 and second_score < 0.02:
            result = Attribution(top_person, max(top_score, 0.35), dashed=True, reason="fallback")
        elif self.previous_speaker is not None and self.previous_speaker in averages:
            result = Attribution(self.previous_speaker, 0.3, dashed=True, reason="previous")
        else:
            result = Attribution(None, 0.0, reason="ambiguous")

        if result.speaker_id is not None and result.reason != "previous":
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
