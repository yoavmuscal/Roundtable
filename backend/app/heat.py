"""Per-speaker room-map heat, ownership, fairness reach caps, and decay."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import exp, sqrt
from typing import Literal

from .geometry import Point, distance
from .hexmap import Axial, HexGrid

HeatMode = Literal["all", "60s"]


@dataclass(frozen=True, slots=True)
class HeatHex:
    coord: Axial
    owner: str
    opacity: float
    share: float
    contested: bool
    intensity: float

    def as_dict(self) -> dict[str, object]:
        return {
            "axial": self.coord.as_dict(),
            "owner": self.owner,
            "opacity": round(self.opacity, 4),
            "share": round(self.share, 4),
            "contested": self.contested,
            "intensity": round(self.intensity, 4),
        }


class HeatMap:
    def __init__(
        self,
        grid: HexGrid,
        sigma_m: float = 0.35,
        reach_min_m: float = 0.35,
        reach_scale_m: float = 0.7,
    ) -> None:
        self.grid = grid
        self.sigma_m = sigma_m
        self.reach_min_m = reach_min_m
        self.reach_scale_m = reach_scale_m
        self.energy: dict[Axial, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.events: list[tuple[float, Axial, str, float]] = []
        self.talk_totals: dict[str, float] = defaultdict(float)
        self._reference = 0.0

    def deposit(self, time_s: float, person_id: str, position: Point, duration_s: float, loudness: float = 1.0) -> None:
        amount = max(0.0, duration_s) * max(0.0, loudness)
        if amount <= 0.0:
            return
        cutoff = self.sigma_m * 3.0
        weighted: list[tuple[Axial, float]] = []
        for cell in self.grid.cells.values():
            d = distance(cell.center, position)
            if d <= cutoff:
                weighted.append((cell.coord, exp(-(d * d) / (2.0 * self.sigma_m * self.sigma_m))))
        normalizer = sum(weight for _, weight in weighted)
        if normalizer <= 0.0:
            return
        for coord, weight in weighted:
            share = amount * weight / normalizer
            self.energy[coord][person_id] += share
            self.events.append((time_s, coord, person_id, share))
        self.talk_totals[person_id] += amount

    def frame(self, now_s: float, mode: HeatMode = "all") -> list[dict[str, object]]:
        energies = self._capped_energies(now_s, mode)
        nonzero_totals = [sum(people.values()) for people in energies.values()]
        nonzero_totals = [value for value in nonzero_totals if value > 1e-12]
        if not nonzero_totals:
            return []
        reference = _percentile(nonzero_totals, 0.95)
        self._reference = reference if self._reference <= 0 else 0.9 * self._reference + 0.1 * reference
        output: list[HeatHex] = []
        for coord, people in energies.items():
            total = sum(people.values())
            if total <= 1e-12:
                continue
            owner, owner_energy = max(people.items(), key=lambda item: item[1])
            share = owner_energy / total
            intensity = min(1.0, total / max(self._reference, 1e-12))
            opacity = 0.06 + 0.84 * sqrt(intensity)
            if opacity < 0.08:
                continue
            output.append(
                HeatHex(
                    coord=coord,
                    owner=owner,
                    opacity=min(1.0, opacity),
                    share=share,
                    contested=share < 0.55,
                    intensity=intensity,
                )
            )
        return [item.as_dict() for item in sorted(output, key=lambda item: item.coord)]

    def talk_shares(self) -> dict[str, float]:
        total = sum(self.talk_totals.values())
        if total <= 0.0:
            return {}
        return {person: value / total for person, value in sorted(self.talk_totals.items())}

    def _capped_energies(self, now_s: float, mode: HeatMode) -> dict[Axial, dict[str, float]]:
        if mode == "all":
            source = {coord: dict(values) for coord, values in self.energy.items()}
        else:
            source: dict[Axial, dict[str, float]] = defaultdict(lambda: defaultdict(float))
            for event_time, coord, person, amount in self.events:
                age = now_s - event_time
                if age < 0.0:
                    continue
                fade = max(0.0, 1.0 - age / 60.0)
                if fade > 0.0:
                    source[coord][person] += amount * fade
        peaks = self._person_peaks()
        top_talk = max(self.talk_totals.values(), default=0.0)
        capped: dict[Axial, dict[str, float]] = {}
        for coord, people in source.items():
            center = self.grid.cells[coord].center
            kept: dict[str, float] = {}
            for person, value in people.items():
                peak = peaks.get(person)
                if peak is None:
                    continue
                total_talk = self.talk_totals.get(person, 0.0)
                relative_talk = total_talk / top_talk if top_talk > 0 else 1.0
                reach = max(self.reach_min_m, self.reach_scale_m * sqrt(max(0.0, relative_talk)))
                if distance(center, peak) <= reach + 1e-9:
                    kept[person] = value
            if kept:
                capped[coord] = kept
        return self._enforce_spatial_fairness(capped)

    def _enforce_spatial_fairness(self, energies: dict[Axial, dict[str, float]]) -> dict[Axial, dict[str, float]]:
        """Keep open end space from giving quieter speakers oversized territories.

        The radial reach cap is applied first. This pass trims only the weakest
        fringe cells when a quieter speaker would otherwise own more area than
        the louder adjacent territory ordering allows.
        """
        owner_by_coord: dict[Axial, str] = {}
        for coord, people in energies.items():
            if people:
                owner_by_coord[coord] = max(people.items(), key=lambda item: item[1])[0]
        counts: dict[str, int] = defaultdict(int)
        for owner in owner_by_coord.values():
            counts[owner] += 1
        ordered_people = sorted(
            counts,
            key=lambda person: (-self.talk_totals.get(person, 0.0), person),
        )
        for index, person in enumerate(ordered_people[1:], start=1):
            previous = ordered_people[index - 1]
            if self.talk_totals.get(person, 0.0) >= self.talk_totals.get(previous, 0.0) - 1e-12:
                continue
            multiplier = 1.0 if index == 1 else 1.15
            allowed = max(1, int(counts[previous] * multiplier))
            excess = counts[person] - allowed
            if excess <= 0:
                continue
            weakest = sorted(
                (
                    (sum(energies[coord].values()), coord)
                    for coord, owner in owner_by_coord.items()
                    if owner == person
                ),
                key=lambda item: (item[0], item[1]),
            )
            for _, coord in weakest[:excess]:
                energies[coord].pop(person, None)
                if energies[coord]:
                    owner_by_coord[coord] = max(energies[coord].items(), key=lambda item: item[1])[0]
                else:
                    energies.pop(coord, None)
                    owner_by_coord.pop(coord, None)
            counts[person] = allowed
        return energies

    def _person_peaks(self) -> dict[str, Point]:
        best: dict[str, tuple[float, Axial]] = {}
        for coord, people in self.energy.items():
            for person, value in people.items():
                if person not in best or value > best[person][0]:
                    best[person] = (value, coord)
        return {person: self.grid.cells[coord].center for person, (_, coord) in best.items()}


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(percentile * (len(ordered) - 1))))
    return ordered[index]
