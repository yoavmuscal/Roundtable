"""Pointy-top axial hex grid used by the room map."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, cos, floor, pi, sin, sqrt

from .geometry import Point


@dataclass(frozen=True, order=True, slots=True)
class Axial:
    q: int
    r: int

    def as_dict(self) -> dict[str, int]:
        return {"q": self.q, "r": self.r}


@dataclass(frozen=True, slots=True)
class HexCell:
    coord: Axial
    center: Point

    def vertices(self, size: float, scale: float = 0.9) -> list[Point]:
        radius = size * scale
        return [
            Point(
                self.center.x + radius * cos(-pi / 2.0 + index * pi / 3.0),
                self.center.y + radius * sin(-pi / 2.0 + index * pi / 3.0),
            )
            for index in range(6)
        ]


class HexGrid:
    """Meter-space pointy-top hexes around, but not centered under, the table."""

    def __init__(self, width_m: float, height_m: float, size_m: float = 0.10, margin_m: float = 0.8) -> None:
        if width_m <= 0 or height_m <= 0 or size_m <= 0 or margin_m < 0:
            raise ValueError("invalid hex grid dimensions")
        self.width_m = width_m
        self.height_m = height_m
        self.size_m = size_m
        self.margin_m = margin_m
        self.cells = self._generate()

    def axial_to_point(self, coord: Axial) -> Point:
        return Point(
            self.size_m * sqrt(3.0) * (coord.q + coord.r / 2.0),
            self.size_m * 1.5 * coord.r,
        )

    def point_to_axial_fractional(self, point: Point) -> tuple[float, float]:
        q = (sqrt(3.0) / 3.0 * point.x - point.y / 3.0) / self.size_m
        r = (2.0 / 3.0 * point.y) / self.size_m
        return q, r

    @staticmethod
    def axial_round(q: float, r: float) -> Axial:
        x = q
        z = r
        y = -x - z
        rx = round(x)
        ry = round(y)
        rz = round(z)
        x_diff = abs(rx - x)
        y_diff = abs(ry - y)
        z_diff = abs(rz - z)
        if x_diff > y_diff and x_diff > z_diff:
            rx = -ry - rz
        elif y_diff > z_diff:
            ry = -rx - rz
        else:
            rz = -rx - ry
        return Axial(rx, rz)

    def nearest(self, point: Point) -> HexCell:
        q, r = self.point_to_axial_fractional(point)
        coord = self.axial_round(q, r)
        return self.cells.get(coord, min(self.cells.values(), key=lambda cell: _distance_sq(cell.center, point)))

    def neighbors(self, coord: Axial) -> list[Axial]:
        return [
            Axial(coord.q + dq, coord.r + dr)
            for dq, dr in ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))
        ]

    def _generate(self) -> dict[Axial, HexCell]:
        q_min = floor((-self.margin_m - self.height_m) / (sqrt(3.0) * self.size_m)) - 2
        q_max = ceil((self.width_m + self.margin_m + self.height_m) / (sqrt(3.0) * self.size_m)) + 2
        r_min = floor(-self.margin_m / (1.5 * self.size_m)) - 2
        r_max = ceil((self.height_m + self.margin_m) / (1.5 * self.size_m)) + 2
        cells: dict[Axial, HexCell] = {}
        for r in range(r_min, r_max + 1):
            for q in range(q_min, q_max + 1):
                coord = Axial(q, r)
                center = self.axial_to_point(coord)
                if not (-self.margin_m <= center.x <= self.width_m + self.margin_m):
                    continue
                if not (-self.margin_m <= center.y <= self.height_m + self.margin_m):
                    continue
                if 0.0 < center.x < self.width_m and 0.0 < center.y < self.height_m:
                    continue
                cells[coord] = HexCell(coord, center)
        return cells


def _distance_sq(a: Point, b: Point) -> float:
    return (a.x - b.x) ** 2 + (a.y - b.y) ** 2
