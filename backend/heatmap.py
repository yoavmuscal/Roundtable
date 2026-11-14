from __future__ import annotations

from collections import defaultdict
from math import exp, sqrt
from typing import DefaultDict

from .contract import DEFAULT_TABLE_SIZE, HexCell, Point, Size

HEX_SIZE = 0.10
MARGIN = 0.80
SIGMA = 0.35


def hex_center(q: int, r: int) -> Point:
    return {
        "x": -MARGIN + HEX_SIZE * sqrt(3) * (q + r / 2),
        "y": -MARGIN + HEX_SIZE * 1.5 * r,
    }


def generate_hexes(table_size: Size = DEFAULT_TABLE_SIZE) -> list[tuple[int, int, Point]]:
    cells: list[tuple[int, int, Point]] = []
    max_q = int((table_size["width"] + MARGIN * 2) / (HEX_SIZE * sqrt(3))) + 4
    max_r = int((table_size["height"] + MARGIN * 2) / (HEX_SIZE * 1.5)) + 4
    for r in range(-2, max_r):
        for q in range(-2, max_q):
            center = hex_center(q, r)
            inside_extent = (
                -MARGIN <= center["x"] <= table_size["width"] + MARGIN
                and -MARGIN <= center["y"] <= table_size["height"] + MARGIN
            )
            under_table = (
                0 <= center["x"] <= table_size["width"]
                and 0 <= center["y"] <= table_size["height"]
            )
            if inside_extent and not under_table:
                cells.append((q, r, center))
    return cells


class HeatMap:
    def __init__(self, table_size: Size = DEFAULT_TABLE_SIZE) -> None:
        self.table_size = table_size
        self.cells = generate_hexes(table_size)
        self.energy: DefaultDict[str, dict[tuple[int, int], float]] = defaultdict(dict)
        self.reference = 0.0

    def deposit(self, person_id: str, position: Point, seconds: float, loudness: float) -> None:
        amount = seconds * max(0.0, loudness)
        if amount <= 0:
            return
        for q, r, center in self.cells:
            distance_sq = (center["x"] - position["x"]) ** 2 + (center["y"] - position["y"]) ** 2
            if distance_sq > (3 * SIGMA) ** 2:
                continue
            key = (q, r)
            self.energy[person_id][key] = self.energy[person_id].get(key, 0.0) + amount * exp(
                -distance_sq / (2 * SIGMA**2)
            )

    def snapshot(self) -> list[HexCell]:
        totals = {person_id: sum(values.values()) for person_id, values in self.energy.items()}
        top_talk = max(totals.values(), default=0.0)
        capped: dict[tuple[int, int], dict[str, float]] = defaultdict(dict)
        for person_id, values in self.energy.items():
            if not values:
                continue
            peak_key, peak_value = max(values.items(), key=lambda item: item[1])
            peak = hex_center(*peak_key)
            reach = max(0.35, 0.7 * sqrt(totals[person_id] / top_talk)) if top_talk else 0.35
            for key, value in values.items():
                center = hex_center(*key)
                if (center["x"] - peak["x"]) ** 2 + (center["y"] - peak["y"]) ** 2 <= reach**2:
                    capped[key][person_id] = value / max(peak_value, 1e-9)

        if capped:
            current_max = max(sum(values.values()) for values in capped.values())
            self.reference = self.reference * 0.9 + current_max * 0.1 if self.reference else current_max
        output: list[HexCell] = []
        for (q, r), values in capped.items():
            total = sum(values.values())
            if total <= 0:
                continue
            owner_id, owner_value = max(values.items(), key=lambda item: item[1])
            share = owner_value / total
            intensity = total / max(self.reference, 1e-9)
            opacity = 0.06 + 0.84 * sqrt(max(0.0, min(1.0, intensity)))
            if opacity < 0.08:
                continue
            output.append(
                {
                    "q": q,
                    "r": r,
                    "ownerId": owner_id,
                    "opacity": round(opacity, 3),
                    "share": round(share, 3),
                    "contested": share < 0.55,
                }
            )
        return output
