"""Frame-to-frame identity tracking using position plus shirt-color histograms."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import pi
from typing import Callable

from .contract import DEFAULT_THRESHOLDS
from .geometry import Point, distance
from .models import Box, FaceObservation


class OneEuroFilter:
    def __init__(self, min_cutoff: float = 0.8, beta: float = 0.5) -> None:
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.x: float | None = None
        self.dx = 0.0
        self.time: float | None = None

    def update(self, value: float, time_s: float) -> float:
        if self.x is None or self.time is None:
            self.x = value
            self.time = time_s
            return value
        dt = max(1e-3, time_s - self.time)
        derivative = (value - self.x) / dt
        alpha_d = _alpha(1.0, dt)
        self.dx += alpha_d * (derivative - self.dx)
        cutoff = self.min_cutoff + self.beta * abs(self.dx)
        self.x += _alpha(cutoff, dt) * (value - self.x)
        self.time = time_s
        return self.x


def _alpha(cutoff: float, dt: float) -> float:
    tau = 1.0 / (2.0 * pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


def histogram_similarity(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    length = max(len(a), len(b), 1)
    left = tuple(a) + (0.0,) * (length - len(a))
    right = tuple(b) + (0.0,) * (length - len(b))
    left_total = sum(left)
    right_total = sum(right)
    if left_total <= 0 or right_total <= 0:
        return 0.0
    return sum(sqrt_pair(x / left_total, y / right_total) for x, y in zip(left, right))


def sqrt_pair(a: float, b: float) -> float:
    return (a * b) ** 0.5


@dataclass(slots=True)
class TrackedPerson:
    id: str
    observation: FaceObservation
    smoothed: FaceObservation
    first_seen: float
    last_seen: float
    state: str = "seated"
    anchor_mode: str = "chest"
    anchor_point: Point | None = None
    seat_position: Point | None = None
    pending_anchor_mode: str | None = None
    pending_anchor_since: float | None = None
    seat_candidate: Point | None = None
    seat_candidate_since: float | None = None
    seated_shoulder_y: float | None = None
    filters: dict[str, OneEuroFilter] = field(default_factory=dict)

    def update(
        self,
        observation: FaceObservation,
        time_s: float,
        seat_mapper: Callable[[Point], Point] | None,
        thresholds: dict[str, float],
    ) -> None:
        self.observation = observation
        self.smoothed = self._smooth(observation, time_s)
        self.last_seen = time_s

        desired_mode = "chest" if observation.torso_visible and observation.chest_point.y < 0.92 else "head"
        if desired_mode != self.anchor_mode:
            if self.pending_anchor_mode != desired_mode:
                self.pending_anchor_mode = desired_mode
                self.pending_anchor_since = time_s
            elif self.pending_anchor_since is not None and time_s - self.pending_anchor_since >= 0.5:
                self.anchor_mode = desired_mode
                self.pending_anchor_mode = None
                self.pending_anchor_since = None
        else:
            self.pending_anchor_mode = None
            self.pending_anchor_since = None
        raw_anchor = observation.chest_point if self.anchor_mode == "chest" else observation.head_top_point
        self.anchor_point = Point(
            self._filter("anchor_x", 1.0, 0.02).update(raw_anchor.x, time_s),
            self._filter("anchor_y", 1.0, 0.02).update(raw_anchor.y, time_s),
        )

        face_height = max(1e-6, observation.face_box.height)
        shoulder_y = observation.shoulder_point.y
        if self.seated_shoulder_y is None:
            self.seated_shoulder_y = shoulder_y
        rise = self.seated_shoulder_y - shoulder_y
        if rise > 1.5 * face_height:
            self.state = "standing"
        elif self.state == "standing" and rise < 1.2 * face_height:
            self.state = "seated"
        elif self.state == "away":
            self.state = "seated"
        if self.state == "seated":
            self.seated_shoulder_y = 0.98 * self.seated_shoulder_y + 0.02 * shoulder_y

        similarity = histogram_similarity(self.smoothed.shirt_histogram, observation.shirt_histogram)
        if similarity > 0.85 and self.smoothed.shirt_histogram and observation.shirt_histogram:
            adapted = tuple(0.95 * old + 0.05 * new for old, new in zip(self.smoothed.shirt_histogram, observation.shirt_histogram))
            self.smoothed = replace(self.smoothed, shirt_histogram=adapted)

        if seat_mapper is not None:
            mapped = seat_mapper(observation.shoulder_point)
            if self.seat_position is None:
                self.seat_position = mapped
            elif distance(mapped, self.seat_position) > thresholds["seat_follow_distance_m"]:
                if self.seat_candidate is None or distance(mapped, self.seat_candidate) > 0.15:
                    self.seat_candidate = mapped
                    self.seat_candidate_since = time_s
                elif self.seat_candidate_since is not None and time_s - self.seat_candidate_since >= thresholds["seat_follow_after_s"]:
                    self.seat_position = mapped
                    self.seat_candidate = None
                    self.seat_candidate_since = None
            else:
                self.seat_candidate = None
                self.seat_candidate_since = None
                self.seat_position = Point(
                    0.98 * self.seat_position.x + 0.02 * mapped.x,
                    0.98 * self.seat_position.y + 0.02 * mapped.y,
                )

    def mark_unseen(self, time_s: float, away_after_s: float) -> None:
        if time_s - self.last_seen >= away_after_s:
            self.state = "away"

    def _smooth(self, observation: FaceObservation, time_s: float) -> FaceObservation:
        box = observation.face_box
        smoothed_box = Box(
            self._filter("face_x", 0.8, 0.5).update(box.x, time_s),
            self._filter("face_y", 0.8, 0.5).update(box.y, time_s),
            self._filter("face_w", 0.8, 0.5).update(box.width, time_s),
            self._filter("face_h", 0.8, 0.5).update(box.height, time_s),
        )
        return replace(
            observation,
            face_box=smoothed_box,
            shoulder_point=self._smooth_point("shoulder", observation.shoulder_point, time_s),
            chest_point=self._smooth_point("chest", observation.chest_point, time_s),
            head_top_point=self._smooth_point("head", observation.head_top_point, time_s),
        )

    def _smooth_point(self, prefix: str, point: Point, time_s: float) -> Point:
        return Point(
            self._filter(f"{prefix}_x", 0.8, 0.5).update(point.x, time_s),
            self._filter(f"{prefix}_y", 0.8, 0.5).update(point.y, time_s),
        )

    def _filter(self, key: str, min_cutoff: float, beta: float) -> OneEuroFilter:
        if key not in self.filters:
            self.filters[key] = OneEuroFilter(min_cutoff, beta)
        return self.filters[key]

    def as_frame(self) -> dict[str, object]:
        return {
            "id": self.id,
            "faceBox": self.smoothed.face_box.as_dict(),
            "captionAnchor": {
                "point": (self.anchor_point or self.smoothed.chest_point).as_dict(),
                "mode": self.anchor_mode,
            },
            "mapPosition": self.seat_position.as_dict() if self.seat_position else None,
            "state": self.state,
            "mouth": round(self.observation.mouth_score, 4),
        }


@dataclass(slots=True)
class NewcomerCandidate:
    observation: FaceObservation
    first_seen: float
    last_seen: float


class PersonTracker:
    def __init__(
        self,
        expected_people: int = 0,
        thresholds: dict[str, float] | None = None,
        seat_mapper: Callable[[Point], Point] | None = None,
    ) -> None:
        self.expected_people = expected_people
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        self.seat_mapper = seat_mapper
        self.tracks: dict[str, TrackedPerson] = {}
        self.candidates: list[NewcomerCandidate] = []

    def expect_person(self) -> None:
        self.expected_people = min(4, self.expected_people + 1)

    def update(self, time_s: float, observations: list[FaceObservation]) -> list[dict[str, object]]:
        observations = [_normalize_histogram(observation) for observation in observations]
        assignments, unmatched = self._assign(observations, time_s)
        for track_id, detection_index in assignments.items():
            self.tracks[track_id].update(observations[detection_index], time_s, self.seat_mapper, self.thresholds)
        for track_id, track in self.tracks.items():
            if track_id not in assignments:
                track.mark_unseen(time_s, self.thresholds["tracker_away_after_s"])
        for detection_index in unmatched:
            if len(self.tracks) < self.expected_people:
                self._create_track(observations[detection_index], time_s)
            else:
                self._update_newcomer(observations[detection_index], time_s)
        return [track.as_frame() for track in sorted(self.tracks.values(), key=lambda item: item.id)]

    def _assign(self, observations: list[FaceObservation], time_s: float) -> tuple[dict[str, int], list[int]]:
        track_ids = sorted(self.tracks)
        costs: dict[tuple[str, int], float] = {}
        for track_id in track_ids:
            track = self.tracks[track_id]
            for index, observation in enumerate(observations):
                d = distance(track.smoothed.face_box.center, observation.face_box.center)
                similarity = histogram_similarity(track.smoothed.shirt_histogram, observation.shirt_histogram)
                if d > self.thresholds["tracker_match_distance"]:
                    continue
                if track.state == "away" and similarity < self.thresholds["tracker_reidentify_similarity"]:
                    continue
                costs[(track_id, index)] = d + 0.25 * (1.0 - similarity)

        best_cost = float("inf")
        best: dict[str, int] = {}

        def visit(track_index: int, used: set[int], current: dict[str, int], cost: float) -> None:
            nonlocal best_cost, best
            if track_index == len(track_ids):
                if cost < best_cost:
                    best_cost = cost
                    best = dict(current)
                return
            track_id = track_ids[track_index]
            # An unmatched track receives a modest penalty, preventing weak forced matches.
            visit(track_index + 1, used, current, cost + 0.2)
            for detection_index in range(len(observations)):
                edge_cost = costs.get((track_id, detection_index))
                if detection_index not in used and edge_cost is not None:
                    current[track_id] = detection_index
                    used.add(detection_index)
                    visit(track_index + 1, used, current, cost + edge_cost)
                    used.remove(detection_index)
                    del current[track_id]

        visit(0, set(), {}, 0.0)
        assigned_detections = set(best.values())
        return best, [index for index in range(len(observations)) if index not in assigned_detections]

    def _create_track(self, observation: FaceObservation, time_s: float) -> TrackedPerson | None:
        if len(self.tracks) >= 4:
            return None
        person_id = f"p{len(self.tracks) + 1}"
        track = TrackedPerson(
            id=person_id,
            observation=observation,
            smoothed=observation,
            first_seen=time_s,
            last_seen=time_s,
        )
        self.tracks[person_id] = track
        track.update(observation, time_s, self.seat_mapper, self.thresholds)
        return track

    def _update_newcomer(self, observation: FaceObservation, time_s: float) -> None:
        candidate = None
        for item in self.candidates:
            if (
                distance(item.observation.face_box.center, observation.face_box.center) <= self.thresholds["tracker_match_distance"]
                and histogram_similarity(item.observation.shirt_histogram, observation.shirt_histogram) >= 0.5
            ):
                candidate = item
                break
        if candidate is None:
            self.candidates.append(NewcomerCandidate(observation, time_s, time_s))
            return
        candidate.observation = observation
        candidate.last_seen = time_s
        if candidate.last_seen - candidate.first_seen >= self.thresholds["tracker_newcomer_after_s"]:
            self.candidates.remove(candidate)
            self._create_track(observation, time_s)


def _normalize_histogram(observation: FaceObservation) -> FaceObservation:
    histogram = tuple(max(0.0, value) for value in observation.shirt_histogram[:32])
    histogram += (0.0,) * (32 - len(histogram))
    return replace(observation, shirt_histogram=histogram)
